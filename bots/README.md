# Trading Bot Scaffolds

Four starter bots from the [research synthesis](../README.md), ranked by Sharpe-per-effort:

| Folder | Strategy | Capital | Realistic APR | Effort |
|---|---|---|---|---|
| [`funding-rate-arb/`](./funding-rate-arb/) | Long spot + short perp on crypto majors | $1k+ | 8–15% | Low (cron + alerts) |
| [`polymarket-kalshi-arb/`](./polymarket-kalshi-arb/) | Cross-venue mispricing on BTC-hourly / sports | $500+ | 15–25% | Medium |
| [`polymarket-mm/`](./polymarket-mm/) | Maker-rebate farming on Polymarket CLOB v2 | $1k+ | 10–20% | Medium |
| [`options-wheel/`](./options-wheel/) | CSP + covered call on SPY/IWM/QQQ via Tradier | $5k+ | 8–12% | Low |

**All bots default to dry-run / read-only mode.** No order is sent without an explicit flag and configured API keys. Run the scanner first, paper-trade for weeks, then risk real money in the smallest size you'd be unhappy to lose.

## Common setup

```bash
cd bots/<bot-name>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in keys when you're ready
python scan.py        # always works without keys
```

## Disclaimer

These are educational scaffolds, not financial advice. Backtests lie, fills slip, exchanges go down, regulators change rules. ~70–95% of retail algo traders lose money. Read [the reality check](#) in the research summary before funding anything.
