# perps-research

A research and paper-trading framework for perpetual-futures markets.

> **Reality check.** This repository is for **finding and falsifying trading
> hypotheses**, not for printing money. Every backtest result must survive
> walk-forward out-of-sample testing, realistic fee + slippage, regime-shift
> stress, and at least one month of live paper-trading before any real
> capital. No automated tooling makes "perps trading" reliably profitable —
> this codebase is just instrumentation that lets you investigate honestly.

> **Repo location note.** This project currently lives as a sub-tree inside
> `spikespiegelog/token-list` on branch `claude/perps-trading-research-Wgf44`.
> When you want it as its own repo, run:
>
> ```sh
> git subtree split --prefix=perps-research -b perps-research-only
> # then push that branch to a fresh remote
> ```

## What's here

```
apps/
  ingest/          Long-running WS workers → DuckDB
  web/             Next.js 15 dashboard (TradingView Lightweight Charts)
packages/
  core/            Shared types: Tick, Bar, Funding, Order, Fill, Signal
  venues/
    hyperliquid/   wss://api.hyperliquid.xyz/ws adapter
    binance/       wss://fstream.binance.com adapter (geo-restricted)
  storage/         DuckDB schema + tick→bar rollup
  indicators/      EMA (more in Phase 5)
  backtest/        Event-driven engine, slippage model, metrics
  strategies/      Starter hypotheses + registry
  macro/           Calendar + news ingest + event-impact correlation
  paper/           Live paper trader (same fill/slippage as backtest)
infra/             fly.toml + Dockerfile (Phase 2.5)
```

## Phase 1 — vertical slice (shipped)

Live Hyperliquid trades → DuckDB → Next.js candlestick chart with EMA(20)
overlay, plus an SSE stream that pushes each new tick.

## Phase 2 — multi-venue + funding/OI/liquidations (shipped)

- **Hyperliquid** also subscribes to `activeAssetCtx` per coin → emits
  `Funding` (hourly rate) and `OpenInterest`.
- **Binance USDⓈ-M Futures** adapter: `aggTrade`, `markPrice@1s` (funding),
  `forceOrder` (liquidations); REST poller for OI every 60s.
- New tables: `funding`, `open_interest`, `liquidations`. Funding/OI are
  throttled at the bus subscriber so we only persist on rate change OR
  every 60s.
- **/funding** — cross-venue heatmap with naive-APR for each rate, plus OI
  side-by-side. Color saturated at |rate| = 5bp/period.
- **/liquidations** — live Binance forceOrder tape with rolling 60s
  long/short notional summary.

> **Geo-restriction note.** Binance Futures REST + WS reject from US-based
> IPs (HTTP 451 + silent WS no-data). The code path is correct but
> verifying Binance live data requires running ingest from a non-US region
> — fly.io with `primary_region = "nrt"` (Tokyo) or `"fra"` (Frankfurt)
> works. Hyperliquid has no such restriction. Configure venue selection
> via `INGEST_VENUES=hyperliquid,binance` (or just `hyperliquid` for US
> dev).

### Run it locally

```sh
pnpm install
pnpm build                         # builds the workspace TS packages
cp .env.example .env.local        # defaults are fine
pnpm dev                           # starts Next.js; ingest is embedded
# open http://localhost:3000/chart/BTC
```

The web app uses Next.js's `instrumentation.ts` hook to boot the Hyperliquid
WS adapter inside the same Node process. Trades are normalized into the
shared `Tick` shape, written to DuckDB, and republished on an in-memory
`TickBus` that the SSE route fans out to connected charts.

DuckDB takes an exclusive file lock, which is why ingest+web are colocated
in one process for single-machine dev. For Phase 2 multi-machine deploys
on fly.io, swap DuckDB for Postgres/TimescaleDB and run `apps/ingest` as a
standalone worker — the standalone entrypoint is preserved at
`apps/ingest/src/main.ts`.

### Acceptance checks

1. `pnpm install && pnpm build && pnpm test` all green.
2. `pnpm dev` boots both processes; logs show "[hyperliquid] subscribed
   trades:BTC".
3. `data/perps.duckdb` is created and `SELECT count(*) FROM ticks` grows.
4. `http://localhost:3000/chart/BTC` shows candles updating in real time
   with an EMA(20) overlay.
5. Killing/restarting `apps/ingest` reconnects within ~5s; chart history
   persists across reloads.

## Phase 3 — backtest engine + starter strategies (shipped)

- `@perps/backtest` event-driven engine: replays bars through a `Strategy`,
  routes orders through a half-spread + taker-fee slippage model, marks
  equity bar-by-bar, force-closes any open position at end-of-run.
- Metrics: total return, Sharpe, Sortino, max drawdown, win rate,
  expectancy, exposure, trade count. Annualisation defaults to 1m bars.
