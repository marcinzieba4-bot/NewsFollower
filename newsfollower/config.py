"""Tunable rules and thresholds.

Everything the filters key off lives here so behaviour can be changed without
touching the scoring code. Weights are on a 0-100 scale; the final news score
is clamped to that range.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --- Source trust -----------------------------------------------------------
# Multiplier applied to the raw category score. A perfect headline off an
# unranked blog should not outrank a mediocre one off the wire.
SOURCE_TIERS: dict[str, float] = {
    # tier 1: wires and primary sources - what actually moves the tape
    "reuters": 1.00,
    "bloomberg": 1.00,
    "dowjones": 1.00,
    "ap": 1.00,
    "federalreserve.gov": 1.00,
    "bls.gov": 1.00,
    "sec.gov": 1.00,
    "treasury.gov": 1.00,
    "opec.org": 1.00,
    "company-ir": 1.00,
    "truthsocial": 0.95,   # primary but unstructured
    # tier 2: fast, reliable, occasionally derivative
    "cnbc": 0.85,
    "wsj": 0.90,
    "ft": 0.90,
    "barrons": 0.80,
    "axios": 0.80,
    "politico": 0.80,
    # tier 3: aggregators and syndicated recaps
    "yahoo": 0.60,
    "marketwatch": 0.65,
    "investing.com": 0.55,
    "zacks": 0.55,
    "seekingalpha": 0.50,
    # tier 4: commentary, unverified
    "zerohedge": 0.40,
    "reddit": 0.25,
    "x": 0.30,
    "blog": 0.25,
}
DEFAULT_SOURCE_WEIGHT = 0.45

# --- Category rules ---------------------------------------------------------
# Each entry: (category, base_weight, phrases). Matching is on lowercased text
# with word boundaries, so "cpi" will not fire inside "recipient".
CATEGORY_RULES: list[tuple[str, int, tuple[str, ...]]] = [
    ("systemic_credit", 50, (
        "bank run", "bailout", "insolvent", "insolvency", "receivership",
        "circuit breaker", "trading halted", "halts trading", "suspends redemptions",
        "sovereign default", "defaults on", "files for bankruptcy", "chapter 11",
        "counterparty", "margin call", "liquidity crisis", "credit event",
    )),
    ("central_bank", 48, (
        "rate hike", "rate cut", "raise rates", "cut rates", "hike rates",
        "interest rate decision", "fomc", "jackson hole", "fed chair",
        "federal reserve", "ecb", "bank of japan", "boj", "pboc",
        "central bank", "quantitative tightening", "quantitative easing",
        "emergency meeting",
        "basis point", "basis points", "hawkish", "dovish", "policy statement",
        "dot plot", "yield curve control",
    )),
    ("macro_data", 44, (
        "cpi", "core cpi", "ppi", "pce", "inflation report", "nonfarm payrolls",
        "non-farm payrolls", "jobs report", "unemployment rate", "gdp",
        "retail sales", "jobless claims", "ism", "pmi", "consumer confidence",
    )),
    ("geopolitics_supply", 42, (
        "airstrike", "missile strike", "invasion", "blockade", "embargo",
        "export ban", "sanctions", "strait of hormuz", "opec+", "opec",
        "production cut", "output cut", "supply disruption", "pipeline attack",
        "port closed", "shipments halted", "halt shipments", "halts shipments",
        "halt exports", "halts exports", "grain corridor", "grain ports",
        "black sea", "drone strike", "drone attack", "attack on", "attacks on",
        "export terminal", "refinery fire", "seizes", "closes airspace",
        "declares war", "ceasefire", "nuclear",
    )),
    ("policy_regulatory", 34, (
        "executive order", "tariff", "tariffs", "antitrust", "breaks up",
        "doj sues", "ftc sues", "sec charges", "indicted", "export controls",
        "price cap", "nationalize", "windfall tax", "ban on",
        "authorizes", "authorizing", "monopoly", "new rules", "rule change",
        "import quota", "export quota", "subsidy", "deregulation",
    )),
    ("earnings_guidance", 32, (
        "cuts guidance", "raises guidance", "guides below", "guides above",
        "profit warning", "misses estimates", "beats estimates", "tops estimates",
        "withdraws guidance", "revenue forecast", "gross margin", "earnings",
        "guides", "sees revenue", "sees full-year", "cuts outlook", "raises outlook",
        "quarterly results", "preliminary results",
    )),
    ("mna", 26, (
        "to acquire", "acquisition of", "merger with", "takeover bid",
        "buyout offer", "all-cash offer", "stake in", "spin off", "spinoff",
        "deal collapses", "walks away from",
    )),
    ("company_event", 20, (
        "ceo resigns", "cfo resigns", "steps down", "recall", "data breach",
        "fda approval", "fda rejects", "clinical trial", "strike action",
        "layoffs", "plant fire", "outage", "cyberattack", "short seller report",
    )),
]

# --- Modifiers --------------------------------------------------------------
# Words signalling an actual surprise / imminent action rather than commentary.
SURPRISE_PHRASES: tuple[str, ...] = (
    "unexpected", "unexpectedly", "surprise", "shock", "emergency",
    "worse than expected", "better than expected", "well above", "well below",
    "record", "highest since", "lowest since", "first time since",
    "decade low", "decade high", "multi-year low", "multi-year high",
    "breaking", "just in", "confirms", "announces", "signs", "authorizes",
    "orders", "declares", "halts", "suspends", "abruptly",
)
SURPRISE_BONUS = 12

# Hedging and second-hand framing. These are the classic false positives:
# previews, opinion, "what history shows" content and analyst chatter.
NOISE_PHRASES: tuple[str, ...] = (
    "what to expect", "what to watch", "preview", "history shows",
    "here's what", "here is what", "could", "may be", "might",
    "analysts say", "analyst says", "strategist says", "opinion",
    "op-ed", "explainer", "how to", "best stocks", "stocks to buy",
    "3 reasons", "5 reasons", "why you should", "outlook for",
    "poised to", "set to benefit", "in focus", "things to know",
    "recap", "wrap", "closing bell", "midday", "premarket movers",
    "week ahead", "look ahead", "reportedly", "rumor", "speculation",
    "denies report", "according to sources",
)
NOISE_PENALTY = 14

# Anything older than this (seconds) is stale for a trading alert; score is
# decayed linearly to zero across the window.
MAX_AGE_S = 30 * 60


@dataclass
class NewsConfig:
    """Thresholds for the headline filter."""

    important_threshold: float = 50.0
    critical_threshold: float = 68.0
    min_emit_score: float = 38.0
    max_age_s: float = MAX_AGE_S
    # Jaccard similarity above which two headlines count as the same story.
    dedup_similarity: float = 0.62
    dedup_ttl_s: float = 45 * 60
    # Names you actually trade. Index heavyweights belong here: a guidance
    # line from a top-10 weight is a macro event, not a single-stock story.
    watchlist: frozenset[str] = frozenset()
    watchlist_bonus: float = 12.0


@dataclass
class MoveConfig:
    """Thresholds for the quick-move detector.

    A move fires when it is BOTH statistically large for the symbol (z-score
    against its own recent volatility) and larger than a hard floor, so a
    sleepy symbol drifting 0.2% does not page anyone.
    """

    windows_s: tuple[float, ...] = (60.0, 300.0)
    min_z: float = 4.0
    min_abs_ret: float = 0.005          # 0.5% floor
    hard_ret: float = 0.02              # always fires regardless of z / volume
    min_volume_ratio: float = 1.8       # window volume vs typical
    require_volume: bool = True         # ignored when |ret| >= hard_ret
    cooldown_s: float = 120.0           # per symbol, per direction
    # Baseline needs this many ticks before any move can fire.
    warmup_ticks: int = 30
    history_s: float = 3600.0
    ewma_alpha: float = 0.06


@dataclass
class PipelineConfig:
    news: NewsConfig = field(default_factory=NewsConfig)
    move: MoveConfig = field(default_factory=MoveConfig)
    # A move and a critical headline on the same symbol inside this window are
    # treated as one confirmed event rather than two alerts.
    correlate_s: float = 300.0
