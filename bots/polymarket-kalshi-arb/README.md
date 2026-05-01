# Polymarket ↔ Kalshi Cross-Arb Bot

Scan for mispriced overlapping markets between Polymarket and Kalshi (BTC hourly, sports, weather). When YES on Polymarket + NO on Kalshi cost less than $1 (or vice versa), there's a guaranteed payout.

## Files

- `scan.py` — read-only scanner. Pulls BTC-hourly markets from both venues' public APIs, prints opportunities where combined cost < $0.99. **Works with no API keys.**
- `arb.py` — execution skeleton. **Defaults to `--dry-run`.** Requires Kalshi credentials + Polymarket private key + USDC on Polygon.

## Quick start

```bash
pip install -r requirements.txt
python scan.py                   # always works
python scan.py --tag bitcoin     # filter
python arb.py --threshold 0.97   # dry-run, prints what it would do
```

## How it makes money

If Polymarket says "BTC up by 1pm" YES = $0.55 and Kalshi says "BTC up by 1pm" NO = $0.43, you buy both for $0.98 total and one of them pays $1 at resolution. ~2¢ per dollar = 2% per cycle, which compounds fast on hourly markets.

## How it blows up

- **Resolution-criteria mismatch** — Polymarket and Kalshi sometimes word the same event differently (gov-shutdown contracts settled on different snapshots). Read both rule pages before trading.
- **Liquidity drains** — orderbook on the cheap side may be 100 contracts; you take it and the spread vanishes.
- **Settlement currency mismatch** — Polymarket pays USDC on Polygon, Kalshi pays USD via ACH. Capital recycling has friction.
- **Polymarket KYC** — US users may need additional verification post-QCEX acquisition.

## Open-source references

- [CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot](https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot)
- [ImMike/polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage)
