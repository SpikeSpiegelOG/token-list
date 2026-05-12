# Binance Listing Scanner

Self-hosted, local-first toolkit to:

1. **Scanner** — find wallet clusters that bought past Binance memecoin listings
   in the pre-announcement window (insider/leak detection).
2. **Candidate scorer** — given that insider wallet list, find what they're
   buying right now (forward-looking watchlist).
3. **Monitor** — long-running watchers (wallet activity, Binance announcement
   firehose, public Telegram alpha channels) that write into a local SQLite
   DB, surfaced on a localhost dashboard at `http://localhost:8000`.

No external bots, no Telegram outputs, no third-party SaaS. Everything lives
on your machine.

## Why

The "Binance Effect" averages a +41% pop on listing day, but insider clusters
front-run the announcement on-chain. Public research (Alex Mason, DuaCrypto,
WalletFinder.ai, Lookonchain) has shown that ~6–8 wallets repeatedly accumulate
tokens 0–72h before announcements. **Copy-trading those wallets is legal**
(the data is public), as long as you're not yourself receiving non-public info.

This stack reproduces that research locally so you don't depend on Twitter
threads being live or Nansen labels being current.

## Prereqs

- Python 3.11+
- Free API keys:
  - [Etherscan V2](https://etherscan.io/apis) — one key, all EVM chains
  - [Helius](https://helius.dev) — Solana RPC + enhanced txn API
  - [CoinGecko Demo](https://www.coingecko.com/en/api/pricing) — free tier
  - [Telegram API ID/Hash](https://my.telegram.org) — for the TG scraper
- Optional: [Dune Sim](https://sim.dune.com) for richer cross-chain queries

## Install

```bash
cd binance-listing-scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in ETHERSCAN_API_KEY, HELIUS_API_KEY, COINGECKO_API_KEY,
# and TG_API_ID/TG_API_HASH/TG_CHANNELS if you want TG scraping
```

## 1) Build the historical insider watchlist

```bash
python -m scanner.build_watchlist
# writes:
#   data/listings.json
#   data/buyers/<SYMBOL>.json
#   data/insider_wallets.json   <-- the PRIMARY cluster
#   data/scanner.db             <-- all tiers + funding edges
```

What it does:

| Step | File | Action |
|---|---|---|
| 1 | `scanner/binance_listings.py` | Pulls last `LOOKBACK_LISTINGS` Binance memecoin listings from the CMS API. Resolves token contracts via CoinGecko. |
| 2 | `scanner/prelisting_buyers.py` | For each listing, queries every wallet that received the token in the `PRE_LISTING_WINDOW_HOURS` before the announcement (Etherscan V2 for EVM, Helius for Solana). Filters out CEX hot wallets. |
| 3 | `scanner/cluster.py` | Cross-joins those buyer lists. Wallets appearing in `>= MIN_LISTINGS_FOR_INSIDER` listings are flagged as **PRIMARY** insider cluster, ranked by hit count and average lead time. |
| 4 | `monitor/load_insiders.py` | Pushes PRIMARY wallets to SQLite so the expansion steps can build on them. |
| 5 | `scanner/cluster_expansion.py` | **EXPANDED tier.** For each PRIMARY wallet, walks funding lineage: finds who funded the seed (parent), what wallets the seed funded (child), and wallets the same parent funded near-simultaneously (siblings). Confidence-scored, ≥0.7 written. Edges persisted to `funding_edges` table for graph visualization. |
| 6 | `scanner/binance_secondary.py` | **BINANCE_2NDARY tier.** Pulls last 30 days of outflows from every known Binance hot wallet. For each recipient, scores: wallet-age, time-to-first-DEX-swap, repeated-withdrawal count, first-swap-token (memecoin vs blue chip), historical pre-listing buyer overlap. Score ≥0.6 written. |

### Tier model

| Tier | What | Convergence weight |
|---|---|---|
| **PRIMARY** | Appears in ≥`MIN_LISTINGS_FOR_INSIDER` historical Binance memecoin pre-listing windows. | 1.0× |
| **FACILITATOR** | Receives recurring $50k+ stablecoin tranches from many distinct memecoin team wallets ("listing fixer" archetype). Built by scanning every listed token's team-wallet outflows backward and finding recipients that appear across multiple unrelated tokens. | 0.9× |
| **EXPANDED** | Linked to a PRIMARY via funding lineage (parent, child, or sibling co-funded within 1 hour). | 0.6× |
| **BINANCE_2NDARY** | Funded directly from a Binance hot wallet AND exhibits post-withdrawal sniper behavior (fresh wallet, <24h to first DEX swap, recurring Binance withdrawals, memecoin first trade). | 0.5× |

An ENTRY alert fires when the **weighted score** for a token in the
convergence window reaches **≥ 2.0** — i.e., 2 PRIMARYs, or 1 PRIMARY +
2 EXPANDEDs, or 4 BINANCE_2NDARYs, etc. This is much more sensitive than
plain "≥2 wallets" while still requiring real signal.

Tweak `LOOKBACK_LISTINGS`, `PRE_LISTING_WINDOW_HOURS`, `MIN_LISTINGS_FOR_INSIDER`
in `.env`.

## 2) Find what those insiders are buying right now

```bash
python -m candidates.score_tokens
# writes data/candidates.json
```

For every wallet in `insider_wallets.json`, queries the last 14 days of inflows
and aggregates by token. Tokens with **2+ insiders converging** are surfaced
as candidates. Output is sorted by insider count and median wallet strength.

See `candidates/current_candidates.md` for the full convergence/scoring
framework, validation gates, and sizing notes.

## 2b) Score candidates against the full Binance-listing playbook

Modeled on the public ACT1 listing story — a memecoin that allegedly cleared
four criteria to get on Binance: enough X activity, enough volume, enough
holders, and a backchannel payment.

```bash
python -m qualification.qualification_score
# writes data/qualified_candidates.json
```

For each candidate token from step 2, scores out of 100:

| Component | What it checks | Source |
|---|---|---|
| **Market (25 pts)** | 24h DEX volume ≥ $8M, liquidity ≥ $500k, holders ≥ 10k, txns ≥ 5k | DEXScreener / Solscan / Etherscan |
| **Social (25 pts)** | Galaxy Score ≥ 60, social volume ≥ 5k, followers ≥ 20k | LunarCrush (optional) + Nitter profile scrape |
| **Insider flow (25 pts)** | How many distinct insider wallets are converging, weighted by their hit-strength | `candidates/score_tokens.py` output |
| **Payment lineage (25 pts)** | Has the team paid a known FACILITATOR or BINANCE_2NDARY wallet $50k+ in stables in the last 90 days? | `qualification/payment_lineage.py` |

Score ≥70 = STRONG, 45–69 = MODERATE, <45 = WEAK.

**Important:** a HIGH PAYMENT_LINEAGE score on its own is not a buy signal —
it suggests insider/facilitator activity has begun, which is when PRIMARY
clusters typically start front-running. Use it as a confirmation layer on
top of an INSIDER_FLOW signal, not a standalone trigger.

### Single-token qualification CLI

For ad-hoc analysis of one address:

```bash
python -m qualification.qualify 2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump
python -m qualification.qualify 0x6982508145454ce325ddbe47a25d4ec3d2311933 --twitter pepecoineth
python -m qualification.qualify <addr> --chain binance-smart-chain --json
```

Chain auto-detected from address shape. Insider count auto-pulled from the
local DB if available. Prints a human-readable report with per-component
scores, OR `--json` for machine-readable output.

### Validating the pipeline

```bash
python -m validation.validate_pipeline           # offline / mock
python -m validation.validate_pipeline --live    # also hit no-auth APIs
```

Runs the cluster + facilitator logic against synthetic fixtures (5 fake
listings with 3 known-insider wallets and 1 known-facilitator wallet)
and checks for correct identification + correct noise rejection.
With `--live`, also validates DEXScreener and Binance CMS endpoints
still respond as expected — catches API-shape regressions early.

## Multi-chain support

| Chain | Listings + buyers | Insider expansion | Binance-secondary | Facilitator | Payment lineage |
|---|---|---|---|---|---|
| Ethereum         | ✅ | ✅ | ✅ | ✅ | ✅ |
| BSC              | ✅ | ✅ | ✅ | ✅ | ✅ |
| Base             | ✅ | ✅ | ✅ | ✅ | ✅ |
| Arbitrum         | ✅ | ✅ | ✅ | ✅ | ✅ |
| Polygon          | ✅ | ✅ | ❌ | ✅ | ✅ |
| Optimism         | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Solana**       | ✅ | partial | ✅ | ✅ | ✅ |

Solana paths use Helius RPC + enhanced txn API. EVM paths use Etherscan V2
multichain.

## Facilitator graph

The dashboard exposes an interactive node-link diagram for each known
FACILITATOR wallet, showing:

- Every memecoin team wallet that paid it (inbound, color-coded by listing)
- Every wallet it has forwarded funds to (outbound, including any Binance
  hot wallet deposits)

Index page lists all facilitators at `/facilitators`. Click a wallet to
open `/facilitator-graph/<addr>` rendered with vis.js (CDN, no build step).
JSON also available at `/api/facilitator-graph/<addr>` for scripting.

## 3) Run the local monitor + dashboard

```bash
./monitor/run_all.sh
# Then open http://localhost:8000
```

This starts:

- `monitor/announcement_watcher.py` — polls Binance announcement CMS every 3s
  (often catches the announcement page going live a few seconds before the
  official tweet). Writes to `binance_announcements`, emits `INFO` alert.
- `monitor/wallet_watcher.py` — polls each insider wallet every 60s for new
  txs. Two special detections:
  - **`URGENT_EXIT`**: wallet sends a token to a known Binance hot wallet →
    near-certain "dump incoming" signal.
  - **`ENTRY`**: 2+ insider wallets buy the same token within 6h →
    convergence signal, treat as candidate.
- `monitor/tg_scraper.py` — Telethon **user** client (no bot). Joins/listens
  to public alpha-leak channels listed in `TG_CHANNELS`, extracts contract
  addresses from messages, persists to `tg_messages`. Tags posts containing
  the words `binance|listing|spot|alpha|leaked|sniper|insider|vote to list`
  + addresses as `WATCH` alerts.
- `monitor/dashboard.py` — FastAPI page at `localhost:8000` showing live
  alerts, insider wallet table, recent announcements, TG firehose. Auto-
  refreshes every 10s. JSON APIs at `/api/alerts`, `/api/insider-wallets`,
  `/api/wallet/{addr}`.

## Workflow

1. **Once per week**: `python -m scanner.build_watchlist` to refresh the
   insider cluster (new listings keep happening, the cluster evolves).
2. **Once per day**: `python -m candidates.score_tokens` to refresh the
   forward-looking watchlist. Manually validate top candidates with the
   gates in `candidates/current_candidates.md` (mint authority off, LP
   locked, holder distribution, etc).
3. **Continuously**: leave `./monitor/run_all.sh` running. Check the
   dashboard a few times a day. Act on:
   - `ENTRY` cluster_buy alerts → candidate to consider sizing into
   - `URGENT_EXIT` binance_deposit alerts → if you're holding, exit now
   - `INFO` announcement alerts → the Binance tweet is seconds away
   - `WATCH` tg_leak alerts → cross-check the address against
     `score_tokens.py` output for confirmation

## Layout

```
binance-listing-scanner/
├── README.md
├── requirements.txt
├── .env.example
├── config.py
├── data/                          # outputs (gitignored)
├── scanner/
│   ├── binance_listings.py        # 1) Fetch listings + resolve contracts
│   ├── prelisting_buyers.py       # 2) Find pre-announcement buyers
│   ├── cluster.py                 # 3) PRIMARY cluster (cross-listing wallets)
│   ├── cluster_expansion.py       # 5) EXPANDED tier (funding-lineage graph)
│   ├── binance_secondary.py       # 6) BINANCE_2NDARY tier (hot-wallet outflows)
│   └── build_watchlist.py         # entry point: runs 1→2→3→4→5→6
├── candidates/
│   ├── score_tokens.py            # what insiders are buying NOW
│   └── current_candidates.md      # framework + seed wallets + categories
├── qualification/
│   ├── market_metrics.py          # 24h vol / liquidity / holders / txns
│   ├── social_score.py            # LunarCrush + Nitter profile scrape
│   ├── facilitator_finder.py      # discovers FACILITATOR wallets
│   ├── payment_lineage.py         # checks team→facilitator payments
│   └── qualification_score.py     # aggregates all 4 into 0–100 score
└── monitor/
    ├── db.py                      # SQLite schema
    ├── load_insiders.py           # JSON → DB
    ├── wallet_watcher.py          # insider wallet polling + alerts
    ├── announcement_watcher.py    # Binance CMS polling
    ├── tg_scraper.py              # Telethon → SQLite (no bot)
    ├── dashboard.py               # FastAPI dashboard
    └── run_all.sh                 # boot the whole stack
```

## Caveats — read these

- **Copy-trading insiders is statistically edge-positive but fat-tailed.**
  Most candidates do NOT list within 30 days. Size as if each bet is binary.
- **Insiders bait copy-traders.** They know they're being watched. The
  `URGENT_EXIT` signal can be a head-fake; cross-check with cluster behavior.
- **Binance is actively suspending insiders.** The window for this kind of
  edge is narrowing as Binance tightens internal controls.
- **Receiving leaks privately is illegal.** This tool only consumes public
  on-chain and public Telegram channel data. Don't pay for "private" alpha.
- **Survivorship bias is huge.** The famous insider clusters are famous
  because they won. The losers are invisible.
- **Rate limits exist.** Etherscan free tier = 5 req/s; Helius free =
  100k req/mo. Increase poll intervals if you hit them.

## Extending

- **More CEX hot wallet labels**: edit `BINANCE_HOTS` in
  `monitor/wallet_watcher.py`. Add Coinbase, Kraken, Bybit, OKX too — exits
  to other CEXs are less informative but still relevant.
- **Mempool-level detection**: subscribe to a private mempool (Blocknative,
  Bloxroute) to catch sniper bots in the same block as the announcement.
- **Price-aware PnL**: extend `cluster.py` to compute realized PnL per wallet
  using DEX price at buy time vs. listing-day open. Highest-PnL wallets are
  the highest-conviction insiders.
- **Webhook ingestion**: replace the polling watcher with Alchemy webhooks
  or Helius webhooks for sub-second latency.
