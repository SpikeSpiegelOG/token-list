"""Find candidate puts for the wheel. Uses Tradier sandbox.

    python chain.py --symbol IWM --target-delta 0.25 --min-dte 30 --max-dte 45
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()

SANDBOX = "https://sandbox.tradier.com/v1"


def headers():
    tok = os.getenv("TRADIER_SANDBOX_TOKEN")
    if not tok:
        sys.exit("set TRADIER_SANDBOX_TOKEN in .env (free at developer.tradier.com)")
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}


def expirations(symbol: str) -> list[str]:
    r = requests.get(f"{SANDBOX}/markets/options/expirations",
                     params={"symbol": symbol, "includeAllRoots": "true"},
                     headers=headers(), timeout=10)
    r.raise_for_status()
    data = r.json().get("expirations") or {}
    return data.get("date") or []


def chain(symbol: str, expiration: str) -> list[dict]:
    r = requests.get(f"{SANDBOX}/markets/options/chains",
                     params={"symbol": symbol, "expiration": expiration, "greeks": "true"},
                     headers=headers(), timeout=10)
    r.raise_for_status()
    data = r.json().get("options") or {}
    return data.get("option") or []


def quote(symbol: str) -> float:
    r = requests.get(f"{SANDBOX}/markets/quotes",
                     params={"symbols": symbol}, headers=headers(), timeout=10)
    r.raise_for_status()
    return float(r.json()["quotes"]["quote"]["last"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--target-delta", type=float, default=0.25,
                   help="abs(delta) target for puts (0.25 = ~25% ITM probability)")
    p.add_argument("--min-dte", type=int, default=30)
    p.add_argument("--max-dte", type=int, default=45)
    p.add_argument("--right", choices=["put", "call"], default="put")
    args = p.parse_args()

    spot = quote(args.symbol)
    print(f"{args.symbol} last = ${spot:.2f}\n")

    today = date.today()
    candidates = []
    for exp in expirations(args.symbol):
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        if dte < args.min_dte or dte > args.max_dte:
            continue
        for opt in chain(args.symbol, exp):
            if opt.get("option_type") != args.right:
                continue
            greeks = opt.get("greeks") or {}
            delta = greeks.get("delta")
            if delta is None:
                continue
            candidates.append({
                "exp": exp, "dte": dte,
                "strike": opt["strike"],
                "bid": opt.get("bid") or 0, "ask": opt.get("ask") or 0,
                "delta": delta, "iv": greeks.get("mid_iv") or 0,
                "symbol": opt["symbol"],
            })

    if not candidates:
        sys.exit("no candidates found in DTE window")

    # rank by closeness to target absolute delta
    candidates.sort(key=lambda c: abs(abs(c["delta"]) - args.target_delta))
    top = candidates[:10]

    print(tabulate(
        [[c["exp"], c["dte"], f"${c['strike']:.2f}",
          f"${c['bid']:.2f}", f"${c['ask']:.2f}",
          f"{c['delta']:+.3f}", f"{c['iv']*100:.1f}%",
          f"{(c['bid']/c['strike']*365/c['dte']*100):.1f}%"]
         for c in top],
        headers=["expiration", "dte", "strike", "bid", "ask",
                 "delta", "iv", "ann.yield"]))
    print("\nTip: pick the row closest to your target delta with a tight bid-ask spread.")


if __name__ == "__main__":
    main()
