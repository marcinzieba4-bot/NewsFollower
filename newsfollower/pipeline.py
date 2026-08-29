"""The follower itself: news in, ticks in, only the alerts worth acting on out."""

from __future__ import annotations

from collections import defaultdict, deque

from .config import PipelineConfig
from .criticality import extract_symbols, score_news
from .dedup import Deduper
from .models import Alert, Move, NewsItem, Priority, Tick
from .price_action import QuickMoveDetector


class NewsFollower:
    """Two independent filters joined by a correlation window.

    Either one alone is enough to page you:

    * a headline that scores IMPORTANT or above, or
    * a price move that is fast and unusual for that symbol,

    and when both fire on the same symbol inside `correlate_s` they collapse
    into one CRITICAL `confirmed` alert instead of two.
    """

    def __init__(self, cfg: PipelineConfig | None = None,
                 min_priority: Priority = Priority.IMPORTANT):
        self.cfg = cfg or PipelineConfig()
        self.min_priority = min_priority
        self.detector = QuickMoveDetector(self.cfg.move)
        self.deduper = Deduper(self.cfg.news.dedup_similarity,
                               self.cfg.news.dedup_ttl_s)
        self._recent_news: dict[str, deque] = defaultdict(lambda: deque(maxlen=16))
        self._recent_moves: dict[str, deque] = defaultdict(lambda: deque(maxlen=16))
        self.dropped: list[tuple[str, str]] = []   # (headline, why) for auditing

    # -- news --------------------------------------------------------------
    def on_news(self, item: NewsItem) -> Alert | None:
        cfg = self.cfg.news
        scored = score_news(item, cfg, now=item.ts)

        # Anything with no market relevance at all leaves here. Note the gate
        # is NORMAL, not `min_priority`: a merely-notable headline still gets
        # remembered, because if the tape moves on it in the next few minutes
        # that combination is worth waking someone for.
        if scored.priority < Priority.NORMAL:
            self.dropped.append((item.headline, scored.reason))
            return None

        dupe = self.deduper.check(item.headline, item.ts)
        if dupe is not None:
            self.dropped.append((item.headline, f"duplicate of: {dupe}"))
            return None
        self.deduper.add(item.headline, item.ts)

        symbols = extract_symbols(item)
        for sym in symbols:
            self._recent_news[sym].append((item.ts, item, scored))

        move = self._recent_move_for(symbols, item.ts)
        if move is not None:
            return Alert(
                kind="confirmed", priority=Priority.CRITICAL, ts=item.ts,
                score=min(100.0, scored.score + 10.0),
                reason=f"{scored.reason}; price already moved: {move.describe()}",
                symbols=symbols, item=item, move=move,
            )

        if scored.priority < self.min_priority:
            self.dropped.append(
                (item.headline, f"below {self.min_priority.name}: {scored.reason}"))
            return None

        return Alert(
            kind="news_critical", priority=scored.priority, ts=item.ts,
            score=scored.score, reason=scored.reason, symbols=symbols, item=item,
        )

    # -- prices ------------------------------------------------------------
    def on_tick(self, tick: Tick) -> Alert | None:
        move = self.detector.update(tick)
        if move is None:
            return None
        self._recent_moves[tick.symbol].append((move.ts, move))

        news = self._recent_news_for(tick.symbol, move.ts)
        if news is not None:
            item, scored = news
            return Alert(
                kind="confirmed", priority=Priority.CRITICAL, ts=move.ts,
                score=min(100.0, scored.score + 10.0),
                reason=f"{move.describe()} on: {item.headline}",
                symbols=(tick.symbol,), item=item, move=move,
            )

        # No headline explains it. In practice this is the most valuable of the
        # three: the tape is moving and the story has not printed yet.
        priority = Priority.CRITICAL if abs(move.ret) >= self.cfg.move.hard_ret \
            else Priority.IMPORTANT
        return Alert(
            kind="unexplained_move", priority=priority, ts=move.ts,
            score=min(100.0, 45.0 + move.z * 4.0 + abs(move.ret) * 400.0),
            reason=f"{move.describe()} with no matching headline"
                   + (" (reversal)" if move.reversal else ""),
            symbols=(tick.symbol,), move=move,
        )

    # -- correlation helpers ----------------------------------------------
    def _recent_move_for(self, symbols: tuple[str, ...], now: float) -> Move | None:
        for sym in symbols:
            for ts, move in reversed(self._recent_moves[sym]):
                if now - ts <= self.cfg.correlate_s:
                    return move
        return None

    def _recent_news_for(self, symbol: str, now: float):
        for ts, item, scored in reversed(self._recent_news[symbol]):
            if now - ts <= self.cfg.correlate_s:
                return item, scored
        return None
