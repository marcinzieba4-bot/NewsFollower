"""Core data types shared by the news and price-action filters."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class Priority(IntEnum):
    """How loudly an alert should be delivered.

    DROP items are never emitted; they are returned only so callers can log
    why something was filtered out.
    """

    DROP = 0
    LOW = 1
    NORMAL = 2
    IMPORTANT = 3
    CRITICAL = 4


@dataclass
class NewsItem:
    """A single headline off a feed, before any filtering."""

    id: str
    headline: str
    source: str
    ts: float = field(default_factory=time.time)
    body: str = ""
    symbols: tuple[str, ...] = ()
    url: str = ""

    @property
    def text(self) -> str:
        return f"{self.headline}\n{self.body}".strip()


@dataclass
class Tick:
    """One trade or bar for a symbol. `volume` is per-tick, not cumulative."""

    symbol: str
    price: float
    ts: float = field(default_factory=time.time)
    volume: float = 0.0


@dataclass
class Move:
    """A detected quick move in a symbol's price."""

    symbol: str
    ts: float
    ret: float             # signed return over the window, e.g. -0.031 = -3.1%
    window_s: float        # seconds the move took
    sigma: float           # baseline per-second volatility used for scoring
    z: float               # move size in units of baseline volatility
    volume_ratio: float    # window volume vs. the symbol's typical window volume
    price_from: float
    price_to: float
    reversal: bool = False  # flipped sign versus the prior detected move

    @property
    def direction(self) -> str:
        return "up" if self.ret > 0 else "down"

    def describe(self) -> str:
        return (
            f"{self.symbol} {self.direction} {abs(self.ret) * 100:.2f}% in "
            f"{self.window_s:.0f}s ({self.z:.1f}σ, vol x{self.volume_ratio:.1f})"
        )


@dataclass
class Alert:
    """What the pipeline emits once something survives the filters."""

    kind: str              # news_critical | fast_move | confirmed | unexplained_move
    priority: Priority
    ts: float
    score: float
    reason: str
    symbols: tuple[str, ...] = ()
    item: Optional[NewsItem] = None
    move: Optional[Move] = None

    def describe(self) -> str:
        head = self.item.headline if self.item else (self.move.describe() if self.move else "")
        syms = ",".join(self.symbols) if self.symbols else "-"
        return f"[{self.priority.name}] {self.kind} ({syms}) score={self.score:.0f} :: {head} | {self.reason}"
