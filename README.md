# NewsFollower

A free market squawk. Polls 22 key-less public feeds, keeps only the headlines
and price moves worth reacting to, formats them as wire-style tape lines, and
optionally reads them aloud.

```
*(US) FED'S WARSH: CENTRAL BANK STILL HAS WORK TO DO ON INFLATION
*(US) CPI M/M 0.4% VS. EXP. 0.2% (PREV. 0.3%)
-(OPEC) CL: OPEC+ ANNOUNCES SURPRISE PRODUCTION CUT OF 1 MLN BPD
*NVDA ▼ 3.10% IN 60S (8.4 SIGMA) - NO HEADLINE
```

Three layers:

1. **Criticality filter** — scores headlines, drops previews, opinion, analyst
   chatter, agency boilerplate and syndicated duplicates.
2. **Quick-move detector** — flags price action that is fast *and* unusual for
   that specific symbol, rather than large in absolute terms.
3. **Squawk layer** — free feeds in, wire-formatted spoken tape out.

Pure stdlib, no dependencies, no API keys. `pytest` only for the tests.

## Quick start

```bash
# See how the filter treats the news cycle as it stands right now
python -m newsfollower.squawk.runner --replay

# Run it live (Ctrl-C to stop); --speak reads alerts aloud
python -m newsfollower.squawk.runner --speak

# Verify every registered source still works
python -m newsfollower.squawk.runner --check

# Offline demo of the filters on known headlines
python -m newsfollower.cli
```

Two feeds — BLS and SEC EDGAR — require a contact address in the User-Agent as
their stated fair-use condition, and 403 without one:

```bash
export NEWSFOLLOWER_CONTACT="you@example.com"
```

The other 20 work anonymously.

## The squawk

```bash
python -m newsfollower.squawk.runner \
    --speak \
    --watchlist NVDA,TSN \
    --symbols '^GSPC,^VIX,CL=F,ZW=F' \
    --min-priority IMPORTANT \
    --log ~/squawk.jsonl
```

| Flag | Effect |
|---|---|
| `--replay` | Run current feed contents through the filter and exit — the tuning tool |
| `--check` | Verify every source parses; exit code is the failure count |
| `--speak` | Read alerts aloud via the host's TTS |
| `--primary-only` | Central banks, statistical agencies and exchanges only |
| `--watchlist` | Tickers to escalate |
| `--min-priority` | `NORMAL` to see near-misses, `CRITICAL` for headlines only |
| `--log` | Append every emitted line as JSONL |
| `--prime` | Seconds spent absorbing feed backlog before going live |

**Startup primes every feed.** The first poll of an RSS feed returns twenty
historical items; reading yesterday's news aloud as if it were breaking is the
fastest way to make a squawk untrustworthy. Priming marks them seen without
emitting, and the historical price bars collected during priming warm the
detector's per-symbol volatility baselines.

### Formatting

A squawk line is not a headline. It is stripped to the claim, attributed,
region-tagged and short enough to read aloud in about three seconds:

| In | Out |
|---|---|
| `Fed Chair Warsh says central bank still has work to do on inflation` | `*(US) FED'S WARSH: CENTRAL BANK STILL HAS WORK TO DO ON INFLATION` |
| `Kansas City Fed's Schmid says inflation 'stubborn' and 'sticky'` | `-(US) FED'S SCHMID: INFLATION 'STUBBORN' AND 'STICKY'` |
| `BREAKING: OPEC+ announces surprise production cut of 1 million barrels per day - Reuters` | `*(OPEC) OPEC+ ANNOUNCES SURPRISE PRODUCTION CUT OF 1 MLN BPD` |
| `Nvidia guides Q3 revenue to $108 billion` | `-NVDA: NVIDIA GUIDES Q3 REVENUE TO USD 108BLN` |

`*` marks a line to act on now, `-` everything else. Region comes from the
speaking institution, else the earliest country reference in the text — so
"Ukrainian strikes on Russian ports" is a `(UA)` story, not `(RU)`.

For text-to-speech the abbreviations are expanded back out: a voice saying
"B-P-S" is worse than one saying "basis points".

### Economic releases

A data print is the one headline whose importance is fully computable, so it
gets its own path — actual, consensus, prior, and the miss expressed in units
of that indicator's own typical surprise:

```
*(US) CPI M/M 0.4% VS. EXP. 0.2% (PREV. 0.3%)      2.0 sigma -> CRITICAL
-(US) NONFARM PAYROLLS 142K VS. EXP. 165K          0.4 sigma -> NORMAL
 (US) JOBLESS CLAIMS 221K VS. EXP. 225K            0.3 sigma -> LOW
```

