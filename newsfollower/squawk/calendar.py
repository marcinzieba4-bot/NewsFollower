"""Economic releases as actual-vs-expected.

A data print is the one headline whose importance is fully computable: the
number either landed on consensus or it didn't, and how far off it landed —
in units of that indicator's own typical surprise — is the whole story.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Priority

# (typical absolute surprise, market weight 0-1). The sigma is what a normal
# miss looks like for that series, so a 0.2pp CPI miss and a 60k payrolls miss
# both come out around 1 sigma. Weight is how much the tape cares at all.
INDICATORS: dict[str, tuple[float, float]] = {
    "cpi":              (0.10, 1.00),
    "core cpi":         (0.10, 1.00),
    "pce":              (0.10, 0.95),
    "core pce":         (0.10, 1.00),
    "ppi":              (0.20, 0.70),
    "nfp":              (60.0, 1.00),
    "nonfarm payrolls": (60.0, 1.00),
    "unemployment rate": (0.10, 0.85),
    "average hourly earnings": (0.10, 0.75),
    "gdp":              (0.40, 0.85),
    "retail sales":     (0.40, 0.75),
    "jobless claims":   (15.0, 0.55),
    "ism manufacturing": (1.50, 0.70),
    "ism services":     (1.50, 0.75),
    "pmi":              (1.50, 0.60),
    "consumer confidence": (3.00, 0.50),
    "durable goods":    (1.50, 0.50),
    "housing starts":   (60.0, 0.40),
    "trade balance":    (5.00, 0.35),
    "crude inventories": (2.00, 0.60),
    "industrial production": (0.30, 0.45),
}
DEFAULT_INDICATOR = (1.0, 0.45)


@dataclass
class Release:
    """One data print."""

    indicator: str
    region: str = ""
    period: str = ""          # "M/M", "Y/Y", "Q/Q", "AUG" ...
    actual: float | None = None
    expected: float | None = None
    prior: float | None = None
    unit: str = "%"           # "%", "K", "M", "" ...

    @property
    def params(self) -> tuple[float, float]:
        key = self.indicator.lower().strip()
        if key in INDICATORS:
            return INDICATORS[key]
        for name, values in INDICATORS.items():
            if name in key:
                return values
        return DEFAULT_INDICATOR

    @property
    def surprise(self) -> float | None:
        """Signed miss versus consensus, in the indicator's own units."""
        if self.actual is None or self.expected is None:
            return None
        return self.actual - self.expected

    @property
    def surprise_sigma(self) -> float:
        """Absolute miss in units of that indicator's typical surprise."""
        miss = self.surprise
        if miss is None:
            return 0.0
        sigma, _ = self.params
        return abs(miss) / sigma if sigma else 0.0

    def priority(self) -> Priority:
        """An in-line print on a second-tier series is not worth a squawk; a
        2-sigma miss on CPI is worth interrupting whatever else is playing."""
        _, weight = self.params
        strength = self.surprise_sigma * weight
        if strength >= 1.8:
            return Priority.CRITICAL
        if strength >= 0.8:
            return Priority.IMPORTANT
        if weight >= 0.8:
            # A top-tier release in line with consensus is still worth a line.
            return Priority.NORMAL
        return Priority.LOW

    def _fmt(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        text = f"{value:.1f}" if abs(value) < 100 else f"{value:.0f}"
        text = text.rstrip("0").rstrip(".") if "." in text else text
        return f"{text}{self.unit}"

    def squawk_body(self) -> str:
        parts = [self.indicator.upper()]
        if self.period:
            parts.append(self.period.upper())
        parts.append(self._fmt(self.actual))
        if self.expected is not None:
            parts.append(f"VS. EXP. {self._fmt(self.expected)}")
        if self.prior is not None:
            parts.append(f"(PREV. {self._fmt(self.prior)})")
        return " ".join(parts)


_NUM = r"[-+]?\d+(?:[.,]\d+)?"
_ACTUAL_RE = re.compile(
    rf"(?:rose|fell|rises|falls|came in at|printed at|at|was|of)\s+({_NUM})\s*(%|k|m|bln|mln)?",
    re.IGNORECASE)
_EXPECTED_RE = re.compile(
    rf"(?:vs\.?|versus|against)?\s*(?:exp\.?|expected|expectations? of|forecasts? of|"
    rf"consensus(?: of)?|estimates? of)\s*({_NUM})", re.IGNORECASE)
_EXPECTED_TRAILING_RE = re.compile(
    rf"({_NUM})\s*%?\s*(?:expected|forecast|consensus|estimate)", re.IGNORECASE)
_PRIOR_RE = re.compile(
    rf"(?:prev\.?|previous(?:ly)?|prior|last month|last reading)\s*(?:of|was|:)?\s*({_NUM})",
    re.IGNORECASE)
_PERIOD_RE = re.compile(r"\b(m/m|y/y|q/q|mom|yoy|qoq)\b", re.IGNORECASE)

_UNIT_NORMAL = {"%": "%", "k": "K", "m": "M", "bln": "BLN", "mln": "MLN"}


def _to_float(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_release(headline: str, indicator: str, *, region: str = "") -> Release | None:
    """Pull actual / expected / prior out of a prose headline.

    Returns None unless at least an actual was found - a headline that merely
    mentions CPI is not a print.
    """
    actual = expected = prior = None
    unit = "%"

    match = _ACTUAL_RE.search(headline)
    if match:
        actual = _to_float(match.group(1))
        if match.group(2):
            unit = _UNIT_NORMAL.get(match.group(2).lower(), "%")
    if actual is None:
        return None

    match = _EXPECTED_RE.search(headline) or _EXPECTED_TRAILING_RE.search(headline)
    if match:
        expected = _to_float(match.group(1))
    match = _PRIOR_RE.search(headline)
    if match:
        prior = _to_float(match.group(1))

    period = ""
    match = _PERIOD_RE.search(headline)
    if match:
        period = match.group(1).upper().replace("MOM", "M/M") \
                                       .replace("YOY", "Y/Y").replace("QOQ", "Q/Q")

    return Release(indicator=indicator, region=region, period=period,
                   actual=actual, expected=expected, prior=prior, unit=unit)


def find_indicator(text: str) -> str:
    """Longest configured indicator name appearing in the text, or ""."""
    lowered = text.lower()
    best = ""
    for name in INDICATORS:
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lowered) and len(name) > len(best):
            best = name
    return best
