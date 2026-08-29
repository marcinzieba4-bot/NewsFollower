import math
import random

from newsfollower import MoveConfig, QuickMoveDetector, Tick


def calm(symbol="AAA", n=200, base=100.0, sigma=0.0004, seed=3, start=0.0, step=5.0):
    rng = random.Random(seed)
    price, out = base, []
    for i in range(n):
        price *= math.exp(rng.gauss(0.0, sigma))
        out.append(Tick(symbol, price, start + i * step, volume=1000.0))
    return out


def run(detector, ticks):
    return [m for m in (detector.update(t) for t in ticks) if m is not None]


def test_calm_tape_produces_no_alerts():
    assert run(QuickMoveDetector(), calm()) == []


def test_shock_fires_a_move():
    d = QuickMoveDetector()
    ticks = calm()
    last = ticks[-1]
    ticks.append(Tick("AAA", last.price * 0.97, last.ts + 5.0, volume=20000.0))
    moves = run(d, ticks)
    assert len(moves) == 1
    assert moves[0].direction == "down"
    assert moves[0].ret < -0.02


def test_warmup_suppresses_early_fire():
    d = QuickMoveDetector(MoveConfig(warmup_ticks=100))
    ticks = calm(n=10)
    ticks.append(Tick("AAA", ticks[-1].price * 0.90, ticks[-1].ts + 5.0, volume=50000.0))
    assert run(d, ticks) == []


def test_cooldown_suppresses_repeat_alerts():
    d = QuickMoveDetector(MoveConfig(cooldown_s=600.0))
    ticks = calm()
    p, ts = ticks[-1].price, ticks[-1].ts
    for i in range(1, 5):
        ticks.append(Tick("AAA", p * (1 - 0.03 * i), ts + 5.0 * i, volume=20000.0))
    assert len(run(d, ticks)) == 1


def test_volatile_symbol_needs_a_bigger_move():
    """Same 1.5% move: an alert on a quiet symbol, noise on a jumpy one."""
    quiet = QuickMoveDetector(MoveConfig(hard_ret=0.10))
    jumpy = QuickMoveDetector(MoveConfig(hard_ret=0.10))

    def with_bump(ticks):
        out = list(ticks)
        out.append(Tick(out[0].symbol, out[-1].price * 1.015, out[-1].ts + 5.0,
                        volume=20000.0))
        return out

    assert run(quiet, with_bump(calm(sigma=0.0002)))
    assert not run(jumpy, with_bump(calm(sigma=0.006, seed=9)))


def test_volume_requirement_filters_thin_moves():
    d = QuickMoveDetector(MoveConfig(hard_ret=0.10, min_volume_ratio=3.0))
    ticks = calm()
    ticks.append(Tick("AAA", ticks[-1].price * 1.015, ticks[-1].ts + 5.0, volume=1.0))
    assert run(d, ticks) == []


def test_reversal_is_flagged():
    d = QuickMoveDetector(MoveConfig(cooldown_s=1.0))
    ticks = calm()
    p, ts = ticks[-1].price, ticks[-1].ts
    ticks.append(Tick("AAA", p * 0.96, ts + 5.0, volume=20000.0))
    ticks.append(Tick("AAA", p * 1.02, ts + 400.0, volume=20000.0))
    moves = run(d, ticks)
    assert moves[-1].reversal is True


def test_symbols_have_independent_baselines():
    d = QuickMoveDetector()
    run(d, calm("AAA", sigma=0.0002))
    run(d, calm("BBB", sigma=0.006, seed=5))
    sa, _ = d.baseline("AAA")
    sb, _ = d.baseline("BBB")
    assert sb > sa