Calibration lives in `squawk/calendar.INDICATORS` as
`(typical surprise, market weight)`. A 0.2pp CPI miss and a 60k payrolls miss
both come out around 1 sigma; weight is how much the tape cares at all, so an
unrecognised series has to miss by a lot before it interrupts anything.

## Sources

22 verified free feeds, no keys. `--check` re-verifies them all.

| Tier | Sources |
|---|---|
| **Primary** | Fed (press, speeches), ECB, Bank of England (news, publications), BLS, Census, SEC EDGAR 8-K, Nasdaq trade halts, EIA |
| **Wires / majors** | CNBC (top, economy, finance, earnings), MarketWatch (real-time, top), FT |
| **Aggregators** | Yahoo Finance, Investing.com, BBC, Guardian, NYT |
| **Prices** | Yahoo 1-minute bars (equities, indices, futures, FX), Coinbase (crypto) |

Two known-dead sources stay in the registry so the gap is visible rather than
forgotten: **Reuters** retired its public RSS with no free replacement, and
**USDA** (WASDE) 403s any non-browser User-Agent.

Yahoo bars lag and get revised, so treat a quick-move alert sourced from them
as "go look", not "go trade". The last bar of a live session is always withheld
because it is still forming.

Polling is conditional: every request carries `ETag`/`If-Modified-Since`, so an
unchanged feed costs a 304 and no body. In a 150-second live run, 82 of 168
polls were 304s. Failures back off exponentially with jitter and respect
`Retry-After`.

## Library use

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
- **Admin penalty and boilerplate drop** — central banks publish far more
  administrative output than monetary news, on the same feed with the same
  authority. Merger approvals, enforcement actions, task forces and advisory
  councils are penalised heavily; schedules, advisories, "key takeaways" and
  "in charts" are dropped outright. Without this, six of the first eleven
  lines on a live tape were Fed bank-merger approvals.
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
  models.py          NewsItem, Tick, Move, Alert, Priority
  config.py          all rules and thresholds
  criticality.py     headline scoring
  price_action.py    streaming quick-move detector
  dedup.py           shingle + containment de-duplication
  pipeline.py        NewsFollower: joins the two filters
  cli.py             offline demo
  feeds/
    http.py          conditional-GET client with backoff
    rss.py           RSS 2.0 / Atom parsing
    sources.py       the 22-source registry
    prices.py        Yahoo bars, Coinbase ticker
  squawk/
    format.py        headline -> wire-style squawk line
    calendar.py      economic releases, actual vs expected
    audio.py         text-to-speech with priority preemption
    tape.py          terminal tape + JSONL session log
    runner.py        the service, --check and --replay
briefs/              dated market briefs
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

73 tests covering the scoring rules and the false positives that motivated
them, dedup behaviour, price-action edge cases (warmup, cooldown, per-symbol
baselines, volatile-symbol suppression, reversal flagging), squawk formatting
and attribution, release calibration, and feed parsing.

The feed tests are offline — RSS/Atom fixtures and a fake HTTP client — so the
suite does not depend on the internet. Use `--check` to test the real sources.

## Current tuning

The offline demo replays five genuine market-moving headlines from the week
ending 2026-08-28 alongside five preview/opinion/duplicate items from the same
feeds. It keeps the five real ones and reports why it dropped the rest. See
[`briefs/2026-08-29-breaking-news.md`](briefs/2026-08-29-breaking-news.md) for
the stories themselves.

Against the live feeds, `--replay` over 589 items currently emits 9 lines at
`NORMAL` and 5 at `IMPORTANT`. Run it yourself before trusting the thresholds:
the phrase lists are curated and inspectable, which makes coverage gaps real.
Every drop is logged in `follower.dropped` with the reason, so a missed story
is diagnosable rather than mysterious.

## Honest limitations

- **No true wire.** Reuters, Bloomberg and Dow Jones newswires are the actual
  source of a professional squawk's speed edge, and none is free. Everything
  here is seconds-to-minutes behind a real terminal.
- **Polling, not streaming.** Feeds are polled on a 10-60s floor. A commercial
  squawk pushes.
- **Keyword rules.** Categories are curated phrase lists. Deliberately
  inspectable and cheap, but they miss phrasings nobody anticipated — the
  Black Sea headline initially scored zero because the list had "shipments
  halted" and the headline said "halt shipments".
- **Yahoo bars are not a market data feed.** They lag, they get revised, and
  they cover only what Yahoo covers.
