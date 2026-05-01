"""Inspect Polymarket markets and preview maker quotes. No keys required."""
from __future__ import annotations

import argparse
import json
import sys

import requests
from tabulate import tabulate

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"


def list_rewarded(limit: int = 50):
    r = requests.get(GAMMA, params={"limit": limit, "active": "true", "closed": "false",
                                     "rewardsMinSize": 1, "order": "rewardsDailyRate",
                                     "ascending": "false"}, timeout=15)
    r.raise_for_status()
    rows = []
    for m in r.json():
        rewards = m.get("rewards") or {}
        rows.append([
            (m.get("question") or "")[:60],
            m.get("conditionId", "")[:14] + "…",
            f"${float(m.get('volume24hr') or 0):,.0f}",
            f"${float(rewards.get('dailyRate') or 0):,.0f}",
            f"{float(rewards.get('minSize') or 0):.2f}",
            f"{float(rewards.get('maxSpread') or 0):.3f}",
        ])
    print(tabulate(rows, headers=["question", "cond_id", "vol24h",
                                  "rewards/day", "min size", "max spread"]))


def inspect(condition_id: str, notional: float, spread_bps: int):
    # market metadata via Gamma
    r = requests.get(GAMMA, params={"condition_ids": condition_id}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        sys.exit(f"market {condition_id} not found")
    m = data[0]
    tokens = m.get("clobTokenIds")
    if isinstance(tokens, str):
        tokens = json.loads(tokens)
    print(f"Market: {m.get('question')}")
    print(f"  end:  {m.get('endDate')}")
    print(f"  cond: {condition_id}")
    print()

    for outcome, token_id in zip(["YES", "NO"], tokens):
        book = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15).json()
        bids, asks = book.get("bids", []), book.get("asks", [])
        best_bid = float(bids[-1]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        mid = (best_bid + best_ask) / 2
        half = spread_bps / 1e4 / 2
        my_bid = max(0.01, round(mid - half, 3))
        my_ask = min(0.99, round(mid + half, 3))
        size = round(notional / mid, 2) if mid > 0 else 0
        print(f"  {outcome:3} top bid={best_bid:.3f} ask={best_ask:.3f} mid={mid:.3f}")
        print(f"      → quote: BID {my_bid} x {size}    ASK {my_ask} x {size}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-rewarded")

    insp = sub.add_parser("inspect")
    insp.add_argument("--condition-id", required=True)
    insp.add_argument("--notional", type=float, default=200, help="USD per side")
    insp.add_argument("--spread-bps", type=int, default=200, help="200 = 2%")

    args = p.parse_args()
    if args.cmd == "list-rewarded":
        list_rewarded()
    else:
        inspect(args.condition_id, args.notional, args.spread_bps)


if __name__ == "__main__":
    main()
