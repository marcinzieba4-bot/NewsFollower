"""The squawk service: free feeds in, spoken tape out.

    python -m newsfollower.squawk.runner --duration 120 --speak

Startup primes every feed: the first poll of an RSS feed returns twenty
historical items, and reading yesterday's news aloud as if it were breaking is
the fastest way to make a squawk untrustworthy. Priming marks them seen
without emitting, so only genuinely new items reach the tape.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import NewsConfig, PipelineConfig
from ..criticality import extract_symbols
from ..models import Alert, NewsItem, Priority, Tick
from ..pipeline import NewsFollower
from ..feeds.http import ConditionalClient
from ..feeds.prices import DEFAULT_SYMBOLS, CoinbaseFeed, YahooBarFeed
from ..feeds.rss import parse_feed
from ..feeds.sources import LIVE_SOURCES, SOURCES, Source
from .audio import Speaker
from .calendar import find_indicator, parse_release
from .format import SquawkLine, to_squawk
from .tape import Tape


@dataclass
class Stats:
    polls: int = 0
    not_modified: int = 0
    errors: int = 0
    items: int = 0
    emitted: int = 0
    ticks: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self, name: str, by: int = 1) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + by)


class FeedPoller(threading.Thread):
    """One thread per source. Threads, not asyncio, because the whole thing is
    blocking I/O against twenty endpoints and the thread count stays trivial."""

    def __init__(self, source: Source, out: queue.Queue, stats: Stats,
                 stop: threading.Event, client: ConditionalClient,
                 prime_only: threading.Event):
        super().__init__(daemon=True, name=f"poll-{source.name}")
        self.source, self.out, self.stats = source, out, stats
        self.stop, self.client, self.prime_only = stop, client, prime_only
        self.seen: set[str] = set()

    def run(self) -> None:
        # Stagger starts so twenty feeds do not fire simultaneously.
        if self.stop.wait(hash(self.source.name) % 1000 / 1000.0):
            return
        while not self.stop.is_set():
            resp = self.client.get(self.source.url)
            self.stats.bump("polls")
            if resp.not_modified:
                self.stats.bump("not_modified")
            elif resp.ok:
                for item in parse_feed(resp.body, self.source.key):
                    if item.id in self.seen:
                        continue
                    self.seen.add(item.id)
                    if self.prime_only.is_set():
                        continue          # historical backlog: record, don't squawk
                    self.stats.bump("items")
                    self.out.put((self.source, item))
            elif resp.error and resp.error != "backoff":
                self.stats.bump("errors")
            if self.stop.wait(self.source.poll_s):
                return


class PricePoller(threading.Thread):
    def __init__(self, symbols: tuple[str, ...], crypto: tuple[str, ...],
                 out: queue.Queue, stats: Stats, stop: threading.Event,
                 interval: float = 20.0):
        super().__init__(daemon=True, name="poll-prices")
        self.symbols, self.crypto = symbols, crypto
        self.out, self.stats, self.stop, self.interval = out, stats, stop, interval
        self.yahoo, self.coinbase = YahooBarFeed(), CoinbaseFeed()

    def run(self) -> None:
        while not self.stop.is_set():
            for symbol in self.symbols:
                for tick in self.yahoo.poll(symbol):
                    self.stats.bump("ticks")
                    self.out.put((None, tick))
            for product in self.crypto:
                for tick in self.coinbase.poll(product):
                    self.stats.bump("ticks")
                    self.out.put((None, tick))
            if self.stop.wait(self.interval):
                return


class SquawkService:
    """Wires the filters to the feeds, the tape and the speaker."""

    def __init__(self, *, sources: tuple[Source, ...] = LIVE_SOURCES,
                 symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
                 crypto: tuple[str, ...] = ("BTC-USD", "ETH-USD"),
                 watchlist: frozenset[str] = frozenset(),
                 min_priority: Priority = Priority.IMPORTANT,
                 speak: bool = False, log_path: Path | None = None,
                 price_interval: float = 20.0):
        self.sources, self.symbols, self.crypto = sources, symbols, crypto
        self.follower = NewsFollower(
            PipelineConfig(news=NewsConfig(watchlist=watchlist)),
            min_priority=min_priority)
        self.tape = Tape(log_path=log_path)
        self.speaker = Speaker(enabled=speak)
        self.stats = Stats()
        self.queue: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.prime_only = threading.Event()
        self.client = ConditionalClient()
        self.price_interval = price_interval
        self._threads: list[threading.Thread] = []

    # -- formatting --------------------------------------------------------
    def squawk_for(self, alert: Alert, source: Source | None) -> SquawkLine:
        """Turn an alert into a tape line. Data prints get the release
        treatment (actual vs exp vs prior); everything else is formatted prose."""
        region = source.region if source else ""
        if alert.item is not None:
            indicator = find_indicator(alert.item.headline)
            if indicator:
                release = parse_release(alert.item.headline, indicator, region=region)
                if release is not None and release.actual is not None:
                    line = to_squawk(alert.item.headline, priority=alert.priority,
                                     ts=alert.ts, source=alert.item.source,
                                     symbols=alert.symbols, url=alert.item.url,
                                     default_region=region)
                    # The release beats the prose: it is the same information,
                    # ordered the way a trader reads it.
                    line.body = release.squawk_body()
                    line.priority = max(alert.priority, release.priority())
                    return line
            return to_squawk(alert.item.headline, priority=alert.priority,
                             ts=alert.ts, source=alert.item.source,
                             symbols=alert.symbols, url=alert.item.url,
                             default_region=region)

        move = alert.move
        assert move is not None
        arrow = "▲" if move.ret > 0 else "▼"
        body = (f"{move.symbol} {arrow} {abs(move.ret) * 100:.2f}% IN "
                f"{move.window_s:.0f}S ({move.z:.1f} SIGMA)")
        if alert.kind == "unexplained_move":
            body += " - NO HEADLINE"
        return SquawkLine(ts=alert.ts, body=body, priority=alert.priority,
                          symbols=alert.symbols, source="tape")

    def handle(self, source: Source | None, payload) -> None:
        if isinstance(payload, Tick):
            alert = self.follower.on_tick(payload)
        else:
            item: NewsItem = payload
            if source and source.region and not item.symbols:
                item.symbols = extract_symbols(item)
            alert = self.follower.on_news(item)
        if alert is None:
            return
        line = self.squawk_for(alert, source)
        self.tape.emit(line, note=alert.kind)
        self.speaker.say(line.spoken(), line.priority)
        self.stats.bump("emitted")

    # -- lifecycle ---------------------------------------------------------
    def start(self, prime_s: float = 6.0) -> None:
        self.prime_only.set()
        for source in self.sources:
            poller = FeedPoller(source, self.queue, self.stats, self.stop,
                                self.client, self.prime_only)
            poller.start()
            self._threads.append(poller)
        if self.symbols or self.crypto:
            prices = PricePoller(self.symbols, self.crypto, self.queue,
                                 self.stats, self.stop, self.price_interval)
            prices.start()
            self._threads.append(prices)

        self.tape.banner(
            f"NewsFollower squawk | {len(self.sources)} feeds | "
            f"{len(self.symbols) + len(self.crypto)} symbols | "
            f"audio: {self.speaker.backend_name} | priming {prime_s:.0f}s...")
        time.sleep(prime_s)
        self.prime_only.clear()
        # Ticks queued during priming are the day's history: feed them to the
        # detector to build its per-symbol baseline, but suppress alerts.
        self._drain_baseline()
        self.tape.banner("--- LIVE ---")

    def _drain_baseline(self) -> None:
        warmed = 0
        while True:
            try:
                _, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(payload, Tick):
                self.follower.detector.update(payload)
                warmed += 1
        if warmed:
            self.tape.banner(f"    baseline warmed on {warmed} historical bars")

    def run(self, duration: float | None = None, prime_s: float = 6.0) -> None:
        self.start(prime_s=prime_s)
        deadline = time.time() + duration if duration else None
        try:
            while deadline is None or time.time() < deadline:
                try:
                    source, payload = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.handle(source, payload)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop.set()
        self.speaker.stop()
        s = self.stats
        self.tape.banner(
            f"--- STOPPED --- polls={s.polls} 304s={s.not_modified} "
            f"errors={s.errors} items={s.items} bars={s.ticks} "
            f"squawked={s.emitted} filtered={len(self.follower.dropped)}")
        self.tape.close()


def replay(sources: tuple[Source, ...], *, min_priority: Priority,
           watchlist: frozenset[str] = frozenset(), limit: int = 0) -> int:
    """Run everything currently sitting in the feeds through the filter.

    This is the tuning tool: it shows what the squawk would have said about
    the news cycle as it stands, and what it threw away. Staleness scoring is
    disabled here - feed backlogs are hours old by definition, and dropping
    them all on age would say nothing about the rules being tested.
    """
    client = ConditionalClient()
    collected: list[tuple[Source, NewsItem]] = []
    for source in sources:
        resp = client.get(source.url)
        if not resp.ok:
            continue
        for item in parse_feed(resp.body, source.key):
            collected.append((source, item))
    collected.sort(key=lambda pair: pair[1].ts)
    if limit:
        collected = collected[-limit:]

    follower = NewsFollower(
        PipelineConfig(news=NewsConfig(watchlist=watchlist, max_age_s=float("inf"))),
        min_priority=min_priority)
    tape = Tape()
    service = SquawkService.__new__(SquawkService)   # formatting only
    tape.banner(f"REPLAY | {len(collected)} items from {len(sources)} feeds")

    emitted = 0
    for source, item in collected:
        alert = follower.on_news(item)
        if alert is None:
            continue
        tape.emit(service.squawk_for(alert, source), note=alert.kind)
        emitted += 1

    tape.banner(f"--- {emitted} squawked, {len(follower.dropped)} filtered ---")
    reasons: dict[str, int] = {}
    for _, why in follower.dropped:
        key = why.split(":")[0].split(";")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {count:4d}  {reason}")
    return 0


def check_sources() -> int:
    """Verify every registered feed still parses. Exit code = failures."""
    client = ConditionalClient()
    failures = 0
    for source in SOURCES:
        resp = client.get(source.url)
        if resp.ok:
            items = parse_feed(resp.body, source.key)
            status = f"OK    {len(items):3d} items"
            if not items:
                status, failures = "EMPTY   parsed 0 items", failures + 1
        else:
            status = f"FAIL  {resp.error or resp.status}"
            if source.reachable:
                failures += 1
            else:
                status += "  (known dead)"
        print(f"{source.name:34} {status}")
        if source.note:
            print(f"{'':34} note: {source.note}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsfollower-squawk",
                                     description="Free real-time market squawk.")
    parser.add_argument("--check", action="store_true",
                        help="verify every registered source and exit")
    parser.add_argument("--replay", action="store_true",
                        help="run the current feed contents through the filter and exit")
    parser.add_argument("--limit", type=int, default=0,
                        help="with --replay, keep only the N most recent items")
    parser.add_argument("--duration", type=float, default=None,
                        help="seconds to run (default: until Ctrl-C)")
    parser.add_argument("--speak", action="store_true", help="read alerts aloud")
    parser.add_argument("--primary-only", action="store_true",
                        help="central banks, statistical agencies and exchanges only")
    parser.add_argument("--min-priority", default="IMPORTANT",
                        choices=[p.name for p in Priority if p >= Priority.LOW])
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="comma-separated Yahoo symbols to watch")
    parser.add_argument("--watchlist", default="",
                        help="comma-separated tickers to escalate")
    parser.add_argument("--log", type=Path, default=None, help="append JSONL here")
    parser.add_argument("--prime", type=float, default=6.0,
                        help="seconds spent absorbing feed backlog before going live")
    args = parser.parse_args(argv)

    if args.check:
        failures = check_sources()
        print(f"\n{failures} unexpected failure(s)")
        return 1 if failures else 0

    from .sources_filter import select_sources
    watchlist = frozenset(s.strip().upper() for s in args.watchlist.split(",") if s.strip())

    if args.replay:
        return replay(select_sources(primary_only=args.primary_only),
                      min_priority=Priority[args.min_priority],
                      watchlist=watchlist, limit=args.limit)

    service = SquawkService(
        sources=select_sources(primary_only=args.primary_only),
        symbols=tuple(s for s in args.symbols.split(",") if s),
        watchlist=watchlist,
        min_priority=Priority[args.min_priority],
        speak=args.speak, log_path=args.log)
    service.run(duration=args.duration, prime_s=args.prime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
