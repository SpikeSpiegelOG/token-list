"""Options-wheel executor on Tradier. Defaults to --paper (sandbox).

Loop:
  1. Check current position in symbol
     - none + cash    → sell cash-secured put at target delta/DTE
     - long shares    → sell covered call at target delta/DTE
  2. Wait for fill / expiration / assignment
  3. Repeat

This is a scaffold. Production would add: roll logic before expiration, IV
filter (skip if IV is in bottom-quartile = bad premium), earnings avoidance,
position sizing, max-loss circuit breaker.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from chain import chain, expirations, headers as quote_headers, quote

load_dotenv()


def base_url(live: bool) -> str:
    return "https://api.tradier.com/v1" if live else "https://sandbox.tradier.com/v1"


def auth_headers(live: bool) -> dict:
    tok = os.getenv("TRADIER_PROD_TOKEN" if live else "TRADIER_SANDBOX_TOKEN")
    if not tok:
        sys.exit(f"missing {'TRADIER_PROD_TOKEN' if live else 'TRADIER_SANDBOX_TOKEN'} in .env")
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}


def get_position(symbol: str, live: bool) -> int:
    """Return long-share quantity (0 if none)."""
    acct = os.getenv("TRADIER_ACCOUNT_ID")
    if not acct:
        return 0  # unknown in sandbox-without-account; assume flat
    r = requests.get(f"{base_url(live)}/accounts/{acct}/positions",
                     headers=auth_headers(live), timeout=10)
    r.raise_for_status()
    positions = (r.json().get("positions") or {}).get("position") or []
    if isinstance(positions, dict):
        positions = [positions]
    for p in positions:
        if p.get("symbol") == symbol:
            return int(p.get("quantity", 0))
    return 0


def find_target(symbol: str, right: str, target_delta: float,
                min_dte: int, max_dte: int):
    today = date.today()
    candidates = []
    for exp in expirations(symbol):
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        if dte < min_dte or dte > max_dte:
            continue
        for opt in chain(symbol, exp):
            if opt.get("option_type") != right:
                continue
            greeks = opt.get("greeks") or {}
            d = greeks.get("delta")
            if d is None or (opt.get("bid") or 0) <= 0:
                continue
            candidates.append((abs(abs(d) - target_delta), opt))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def place_order(symbol: str, option_symbol: str, side: str,
                qty: int, limit: float, live: bool, paper_send: bool):
    acct = os.getenv("TRADIER_ACCOUNT_ID")
    if not acct:
        print(f"  [no account configured] would {side} {qty} {option_symbol} @ {limit}")
        return
    payload = {
        "class": "option",
        "symbol": symbol,
        "option_symbol": option_symbol,
        "side": side,           # sell_to_open / buy_to_close
        "quantity": qty,
        "type": "limit",
        "duration": "gtc",
        "price": f"{limit:.2f}",
    }
    if not paper_send:
        print(f"  [dry-run] {payload}")
        return
    r = requests.post(f"{base_url(live)}/accounts/{acct}/orders",
                      headers=auth_headers(live), data=payload, timeout=10)
    print(f"  order resp: {r.status_code} {r.text[:200]}")


def step(symbol: str, contracts: int, target_delta: float,
         min_dte: int, max_dte: int, live: bool, paper_send: bool):
    pos = get_position(symbol, live)
    spot = quote(symbol)
    print(f"[{time.strftime('%H:%M:%S')}] {symbol} spot=${spot:.2f} position={pos}sh")

    needed = contracts * 100
    if pos >= needed:
        # have shares → sell covered call
        opt = find_target(symbol, "call", target_delta, min_dte, max_dte)
        if not opt:
            print("  no call candidate in DTE window")
            return
        mid = ((opt.get("bid") or 0) + (opt.get("ask") or 0)) / 2
        print(f"  → SELL_TO_OPEN {contracts}x {opt['symbol']} "
              f"strike=${opt['strike']} delta={opt['greeks']['delta']:+.2f} "
              f"limit=${mid:.2f}")
        place_order(symbol, opt["symbol"], "sell_to_open",
                    contracts, mid, live, paper_send)
    else:
        # no shares → sell cash-secured put
        opt = find_target(symbol, "put", target_delta, min_dte, max_dte)
        if not opt:
            print("  no put candidate in DTE window")
            return
        mid = ((opt.get("bid") or 0) + (opt.get("ask") or 0)) / 2
        cash_required = opt["strike"] * 100 * contracts
        print(f"  → SELL_TO_OPEN {contracts}x {opt['symbol']} "
              f"strike=${opt['strike']} delta={opt['greeks']['delta']:+.2f} "
              f"limit=${mid:.2f}  (collateral=${cash_required:,.0f})")
        place_order(symbol, opt["symbol"], "sell_to_open",
                    contracts, mid, live, paper_send)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True, help="e.g. IWM, SPY, QQQ")
    p.add_argument("--contracts", type=int, default=1)
    p.add_argument("--target-delta", type=float, default=0.25)
    p.add_argument("--min-dte", type=int, default=30)
    p.add_argument("--max-dte", type=int, default=45)
    p.add_argument("--interval", type=int, default=3600,
                   help="re-evaluate every N seconds (default hourly)")
    p.add_argument("--live", action="store_true", help="use Tradier production")
    p.add_argument("--send", action="store_true",
                   help="actually POST orders (default: dry-run)")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    mode = "LIVE-SEND" if (args.live and args.send) else \
           "PAPER-SEND" if args.send else "DRY-RUN"
    print(f"=== options wheel [{mode}] ===")
    print(f"  symbol={args.symbol} contracts={args.contracts} "
          f"delta={args.target_delta} dte={args.min_dte}-{args.max_dte}")
    print()

    while True:
        try:
            step(args.symbol, args.contracts, args.target_delta,
                 args.min_dte, args.max_dte, args.live, args.send)
        except Exception as e:
            print(f"  error: {e}", file=sys.stderr)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
