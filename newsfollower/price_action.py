"""Quick-move detection: fire only on price action that is fast AND unusual
for that particular symbol."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .config import MoveConfig
from .models import Move, Tick


@dataclass
class _SymbolState:
    ticks: deque = field(default_factory=deque)   # (ts, price, volume)
    var_per_s: float = 0.0        # EWMA of squared log-return per second
    vol_per_s: float = 0.0        # EWMA of traded volume per second
    n: int = 0
    last_fire_ts: dict[str, float] = field(default_factory=dict)  # direction -> ts
    last_dir: str = ""


class QuickMoveDetector:
    """Streaming detector. Feed it ticks; it returns a `Move` when a symbol
    moves far enough, fast enough, relative to its own recent behaviour.

    The baseline is per-symbol and self-updating, so the same thresholds work
    for a 0.4%-a-day bond ETF and a 6%-a-day small cap.
    """

    def __init__(self, cfg: MoveConfig | None = None):
        self.cfg = cfg or MoveConfig()
        self._state: dict[str, _SymbolState] = {}

    # -- baseline ----------------------------------------------------------
    def _update_baseline(self, st: _SymbolState, dt: float, logret: float,
                         volume: float) -> None:
        """Winsorised EWMA of per-second variance and volume.

        A single shock must not be absorbed into the baseline, or the second
        leg of the same move stops looking unusual and the detector goes deaf
        exactly when it matters. Returns are therefore clipped to 4x the
        current expected move before they update the estimate; a real regime
        change still gets there, just over several ticks.
        """
        if dt <= 0:
            return
        a = self.cfg.ewma_alpha
        if st.n:
            cap = 4.0 * math.sqrt(max(st.var_per_s, 1e-18) * dt)
            logret = max(-cap, min(cap, logret))
            volume = min(volume, 4.0 * st.vol_per_s * dt) if st.vol_per_s > 0 else volume
        inst_var = (logret * logret) / dt          # variance per second
        inst_vol = volume / dt
        if st.n == 0:
            st.var_per_s, st.vol_per_s = inst_var, inst_vol
        else:
            st.var_per_s = (1 - a) * st.var_per_s + a * inst_var
            st.vol_per_s = (1 - a) * st.vol_per_s + a * inst_vol
        st.n += 1

    def _trim(self, st: _SymbolState, now: float) -> None:
        cutoff = now - self.cfg.history_s
        while st.ticks and st.ticks[0][0] < cutoff:
            st.ticks.popleft()

    def _window_slice(self, st: _SymbolState, now: float, window_s: float):
        """Oldest tick at or before `now - window_s`, plus volume since then."""
        start = now - window_s
        anchor = None
        volume = 0.0
        for ts, price, vol in st.ticks:
            if ts <= start:
                anchor = (ts, price)
            else:
                volume += vol
        return anchor, volume

    # -- main entry point --------------------------------------------------
    def update(self, tick: Tick) -> Move | None:
        cfg = self.cfg
        st = self._state.setdefault(tick.symbol, _SymbolState())

        # Snapshot the baseline BEFORE folding this tick in: the move is
        # measured against how the symbol behaved up to now, not including
        # the move itself.
        sigma_per_s = math.sqrt(max(st.var_per_s, 1e-18))
        vol_per_s = st.vol_per_s

        if st.ticks:
            prev_ts, prev_price, _ = st.ticks[-1]
            if tick.price > 0 and prev_price > 0:
                self._update_baseline(st, tick.ts - prev_ts,
                                      math.log(tick.price / prev_price), tick.volume)

        st.ticks.append((tick.ts, tick.price, tick.volume))
        self._trim(st, tick.ts)

        if st.n < cfg.warmup_ticks:
            return None

        best: Move | None = None

        for window_s in cfg.windows_s:
            anchor, window_volume = self._window_slice(st, tick.ts, window_s)
            if anchor is None:
                continue
            _, p0 = anchor
            if p0 <= 0:
                continue

            ret = (tick.price - p0) / p0
            if abs(ret) < cfg.min_abs_ret:
                continue

            expected = sigma_per_s * math.sqrt(window_s)
            z = abs(math.log(tick.price / p0)) / expected if expected > 0 else float("inf")

            typical_volume = vol_per_s * window_s
            vol_ratio = window_volume / typical_volume if typical_volume > 0 else 0.0

            hard = abs(ret) >= cfg.hard_ret
            if not hard:
                if z < cfg.min_z:
                    continue
                if cfg.require_volume and vol_ratio < cfg.min_volume_ratio:
                    continue

            direction = "up" if ret > 0 else "down"
            last = st.last_fire_ts.get(direction, 0.0)
            # The cooldown has to be at least as long as the window: a 300s
            # window still straddles the shock 120s later and would otherwise
            # re-report the same move as a fresh one.
            if tick.ts - last < max(cfg.cooldown_s, window_s):
                continue

            move = Move(
                symbol=tick.symbol, ts=tick.ts, ret=ret, window_s=window_s,
                sigma=expected, z=z, volume_ratio=vol_ratio,
                price_from=p0, price_to=tick.price,
                reversal=bool(st.last_dir and st.last_dir != direction),
            )
            # Prefer the most violent read across windows: same move seen over
            # 60s and 300s should page once, at its sharpest.
            if best is None or abs(move.ret) > abs(best.ret):
                best = move

        if best is not None:
            st.last_fire_ts[best.direction] = best.ts
            st.last_dir = best.direction
        return best

    def baseline(self, symbol: str) -> tuple[float, int]:
        """(per-second sigma, ticks seen) - useful for diagnostics/tests."""
        st = self._state.get(symbol)
        if not st:
            return 0.0, 0
        return math.sqrt(max(st.var_per_s, 0.0)), st.n
