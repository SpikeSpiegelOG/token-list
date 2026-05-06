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
#   data/insider_wallets.json   <-- the cluster
```

What it does:

| Step | File | Action |
|---|---|---|
| 1 | `scanner/binance_listings.py` | Pulls last `LOOKBACK_LISTINGS` Binance memecoin listings from the CMS API. Resolves token contracts via CoinGecko. |
| 2 | `scanner/prelisting_buyers.py` | For each listing, queries every wallet that received the token in the `PRE_LISTING_WINDOW_HOURS` before the announcement (Etherscan V2 for EVM, Helius for Solana). Filters out CEX hot wallets. |
| 3 | `scanner/cluster.py` | Cross-joins those buyer lists. Wallets appearing in `>= MIN_LISTINGS_FOR_INSIDER` listings are flagged as insider cluster, ranked by hit count and average lead time. |

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
│   ├── cluster.py                 # 3) Cluster wallets across listings
│   └── build_watchlist.py         # entry point: runs 1→2→3
├── candidates/
│   ├── score_tokens.py            # what insiders are buying NOW
│   └── current_candidates.md      # framework + seed wallets + categories
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
