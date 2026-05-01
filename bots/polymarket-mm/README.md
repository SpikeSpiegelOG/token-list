# Polymarket CLOB v2 Market-Maker Bot

Quote both sides of a binary market on Polymarket's CLOB v2. Earn maker rebates from the [Liquidity Rewards Program](https://help.polymarket.com/en/articles/13364466-liquidity-rewards) (~20–25% of collected fees redistributed to LPs) plus the bid-ask spread.

## Files

- `quote.py` — read-only: fetch top-of-book on a market, show what your quotes *would* be. Works without keys.
- `mm.py` — execution skeleton. **Defaults to `--dry-run`.** Requires `py-clob-client`, a Polygon-based EOA private key, and USDC.

## Quick start

```bash
pip install -r requirements.txt
# 1. List rewarded markets
python quote.py list-rewarded
# 2. Inspect a specific market's book and quote plan
python quote.py inspect --condition-id 0xABC...
# 3. Dry-run market maker
python mm.py --condition-id 0xABC... --notional 200 --spread-bps 200
```

## Strategy

Quote `mid ± spread/2` on both YES and NO, sized to the [rewards minimum]
(typically $100–$500 per side depending on market). Re-quote every N seconds
or whenever mid moves > tolerance. Inventory-skew when one side fills more.

## How it makes money

1. **Maker rebates** — a slice of the venue's fee revenue, paid weekly in USDC.
2. **Spread capture** — if takers hit both sides evenly, you earn the spread.

## How it blows up

- **Adverse selection** — informed traders pick off your quotes right before news. Tighten spread only on liquid, news-quiet markets (BTC hourly, sports during live games are *bad*; long-dated political contracts during quiet weeks are *good*).
- **Inventory risk** — one-sided flow leaves you long YES on a market that resolves NO. Cap per-market inventory, hedge across correlated markets, or pull quotes when imbalanced.
- **Smart-contract / settlement risk** — Polygon downtime, USDC depeg, Polymarket admin actions.

## References

- [Polymarket docs (CLOB)](https://docs.polymarket.com/api-reference/introduction)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Liquidity Rewards explainer](https://help.polymarket.com/en/articles/13364466-liquidity-rewards)
