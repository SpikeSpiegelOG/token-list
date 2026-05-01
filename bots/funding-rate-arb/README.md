# Funding-Rate Arbitrage Bot

Delta-neutral cash-and-carry on crypto perpetual swaps. Long spot, short perp, collect funding payments every 8h.

## How it works

When perp funding is positive, longs pay shorts. Hold $X spot + short $X perp → no directional exposure, you just collect funding (annualized 5–15% on majors in calm regimes, occasionally 30%+).

## Files

- `scan.py` — read-only: prints current funding rates and APRs across exchanges. Works with no keys.
- `bot.py` — opens / closes / monitors delta-neutral positions. **Defaults to `--dry-run`.**

## Quick start

```bash
pip install -r requirements.txt

# 1. See where the juice is right now (no keys needed)
python scan.py

# 2. Paper-mode: see what bot.py would do
python bot.py --symbol BTC/USDT --exchange binance --size 1000

# 3. Live (only after .env is set, only with money you can lose)
python bot.py --symbol BTC/USDT --exchange binance --size 1000 --live
```

## How it blows up

- **Funding flips negative** → close immediately, switch pair.
- **Short-leg liquidation** on a wick → cap effective leverage <3x, alert at 70% margin.
- **Exchange insolvency** → split capital across 2–3 venues, never park more than you'd accept losing.
- **Wash-sale equivalents in your tax jurisdiction** → talk to an accountant before scaling.
