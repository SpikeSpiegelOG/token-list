# Options Wheel Bot (Tradier)

Cash-secured-put + covered-call wheel on liquid ETFs (SPY, IWM, QQQ). The classic boring strategy — sell a put, get assigned shares if it goes ITM, sell a call against those shares, get called away, repeat.

## Files

- `chain.py` — read-only: pull options chain from Tradier sandbox, find candidate puts at target delta and DTE. **Works with Tradier's free sandbox token.**
- `wheel.py` — execution skeleton. **Defaults to `--paper`** (Tradier sandbox).

## Quick start

```bash
pip install -r requirements.txt
# Get a free sandbox token at https://developer.tradier.com/
echo "TRADIER_SANDBOX_TOKEN=YOUR_TOKEN" > .env

python chain.py --symbol IWM --target-delta 0.25 --min-dte 30 --max-dte 45
python wheel.py --symbol IWM --contracts 1               # paper mode
python wheel.py --symbol IWM --contracts 1 --live        # real money
```

## How it works

1. **Sell cash-secured put** at ~0.25 delta, 30–45 DTE. Collect premium.
2. **If expires worthless** — keep the premium, sell another put.
3. **If assigned** — you now own 100 shares per contract.
4. **Sell a covered call** at ~0.25 delta, 30–45 DTE.
5. **If called away** — pocket premium + (strike − cost basis), restart at step 1.

## Realistic returns

8–12% annually on the cash-collateral basis in calm regimes. Underperforms buy-and-hold in raging bull markets (you cap upside) and gets *hurt* in March-2020-style gap-downs because you're short vol.

## How it blows up

- **Gap-down bigger than your premium cushion** — assigned at $X, stock now $X-15, premium was $1. Eat the loss or roll.
- **Locked into a bag** — you sell calls below your cost basis and they get exercised → realized loss.
- **Tax drag** — short-term assignments + frequent rolls = ordinary income. Section 1256 contracts (SPX, /ES) get 60/40 treatment if you want to upgrade.
- **June 4, 2026 PDT change** is irrelevant here (no day trading), but worth knowing.

## References

- [Tradier Brokerage API](https://documentation.tradier.com/)
- [Early Retirement Now: why the wheel doesn't always work](https://earlyretirementnow.com/2024/09/17/the-wheel-strategy-doesnt-work-options-series-part-12/)
