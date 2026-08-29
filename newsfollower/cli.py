"""Replay demo: `python -m newsfollower.cli`.

Feeds the filter a mix of real market-moving headlines from the week of
2026-08-24 and the commentary/preview noise that ran alongside them, then a
synthetic tick stream, and prints only what survives.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from .config import NewsConfig, PipelineConfig
from .models import NewsItem, Tick
from .pipeline import NewsFollower

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "headlines_2026_08.json"


def _synthetic_ticks(symbol: str, start: float, *, n: int = 240,
                     base: float = 100.0, shock_at: int | None = None,
                     shock: float = 0.0, seed: int = 7) -> list[Tick]:
    """Calm random walk, optionally with one abrupt repricing."""
    rng = random.Random(seed)
    price, ticks = base, []
    for i in range(n):
        price *= math.exp(rng.gauss(0.0, 0.0004))
        if shock_at is not None and i == shock_at:
            price *= 1.0 + shock
        volume = rng.uniform(800, 1200) * (12.0 if shock_at == i else 1.0)
        ticks.append(Tick(symbol=symbol, price=price, ts=start + i * 5.0, volume=volume))
    return ticks


def main() -> int:
    now = time.time()
    # Index heavyweights and the book we carry.
    watchlist = frozenset({"NVDA", "TSN", "SPY"})
    follower = NewsFollower(PipelineConfig(news=NewsConfig(watchlist=watchlist)))

    raw = json.loads(EXAMPLES.read_text())
    items = [
        NewsItem(id=r["id"], headline=r["headline"], source=r["source"],
                 ts=now + r["offset_min"] * 60.0, symbols=tuple(r.get("symbols", [])))
        for r in raw
    ]
    items.sort(key=lambda i: i.ts)

    print("=== headlines in ===")
    alerts = []
    for item in items:
        alert = follower.on_news(item)
        if alert:
            alerts.append(alert)
            print("  " + alert.describe())

    print(f"\n{len(alerts)} of {len(items)} headlines passed the filter.")
    print("\n=== dropped ===")
    for headline, why in follower.dropped:
        print(f"  - {headline[:68]:<68} :: {why[:70]}")

    print("\n=== price action ===")
    start = now - 20 * 60
    streams = [
        # Headline already printed, then the tape confirms it.
        _synthetic_ticks("TSN", start, shock_at=200, shock=-0.026),
        # Nobody has published anything - this is the one you want first.
        _synthetic_ticks("XYZ", start, base=42.0, shock_at=180, shock=-0.035, seed=11),
    ]
    for stream in streams:
        for tick in stream:
            alert = follower.on_tick(tick)
            if alert:
                print("  " + alert.describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
