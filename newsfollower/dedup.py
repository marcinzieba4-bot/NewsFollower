"""Story-level de-duplication.

Wires, aggregators and syndicated recaps publish the same event five times in
ten minutes. Alerting on each one is how a filter loses its user.
"""

from __future__ import annotations

import re

_STOP = frozenset(
    "a an the of to in on for at by and or as is are was were be been it its "
    "with from that this after over amid says said new".split()
)
_WORD_RE = re.compile(r"[a-z0-9$%.]+")


def shingles(text: str) -> frozenset[str]:
    words = [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 1]
    if len(words) < 2:
        return frozenset(words)
    return frozenset(f"{a} {b}" for a, b in zip(words, words[1:]))


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class Deduper:
    """Keeps recently seen headlines and reports whether a new one is a repeat."""

    def __init__(self, threshold: float = 0.62, ttl_s: float = 45 * 60,
                 containment: float = 0.80):
        self.threshold = threshold
        self.ttl_s = ttl_s
        # Jaccard alone under-reports when one outlet runs the same story with
        # an extra clause ("...; 2-year yield jumps 11bp"). The longer headline
        # drags the union up and the pair slips through. Containment catches
        # it: if one headline is essentially a subset of the other, it is the
        # same story with more or less detail.
        self.containment = containment
        self._seen: list[tuple[float, str, frozenset[str]]] = []

    def _expire(self, now: float) -> None:
        self._seen = [e for e in self._seen if now - e[0] <= self.ttl_s]

    def check(self, headline: str, now: float) -> str | None:
        """Return the matching earlier headline, or None if this is new."""
        self._expire(now)
        sa = shingles(headline)
        if not sa:
            return None
        for _, prev, sb in self._seen:
            inter = len(sa & sb)
            if not inter:
                continue
            union = len(sa | sb)
            if union and inter / union >= self.threshold:
                return prev
            if inter / min(len(sa), len(sb)) >= self.containment:
                return prev
        return None

    def add(self, headline: str, now: float) -> None:
        self._seen.append((now, headline, shingles(headline)))
