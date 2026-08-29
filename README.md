# NewsFollower

Keeps only the news and price action worth reacting to. Two independent
filters, joined by a correlation window:

1. **Criticality filter** — scores headlines and drops previews, opinion,
   analyst chatter, recaps and syndicated duplicates.
2. **Quick-move detector** — flags price action that is fast *and* unusual for
   that specific symbol, rather than large in absolute terms.

Pure stdlib, no dependencies. `pytest` only for the tests.

## Quick start

```bash
python -m newsfollower.cli   # replay demo on real headlines from Aug 2026
```

```python
from newsfollower import NewsFollower, NewsItem, Tick, PipelineConfig, NewsConfig

follower = NewsFollower(PipelineConfig(
    news=NewsConfig(watchlist=frozenset({"NVDA", "TSN"}))
))

alert = follower.on_news(NewsItem(
    id="1",
    headline="Fed announces emergency rate cut of 50 basis points",
    source="reuters",
    symbols=("SPY",),
))
if alert:
    print(alert.describe())

for tick in feed:                      # your market data
    alert = follower.on_tick(Tick("NVDA", tick.price, tick.ts, tick.size))
    if alert:
        print(alert.describe())
```

## The four alert kinds

| Kind | Meaning | Priority |
|---|---|---|
| `news_critical` | Headline cleared the bar on its own | IMPORTANT / CRITICAL |
| `fast_move` | Price moved fast and unusually | IMPORTANT |
| `confirmed` | Both fired on the same symbol within `correlate_s` | CRITICAL |
| `unexplained_move` | Tape moved, no headline explains it | IMPORTANT / CRITICAL |

`unexplained_move` is usually the most valuable of the four: the price is
moving and the story has not printed yet.

## How headlines are scored

```
score = (category_weight + surprise_bonus + magnitude_bonus - noise_penalty)
        x source_weight
        x staleness_decay
        + watchlist_bonus
```

- **Category weight** (0–50) — systemic/credit and central bank rank highest,
  single-company events lowest. Phrases live in `config.CATEGORY_RULES` and
  match on word boundaries, so `cpi` does not fire inside `recipient`.
- **Source weight** (0.25–1.0) — wires and primary sources (Reuters,
  Bloomberg, federalreserve.gov, company IR) at 1.0; aggregators ~0.6;
  commentary ~0.25. A perfect headline off a blog should not outrank a
  mediocre one off the wire.
- **Magnitude** — percentages and basis points in the text. Percentages at or
  above 40 are read as *levels* ("gross margin of 72%"), not moves, and score
  nothing; otherwise a routine headline looks enormous.
- **Noise penalty** — `what to expect`, `history shows`, `3 reasons`,
  `could`, `analysts say`, `week ahead`, `reportedly`. These are the classic
  false positives.
- **Staleness** — score decays linearly over `max_age_s` (default 30 min) and
  is dropped past it. A 25-minute-old "breaking" headline is not a trade.
- **Dedup** — headline shingles compared by Jaccard *and* containment, so the
  same story with an extra clause appended is still caught as a repeat.

Tune everything in `newsfollower/config.py`. Every alert carries a `reason`
string explaining which rules fired, and `follower.dropped` records what was
filtered out and why — so a missed story is diagnosable rather than mysterious.

## How quick moves are detected

A move fires when it is **both** statistically unusual for that symbol and
past a hard floor:

```
z = |log(p_now / p_window_start)| / (sigma_per_second x sqrt(window))
fire if |ret| >= hard_ret                            (2% — always)
     or (z >= min_z and |ret| >= min_abs_ret and volume_ratio >= min_volume_ratio)
```

The baseline `sigma` is a per-symbol EWMA of per-second variance, so the same
thresholds work for a sleepy bond ETF and a 6%-a-day small cap.

Three details that make it usable in practice:

- **The baseline is snapshotted before the current tick is folded in.**
  Otherwise the shock is absorbed into the volatility estimate and the second
  leg of the same move no longer looks unusual — the detector goes deaf
  exactly when it matters.
- **Baseline updates are winsorised** at 4x the current expected move, so one
  shock cannot permanently reset the symbol's notion of "normal".
- **The cooldown is at least the window length.** A 300s window still
  straddles the shock two minutes later and would otherwise re-report the same
  move as a fresh one.

Moves carry `reversal=True` when they flip the prior direction — the Nvidia
pattern of selling the margin line and then buying the revenue guide.

## Layout

```
newsfollower/
  models.py        NewsItem, Tick, Move, Alert, Priority
  config.py        all rules and thresholds
  criticality.py   headline scoring
  price_action.py  streaming quick-move detector
  dedup.py         shingle + containment de-duplication
  pipeline.py      NewsFollower: joins the two filters
  cli.py           replay demo
briefs/            dated market briefs
tests/
```

## Wiring up a real feed

`NewsFollower` takes plain objects, so any source works — adapt to `NewsItem`
and `Tick` and call `on_news` / `on_tick`. Two things to get right:

- **`item.ts` must be the publication time**, not ingest time, or the
  staleness decay is meaningless.
- **`Tick.volume` is per-tick**, not cumulative.

## Tests

```bash
pip install pytest && python -m pytest tests -q
```

Covers the scoring rules, the false positives that motivated them, dedup
behaviour, and the price-action edge cases (warmup, cooldown, per-symbol
baselines, volatile-symbol suppression, reversal flagging).

## Current tuning

The demo replays five genuine market-moving headlines from the week ending
2026-08-28 alongside five preview/opinion/duplicate items from the same feeds.
It keeps 5 of 10 — the five real ones — and reports why it dropped each of the
others. See [`briefs/2026-08-29-breaking-news.md`](briefs/2026-08-29-breaking-news.md)
for the stories themselves.
