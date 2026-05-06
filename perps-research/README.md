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
  storage/         DuckDB schema + tick→bar rollup
  indicators/      EMA, RSI, ATR, ... (Phase 1: EMA only)
infra/             fly.toml + Dockerfile (Phase 2)
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

## Phases 3–5 (gated on review)

- **3** — Event-driven backtest engine + three baseline strategies
  (momentum-breakout, funding-arb, liq-sweep-fade), `/backtest` page.
- **4** — Macro/news ingestion (FRED, BLS, CryptoPanic, econ calendar) and
  event-impact correlation page.
- **5** — Paper trader with live equity curve.
- **2.5 (optional)** — fly.io `Dockerfile` + `fly.web.toml`, region-pinned
  ingest, Coinbase Perps adapter (US-friendly).

## Hard limits

- No real-money order routing. Ever, without an explicit, separate review.
- No keys for funded accounts in this codebase.
- No paid-feed scraping (Bloomberg, Refinitiv, paid TradingView plans).
