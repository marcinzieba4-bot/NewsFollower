"""Free price feeds, normalised to `Tick`.

Yahoo's chart endpoint gives 1-minute bars for equities, indices, futures and
FX with no key; Coinbase's public ticker gives live crypto. Neither is a
professional feed - Yahoo bars lag and can be revised - so treat quick-move
alerts sourced from them as "go look", not "go trade".
"""

from __future__ import annotations

import json
import time

from ..models import Tick
from .http import ConditionalClient

YAHOO_CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               "{symbol}?range=1d&interval=1m")
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/{product}/ticker"

# Yahoo symbols worth watching by default: the index complex, rates proxy,
# energy, ags, gold, dollar. `^` and `=F` are URL-quoted at call time.
DEFAULT_SYMBOLS = ("^GSPC", "^NDX", "^VIX", "^TNX", "CL=F", "GC=F", "ZW=F", "DX-Y.NYB")


class YahooBarFeed:
    """Polls 1-minute bars and emits only bars not seen before.

    The last bar of a live session is still forming and gets revised, so it is
    held back until a newer bar appears behind it. Alerting on a provisional
    print is how a detector cries wolf.
    """

    def __init__(self, client: ConditionalClient | None = None):
        self.client = client or ConditionalClient()
        self._last_emitted: dict[str, float] = {}

    def poll(self, symbol: str, now: float | None = None) -> list[Tick]:
        from urllib.parse import quote
        url = YAHOO_CHART.format(symbol=quote(symbol, safe=""))
        resp = self.client.get(url, now=now)
        if not resp.ok:
            return []
        try:
            payload = json.loads(resp.body)
            result = payload["chart"]["result"][0]
            stamps = result["timestamp"]
            quote_block = result["indicators"]["quote"][0]
            closes, volumes = quote_block["close"], quote_block.get("volume", [])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return []

        # Drop the final bar: it is still forming.
        usable = max(0, len(stamps) - 1)
        since = self._last_emitted.get(symbol, 0.0)
        ticks: list[Tick] = []
        for i in range(usable):
            ts, price = stamps[i], closes[i]
            if price is None or ts <= since:
                continue
            volume = volumes[i] if i < len(volumes) and volumes[i] is not None else 0.0
            ticks.append(Tick(symbol=symbol, price=float(price),
                              ts=float(ts), volume=float(volume)))
        if ticks:
            self._last_emitted[symbol] = ticks[-1].ts
        return ticks


class CoinbaseFeed:
    """Live crypto ticker. One trade per poll, so poll fast or accept gaps."""

    def __init__(self, client: ConditionalClient | None = None):
        self.client = client or ConditionalClient()
        self._last_trade: dict[str, int] = {}

    def poll(self, product: str, now: float | None = None) -> list[Tick]:
        resp = self.client.get(COINBASE_TICKER.format(product=product), now=now)
        if not resp.ok:
            return []
        try:
            data = json.loads(resp.body)
            price = float(data["price"])
            trade_id = int(data.get("trade_id", 0))
            size = float(data.get("size", 0.0))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []
        if trade_id and self._last_trade.get(product) == trade_id:
            return []
        self._last_trade[product] = trade_id
        return [Tick(symbol=product, price=price,
                     ts=time.time() if now is None else now, volume=size)]
