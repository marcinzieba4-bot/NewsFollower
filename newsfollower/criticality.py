"""Headline scoring: keep the market-moving few, drop the rest."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .config import (
    CATEGORY_RULES,
    DEFAULT_SOURCE_WEIGHT,
    NOISE_PENALTY,
    NOISE_PHRASES,
    SOURCE_TIERS,
    SURPRISE_BONUS,
    SURPRISE_PHRASES,
    NewsConfig,
)
from .models import NewsItem, Priority

# Magnitudes in a headline are the single best cheap proxy for importance:
# "CPI rises 0.2%" vs "CPI rises 1.4%" are different trades.
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent|pct)")
_BPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:bps|basis points?)")
_MONEY_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(billion|bn|trillion|tn|million|mn)", re.I)
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")

LEVEL_PCT = 40.0

_MONEY_SCALE = {"million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9,
                "trillion": 1e12, "tn": 1e12}


def _phrase_hits(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Substring match, but anchored on word boundaries to avoid `cpi` in
    `recipient` or `ap` in `apple`."""
    hits = []
    for p in phrases:
        pattern = r"(?<!\w)" + re.escape(p) + r"(?!\w)"
        if re.search(pattern, text):
            hits.append(p)
    return hits


@dataclass
class NewsScore:
    score: float
    priority: Priority
    categories: tuple[str, ...]
    reason: str
    magnitude: float = 0.0

    @property
    def actionable(self) -> bool:
        return self.priority >= Priority.IMPORTANT


def source_weight(source: str) -> float:
    """Match the longest configured source key contained in `source`."""
    s = source.lower()
    best, best_len = DEFAULT_SOURCE_WEIGHT, -1
    for key, weight in SOURCE_TIERS.items():
        if key in s and len(key) > best_len:
            best, best_len = weight, len(key)
    return best


def magnitude_bonus(text: str) -> tuple[float, float]:
    """Return (bonus, largest magnitude seen) from numbers in the text.

    Percentages and basis points are the ones that matter for a macro tape;
    dollar amounts only count once they are in the billions.
    """
    largest = 0.0
    bonus = 0.0

    # Percentages at or above LEVEL_PCT are almost always levels, not moves
    # ("gross margin of 72%", "85% of the market"), and scoring them as move
    # size makes routine headlines look enormous.
    pcts = [float(m) for m in _PCT_RE.findall(text) if float(m) < LEVEL_PCT]
    if pcts:
        top = max(pcts)
        largest = max(largest, top)
        # 1% -> 2pts, 5% -> 10pts, capped at 15.
        bonus = max(bonus, min(15.0, top * 2.0))

    bps = [float(m) for m in _BPS_RE.findall(text)]
    if bps:
        top = max(bps)
        largest = max(largest, top / 100.0)
        bonus = max(bonus, min(15.0, top / 5.0))

    for amount, unit in _MONEY_RE.findall(text):
        usd = float(amount) * _MONEY_SCALE[unit.lower()]
        if usd >= 1e9:
            bonus = max(bonus, min(12.0, 4.0 + usd / 1e11))

    return bonus, largest


def extract_symbols(item: NewsItem) -> tuple[str, ...]:
    """Symbols explicitly tagged on the item, plus ticker-shaped tokens in
    parentheses like `(NVDA)` which feeds commonly emit."""
    found = list(item.symbols)
    for token in re.findall(r"\(([A-Z]{1,5})\)", item.headline):
        if token not in found:
            found.append(token)
    return tuple(found)


def score_news(item: NewsItem, cfg: NewsConfig | None = None,
               now: float | None = None) -> NewsScore:
    """Score a single headline. Higher is more likely to move a market."""
    cfg = cfg or NewsConfig()
    now = time.time() if now is None else now
    text = item.text.lower()

    categories: list[str] = []
    base = 0.0
    for name, weight, phrases in CATEGORY_RULES:
        hits = _phrase_hits(text, phrases)
        if not hits:
            continue
        categories.append(name)
        # Extra matching phrases in the same category add a little, but the
        # category weight dominates - we are not counting keywords.
        base = max(base, weight + min(6.0, 2.0 * (len(hits) - 1)))

    if base == 0.0:
        return NewsScore(0.0, Priority.DROP, (), "no market-relevant category matched")

    surprise = _phrase_hits(text, SURPRISE_PHRASES)
    noise = _phrase_hits(text, NOISE_PHRASES)
    mag_bonus, magnitude = magnitude_bonus(text)

    raw = base
    raw += SURPRISE_BONUS if surprise else 0.0
    raw += mag_bonus
    raw -= NOISE_PENALTY * min(2, len(noise))

    # Multiple independent categories in one headline (e.g. a central bank
    # story that also carries a macro print) is a genuine escalation.
    if len(categories) > 1:
        raw += 6.0 * (len(categories) - 1)

    score = raw * source_weight(item.source)

    # Staleness: a 25-minute-old "breaking" headline is not a trade.
    age = max(0.0, now - item.ts)
    if age >= cfg.max_age_s:
        return NewsScore(0.0, Priority.DROP, tuple(categories),
                         f"stale ({age / 60:.0f}m old)", magnitude)
    score *= 1.0 - (age / cfg.max_age_s) * 0.5

    score = max(0.0, min(100.0, score))

    symbols = extract_symbols(item)
    if cfg.watchlist and any(s in cfg.watchlist for s in symbols):
        score = min(100.0, score + cfg.watchlist_bonus)

    if score >= cfg.critical_threshold:
        priority = Priority.CRITICAL
    elif score >= cfg.important_threshold:
        priority = Priority.IMPORTANT
    elif score >= cfg.min_emit_score:
        priority = Priority.NORMAL
    else:
        priority = Priority.LOW

    bits = [f"cat={'+'.join(categories)}", f"src x{source_weight(item.source):.2f}"]
    if surprise:
        bits.append(f"surprise:{surprise[0]}")
    if mag_bonus:
        bits.append(f"magnitude+{mag_bonus:.0f}")
    if noise:
        bits.append(f"noise:{','.join(noise[:2])}")
    if age > 60:
        bits.append(f"age {age / 60:.0f}m")

    return NewsScore(score, priority, tuple(categories), "; ".join(bits), magnitude)
