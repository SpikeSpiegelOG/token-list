# Current Candidate List — Framework, Seed Wallets, Live Targets

This doc replaces a stale "buy these tokens" list with a reproducible framework
that stays accurate. The actual current candidates come from running
`python -m candidates.score_tokens` against your locally-built insider list.

## 1. Why no static buy list

Specific token candidates rot in days. The PNUT/ACT cluster Mason flagged in
Nov 2024 had moved on within 2 weeks. Anything published more than ~7 days
ago is noise. The pipeline below regenerates a fresh candidate list daily.

## 2. The convergence model

A token is a strong listing candidate if:

| Signal                                  | Weight |
|-----------------------------------------|--------|
| ≥3 distinct insider wallets bought it   | high   |
| Buys within last 7 days                 | high   |
| Insider wallets have ≥4 prior hits      | high   |
| Token has launched on Binance Alpha     | medium |
| Token is on BNB Chain or Solana         | medium |
| MM (Wintermute/GSR/DWF) wallet engaged  | medium |
| Listed on Bybit/OKX/Upbit recently      | medium |
| Vote-to-List campaign active            | medium |
| Holder count growing >20% week/week     | low    |
| DEX volume sustained > $5M/day          | low    |

`score_tokens.py` covers signals 1–3 automatically. Signals 4–9 are
manual gates you apply on top.

## 3. Seed insider wallets to bootstrap

Before you have 20 listings of historical data, seed `data/insider_wallets.json`
with these documented public-research wallets so `score_tokens.py` has
something to query immediately. (Updated as of the published research; verify
before trusting.)

```json
[
  {
    "wallet": "0x000000d40b595b94918a28b27d1e2c66f43a51d3",
    "source": "Alex Mason / DuaCrypto - PNUT/ACT cluster",
    "hit_count": 5,
    "chains": ["solana"],
    "notes": "Bought PNUT, ACT, CHILLGUY, LUCE, FATHA pre-listing"
  },
  {
    "wallet": "9hQ...truncated",
    "source": "WalletFinder.ai - Solana memecoin insider cluster",
    "hit_count": 4,
    "chains": ["solana"]
  }
]
```

> The full wallet addresses change as researchers publish. Pull current ones from:
> - Alex Mason's X threads ([@AlexMasonCrypto](https://x.com/AlexMasonCrypto))
> - DuaCrypto Medium posts
> - Lookonchain X feed
> - Nansen "Smart Money - Memecoin" label
> - WalletFinder.ai public clusters

## 4. Categories currently being accumulated (May 2026 snapshot)

Per public on-chain research, insider clusters as of recent weeks have been
accumulating tokens in these buckets. Use as starting filter; verify the
specific token via your own scanner.

- **BNB Chain memes** — Binance has explicitly favored BSC memes via
  Vote-to-List and Alpha. CZ/Yi He sentiment posts move BSC tickers.
- **Solana memes with Pump.fun → Raydium → Jupiter graduation** — the
  classic Alpha → Spot path (see PNUT, MOODENG, FARTCOIN precedent).
- **Binance-internal memes** — tokens that reference Binance itself
  (Binance Life, BUILD ON BNB / BOB, "CZ's Dog", etc.). Internal team
  attention historically converts to listings.
- **AI-narrative memes** — ACT-style tokens. Crowded but Binance keeps
  listing them.
- **Trending Kaito-mindshare tokens** — top-ranked tokens on Kaito Yaps /
  LunarCrush 7-day mindshare have a meaningful listing-correlation.

## 5. Validation gates BEFORE entry

Even with a high-convergence signal, gate every candidate against:

- [ ] Contract is verified, no mint authority / freeze authority enabled
- [ ] Top 10 holders < 30% of supply (excluding LP, burn, deployer)
- [ ] LP locked or burned
- [ ] No live `transfer()` blacklist or fee-on-transfer trap
- [ ] Liquidity > $200k on the deepest pool
- [ ] Not a known rug-pulled / re-deployed contract
- [ ] Insider wallets are NOT also holding short positions on perps
      (sometimes insider clusters bait spot then dump on perps)

## 6. Sizing

The expected payoff distribution is fat-tailed and mostly losing. Public
research suggests:
- ~20% of candidates list within 30 days of insider convergence
- Of those that list, ~80% pump on day-of (avg +41% in 2024 data)
- Of those that don't list within 30 days, ~70% bleed -50% or more

Therefore size each entry as if the bet is binary and the Kelly fraction is
small. Do not allocate >2–5% of the rotation portfolio per name.

## 7. The exit signal you most want to catch

The single highest-value piece of information from this pipeline is:
**when an insider wallet you're following sends to a Binance hot wallet.**

That is a near-certain "they got the announcement, dump is imminent" signal.
The `monitor/wallet_watcher.py` detects this specifically and writes an
`URGENT_EXIT` row to the local DB.