- `@perps/strategies` registry with three hypotheses, each parameterised:
  - **momentum-breakout** — N-bar high/low breakout with ATR vol gate and
    trailing ATR stop.
  - **liq-sweep-fade** — fade outsized one-bar moves (range proxy for a
    liq cascade); upgrades to a real `liquidations`-table trigger in
    Phase 4.
  - **funding-arb** — proxy version using price-vs-EMA stretch; replaced
    by a basis-vs-funding pair trade once the engine accepts a Funding
    stream.
- `/backtest` UI page: pick strategy + symbol + lookback window + tweak
  params, render equity curve via Lightweight Charts AreaSeries, see
  metrics + last-20 trade list.

> **What "Sharpe 11" means in a 200-bar run.** Nothing. Single backtest
> runs are noise. Real evaluation needs walk-forward out-of-sample,
> regime stratification (trending vs chop vs liquidation cascade), and
> monte-carlo over reasonable parameter neighbourhoods. The shipped page
> is plumbing; the rigour comes in Phase 5.

## Phase 4 — macro/news + event-impact correlation (shipped)

- **`@perps/macro`** package:
  - **ForexFactory weekly XML** parser (no auth) — fetched every 6h.
    Extracts title / country / time / impact / forecast / previous;
    converts ET timestamps to UTC ms; assigns stable IDs from
    sha256(title|country|ts).
  - **CryptoPanic** client — gated by `CRYPTOPANIC_TOKEN`; refreshes every
    5m when set, no-op when unset.
  - **`computeEventImpact`** — for events whose title matches a
    substring filter, computes mean / median / std of % returns at a
    grid of offsets {-15m, -5m, -1m, 0, +1m, +5m, +15m, +60m, +4h, +6h}
    against the locally stored 1m bars.
- New tables: `macro_events` (idempotent upsert by id, so re-fetching the
  same week is safe), `news_items`.
- New endpoints: `/api/macro/events`, `/api/macro/news`,
  `/api/macro/impact`.
- **/macro** UI: upcoming calendar (high+medium impact, next 7 days),
  recent past events, news feed, and an interactive event-impact panel
  for CPI / PPI / NFP / FOMC / GDP / PCE / Unemployment Rate.

> **Why this matters for trading.** Crypto reacts to US macro releases
> (CPI, FOMC, NFP) often more aggressively than equities; the
> event-impact panel is the cheapest way to discover or refute "X always
> dumps on hot CPI" without reading talking heads. Sample sizes are
> small to start — the panel is most useful after several weeks of
> accumulated bar history covering a few release cycles.

> **Caveats baked into the page.** Unstratified single-window stats
> conflate regimes (rate-cut vs hike, hot vs cold print). A 3-event mean
> tells you about three days, not about CPI in general. Treat the
> numbers as a starting point for hypothesis design, not as a signal.

## Phase 5 — paper trader (shipped)

- **`@perps/paper`**: a `PaperEngine` that subscribes to closed 1m bars
  from the rollup and runs a strategy through the same `StrategyContext`
  shape the backtester uses. A strategy validated in `/backtest` runs
  unchanged in `/paper`.
- Same slippage / fee model as the backtester (half-spread + flat taker
  fee), so paper PnL is directly comparable to backtest PnL.
- Persistent across restarts: state (cash, position, avg entry) is
  reconstructed from `paper_equity` on startup, so the run accumulates
  history across server cycles. Run keyed by `runId` (env
  `PERPS_PAPER_RUN_ID`, default `"default"`).
- New tables: `paper_runs`, `paper_equity` (PK on (run_id, ts)),
  `paper_fills`. Equity curve query and fills tape both run from these.
- New endpoints: `/api/paper/status`, `/api/paper/equity`,
  `/api/paper/fills`.
- **/paper** UI: status grid (equity / position / bars / fills),
  live-updating equity curve, last-20 fills.

### Enabling the paper trader

```sh
PERPS_PAPER_STRATEGY=momentum-breakout \
PERPS_PAPER_SYMBOL=BTC \
PERPS_PAPER_PARAMS='{"lookback":20,"minVolPct":0.0005}' \
PERPS_PAPER_INITIAL_CASH=10000 \
PERPS_PAPER_SIZE=0.05 \
pnpm start
```

Without `PERPS_PAPER_STRATEGY` the page renders an instructions stub —
no engine is created, no rows are written.

> **Why paper before real.** A backtest result that survives one month
> of live paper-trading on out-of-sample bars (different from those used
> to tune parameters) is roughly the *minimum* evidence to consider real
> capital. The default fees + half-spread make this conservative on
> purpose — assume worse, not better, in real markets.

## Optional next phases

- **2.5** — fly.io `Dockerfile` + `fly.web.toml`, region-pinned ingest,
  Coinbase Perps adapter (US-friendly).
- **6** — Walk-forward backtest harness, parameter monte-carlo,
  regime-stratified macro impact stats.

## Hard limits

- No real-money order routing. Ever, without an explicit, separate review.
- No keys for funded accounts in this codebase.
- No paid-feed scraping (Bloomberg, Refinitiv, paid TradingView plans).
