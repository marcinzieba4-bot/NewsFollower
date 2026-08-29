"""Prose headline -> squawk line.

A squawk line is not a headline. It is stripped to the claim, attributed to
whoever made it, tagged with a region, and short enough to read aloud in about
three seconds:

    Fed Chair Warsh says central bank still has work to do on inflation
    -> *(US) FED'S WARSH: CENTRAL BANK STILL HAS WORK TO DO ON INFLATION
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..models import Priority

# --- region -----------------------------------------------------------------
REGION_BY_ORG = {
    "FED": "US", "TREASURY": "US", "WHITE HOUSE": "US", "SEC": "US",
    "BLS": "US", "CENSUS": "US", "EIA": "US", "USDA": "US", "FDA": "US",
    "ECB": "EU", "EU COMMISSION": "EU",
    "BOE": "UK", "BOJ": "JP", "PBOC": "CN", "SNB": "CH", "RBA": "AU",
    "BOC": "CA", "CBRT": "TR", "OPEC": "OPEC", "IMF": "IMF", "NATO": "NATO",
}
# Matched by earliest position in the text, not list order: the subject of a
# headline leads it, so "Ukrainian strikes on Russian ports" is a (UA) story
# even though "russia" is also present. List order only breaks ties.
REGION_KEYWORDS: tuple[tuple[str, str, bool], ...] = (
    # (region, keyword, whole_word). Whole-word matching matters: without it
    # "versus" contains "us" and every second headline becomes a US story.
    ("OPEC", "opec", True), ("IMF", "imf", True), ("NATO", "nato", True),
    ("US", "united states", True), ("US", "u.s.", False), ("US", "us", True),
    ("US", "washington", True), ("US", "white house", True),
    ("US", "congress", True), ("US", "trump", True), ("US", "fed", True),
    ("EU", "euro zone", True), ("EU", "eurozone", True),
    ("EU", "european union", True), ("EU", "brussels", True), ("EU", "ecb", True),
    ("DE", "german", False), ("FR", "france", True), ("FR", "french", True),
    ("IT", "italy", True), ("ES", "spain", True),
    ("UK", "britain", True), ("UK", "british", True), ("UK", "london", True),
    ("UK", "uk", True), ("UK", "gilt", False),
    ("CN", "china", True), ("CN", "chinese", True), ("CN", "beijing", True),
    ("JP", "japan", False), ("JP", "tokyo", True),
    ("RU", "russia", False), ("RU", "moscow", True), ("RU", "kremlin", True),
    ("UA", "ukrain", False), ("UA", "kyiv", True),
    ("IN", "india", True), ("BR", "brazil", True),
    ("IL", "israel", False), ("IR", "iran", False), ("SA", "saudi", False),
    ("TR", "turkey", True), ("CA", "canada", True), ("AU", "australia", True),
    ("MX", "mexico", True), ("KR", "korea", False),
)

_REGION_PATTERNS: tuple[tuple[str, "re.Pattern[str]", int], ...] = tuple(
    (region, re.compile(r"(?<!\w)" + re.escape(kw) + (r"(?!\w)" if whole else "")), order)
    for order, (region, kw, whole) in enumerate(REGION_KEYWORDS)
)

SOURCE_REGION_HINT = {
    "federalreserve.gov": "US", "bls.gov": "US", "census.gov": "US",
    "sec.gov": "US", "eia.gov": "US", "nasdaqtrader": "US", "treasury.gov": "US",
    "ecb": "EU", "boe": "UK", "bbc": "UK", "guardian": "UK",
}

# --- speaker attribution ----------------------------------------------------
ORG_ALIASES: tuple[tuple[str, str], ...] = (
    (r"federal reserve|fed(?:eral)?\b", "FED"),
    (r"european central bank|ecb", "ECB"),
    (r"bank of england|boe", "BOE"),
    (r"bank of japan|boj", "BOJ"),
    (r"people's bank of china|pboc", "PBOC"),
    (r"swiss national bank|snb", "SNB"),
    (r"reserve bank of australia|rba", "RBA"),
    (r"bank of canada|boc", "BOC"),
    (r"white house", "WHITE HOUSE"),
    (r"treasury", "TREASURY"),
    (r"opec\+?", "OPEC"),
    (r"\bimf\b|international monetary fund", "IMF"),
    (r"\bnato\b", "NATO"),
    (r"\becb\b", "ECB"),
)

_TITLES = (r"chair(?:man|woman|person)?|president|governor|deputy governor|"
           r"vice chair|chief(?: economist)?|secretary|official|policymaker|"
           r"member|minister|spokesman|spokeswoman|spokesperson|ceo|cfo")
# "tells"/"told" take an indirect object ("tells CNBC that ..."), so the
# outlet has to be consumed or it lands at the front of the squawk body.
_TELL_VERBS = r"tells?|told"
_SAY_VERBS = (r"says?|said|adds|added|warns?|warned|notes?|noted|"
              r"comments?|commented|reiterates?|reiterated|states?|stated|"
              r"argues?|argued|signals?|signalled|signaled|"
              r"expresses|expressed|voices?|voiced|flags?|flagged|"
              r"urges?|urged|advocates?|advocated|stresses|stressed|"
              r"insists?|insisted|repeats?|repeated|denies|denied")

# Words that follow an institution but are not a person. Without this,
# "Federal Reserve Board announces ..." attributes the line to "BOARD".
_NOT_A_NAME = (r"board|bank|committee|council|group|staff|office|system|"
               r"branch|inc|corp|holdings|department|ministry")

# The org must be a *recognised* institution. An open-ended pattern here is
# ambiguous with the name that follows: "ECB's Lagarde" parses just as happily
# as org="EC", name="B's Lagarde", and every line comes out unattributed.
_ORG_PATTERN = "|".join(f"(?:{pattern})" for pattern, _ in ORG_ALIASES)

# "Fed Chair Warsh says X" / "ECB's Lagarde said X" / "Fed's Williams: X".
# The name keeps case-sensitivity via (?-i:...) so a lowercase word cannot pass
# as a surname.
_SPEAKER_RE = re.compile(
    # Up to two capitalised words may precede the institution, so regional
    # Fed presidents ("Kansas City Fed's Schmid") attribute correctly.
    r"^(?:(?-i:[A-Z][\w.'-]+)\s+){0,2}"
    r"(?P<org>" + _ORG_PATTERN + r")"
    r"(?:'s)?\s+"
    r"(?:(?:" + _TITLES + r")\s+)*"
    r"(?!(?:" + _NOT_A_NAME + r")(?!\w))"
    r"(?P<name>(?-i:[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+)?))"
    r"\s*(?:"
    r"(?:" + _TELL_VERBS + r")\s+(?-i:[A-Z][\w.&'-]+)\s+(?:that\s+)?"
    r"|(?:" + _SAY_VERBS + r")\s+(?:that\s+)?"
    r"|:\s*)"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)

# --- text compression -------------------------------------------------------
COMPRESSIONS: tuple[tuple[str, str], ...] = (
    (r"\bbasis points?\b|\bbps\b", "BPS"),
    (r"\bpercentage points?\b", "PPTS"),
    (r"\bpercent\b", "%"),
    (r"\btrillions?\b|\btn\b", "TRLN"),
    (r"\bbillions?\b|\bbn\b", "BLN"),
    (r"\bmillions?\b|\bmn\b", "MLN"),
    (r"\bthousands?\b", "K"),
    (r"\bbarrels per day\b|\bbarrels/day\b", "BPD"),
    (r"\byear[- ]on[- ]year\b|\byear[- ]over[- ]year\b", "Y/Y"),
    (r"\bmonth[- ]on[- ]month\b|\bmonth[- ]over[- ]month\b", "M/M"),
    (r"\bquarter[- ]on[- ]quarter\b", "Q/Q"),
    (r"\bversus\b|\bcompared (?:to|with)\b", "VS."),
    (r"\bexpectations?\b|\bexpected\b|\bestimates?\b|\bforecasts?\b", "EXP."),
    (r"\bprevious(?:ly)?\b|\bprior\b", "PREV."),
    (r"\bfourth quarter\b", "Q4"), (r"\bthird quarter\b", "Q3"),
    (r"\bsecond quarter\b", "Q2"), (r"\bfirst quarter\b", "Q1"),
    (r"\bfull[- ]year\b", "FY"),
    (r"\bgross domestic product\b", "GDP"),
    (r"\bconsumer price index\b", "CPI"),
    (r"\bproducer price index\b", "PPI"),
    (r"\bnon[- ]?farm payrolls?\b", "NFP"),
    (r"\bfederal open market committee\b", "FOMC"),
    (r"\binterest rates?\b", "RATES"),
    (r"\bunited states\b", "US"),
    (r"\bunited kingdom\b", "UK"),
)

# Publication cruft appended by aggregators.
_TRAILER_RE = re.compile(
    r"\s*[-|–—]\s*(reuters|cnbc|bloomberg|marketwatch|yahoo finance|"
    r"the guardian|bbc(?: news)?|financial times|ft\.com|barron's|axios|"
    r"investing\.com|the new york times)\s*$", re.IGNORECASE)
_LEADER_RE = re.compile(
    r"^(breaking|just in|update \d*|exclusive|live|watch|urgent)\s*[:\-–]\s*",
    re.IGNORECASE)

# Dollar amounts: "$108 billion" -> "USD 108BLN" reads better aloud.
_USD_RE = re.compile(r"\$\s?(\d[\d,.]*)\s*(trillion|billion|million|tn|bn|mn)?", re.I)
_UNIT_MAP = {"trillion": "TRLN", "tn": "TRLN", "billion": "BLN", "bn": "BLN",
             "million": "MLN", "mn": "MLN"}


@dataclass
class SquawkLine:
    """One line of tape."""

    ts: float
    body: str
    priority: Priority
    region: str = ""
    org: str = ""
    speaker: str = ""
    symbols: tuple[str, ...] = ()
    source: str = ""
    url: str = ""

    @property
    def marker(self) -> str:
        # Wire convention: * flags a headline you act on now.
        return "*" if self.priority >= Priority.CRITICAL else "-"

    def render(self, *, with_time: bool = True) -> str:
        stamp = time.strftime("%H:%M:%S", time.gmtime(self.ts)) + " " if with_time else ""
        tag = f"({self.region}) " if self.region else ""
        return f"{stamp}{self.marker}{tag}{self.body}"

    def spoken(self) -> str:
        """Expanded back out for text-to-speech - a reader saying 'B-P-S' is
        worse than one saying 'basis points'."""
        text = self.body
        for abbrev, word in (("BPS", "basis points"), ("BLN", " billion"),
                             ("MLN", " million"), ("TRLN", " trillion"),
                             ("EXP.", "expected"), ("PREV.", "previous"),
                             ("VS.", "versus"), ("Y/Y", "year on year"),
                             ("M/M", "month on month"), ("Q/Q", "quarter on quarter"),
                             ("BPD", "barrels per day")):
            text = text.replace(abbrev, word)
        prefix = f"{self.region}. " if self.region else ""
        return (prefix + text.capitalize()).replace("  ", " ")


def detect_region(text: str, source: str = "", default: str = "") -> str:
    lowered = text.lower()
    best: tuple[int, int, str] | None = None
    for region, pattern, order in _REGION_PATTERNS:
        match = pattern.search(lowered)
        if match is None:
            continue
        candidate = (match.start(), order, region)
        if best is None or candidate < best:
            best = candidate
    if best is not None:
        return best[2]
    for key, region in SOURCE_REGION_HINT.items():
        if key in source.lower():
            return region
    return default


def normalise_org(raw: str) -> str:
    lowered = raw.lower().strip()
    for pattern, canonical in ORG_ALIASES:
        if re.fullmatch(pattern, lowered) or re.fullmatch(pattern + r"'s", lowered):
            return canonical
    for pattern, canonical in ORG_ALIASES:
        if re.search(pattern, lowered):
            return canonical
    return ""


def compress(text: str) -> str:
    def usd(match: re.Match) -> str:
        amount, unit = match.group(1), (match.group(2) or "").lower()
        return f"USD {amount}{_UNIT_MAP.get(unit, '')}"

    text = _USD_RE.sub(usd, text)
    for pattern, replacement in COMPRESSIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    # "0.4 percent" becomes "0.4 %" through the table; close it up.
    text = re.sub(r"(\d)\s+%", r"\1%", text)
    return text.strip()


def strip_cruft(headline: str) -> str:
    return _LEADER_RE.sub("", _TRAILER_RE.sub("", headline)).strip()


def split_speaker(headline: str) -> tuple[str, str, str]:
    """-> (org, speaker, remainder). Empty org/speaker when nothing attributed."""
    match = _SPEAKER_RE.match(headline)
    if not match:
        return "", "", headline
    org = normalise_org(match.group("org"))
    name = match.group("name").strip()
    rest = match.group("rest").strip()
    # A bare name with no recognisable institution is not an attribution worth
    # restructuring the line for, and the regex is loose enough to misfire.
    if not org or not rest or len(rest.split()) < 3:
        return "", "", headline
    return org, name.upper(), rest


def to_squawk(headline: str, *, priority: Priority, ts: float, source: str = "",
              symbols: tuple[str, ...] = (), url: str = "",
              default_region: str = "", width: int = 108) -> SquawkLine:
    """Format one headline as a squawk line."""
    cleaned = strip_cruft(headline)
    org, speaker, rest = split_speaker(cleaned)
    region = detect_region(cleaned, source, default_region)
    if org and org in REGION_BY_ORG:
        region = REGION_BY_ORG[org]

    body = compress(rest).upper()
    if org and speaker:
        body = f"{org}'S {speaker}: {body}"
    elif org:
        body = f"{org}: {body}"
    elif region:
        # The region is already in the tag; "(US) US CPI ROSE" says it twice.
        # Lookahead, not \b: "OPEC+" must not be shortened to "+".
        body = re.sub(rf"^{re.escape(region)}(?=[\s,:-]|$)[\s,:-]*", "", body)

    # A ticker is what the reader scans for, so lead with it when we have one.
    if symbols and not org:
        lead = "/".join(symbols[:3])
        if not body.startswith(lead):
            body = f"{lead}: {body}"

    if len(body) > width:
        cut = body[:width].rsplit(" ", 1)[0]
        body = cut + "..."

    return SquawkLine(ts=ts, body=body, priority=priority, region=region,
                      org=org, speaker=speaker, symbols=symbols,
                      source=source, url=url)
