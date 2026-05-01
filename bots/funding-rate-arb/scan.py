"""Scan funding rates across exchanges. Read-only, no API keys required."""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import ccxt
from tabulate import tabulate

EXCHANGES = ["binance", "bybit", "okx", "gate", "kucoinfutures"]
DEFAULT_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
PAYMENTS_PER_DAY = 3  # most majors fund every 8h


def fetch_one(exchange_name: str, symbol: str):
    try:
        ex_cls = getattr(ccxt, exchange_name)
        ex = ex_cls({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        rate = ex.fetch_funding_rate(symbol)
        funding = rate.get("fundingRate")
        if funding is None:
            return None
        apr = funding * PAYMENTS_PER_DAY * 365 * 100
        return {
            "exchange": exchange_name,
            "symbol": symbol,
            "funding_pct": funding * 100,
            "apr_pct": apr,
            "next": rate.get("fundingDatetime") or rate.get("nextFundingDatetime"),
        }
    except Exception as e:
        return {"exchange": exchange_name, "symbol": symbol, "error": str(e)[:60]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    p.add_argument("--exchanges", nargs="*", default=EXCHANGES)
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()

    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_one, ex, sym)
                   for ex in args.exchanges for sym in args.symbols]
        for f in as_completed(futures):
            r = f.result()
            if r:
                rows.append(r)

    ok = [r for r in rows if "error" not in r]
    errs = [r for r in rows if "error" in r]
    ok.sort(key=lambda r: r["apr_pct"], reverse=True)

    print(tabulate(
        [[r["exchange"], r["symbol"], f"{r['funding_pct']:+.4f}%",
          f"{r['apr_pct']:+.2f}%", r.get("next") or ""] for r in ok[:args.top]],
        headers=["exchange", "symbol", "funding (8h)", "apr", "next funding"],
    ))

    if errs:
        print(f"\n{len(errs)} errors (likely unsupported symbol on that exchange)")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
