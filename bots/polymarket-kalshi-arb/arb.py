"""Execution skeleton for cross-venue arbs. Defaults to --dry-run.

This is intentionally minimal — Polymarket CLOB v2 order signing requires
py-clob-client and a funded Polygon address; Kalshi orders need RSA-signed
auth. Wire those in once you've validated arb opportunities with scan.py.

    python arb.py --threshold 0.97
    python arb.py --threshold 0.97 --live
"""
from __future__ import annotations

import argparse
import sys
import time

from scan import fetch_polymarket, fetch_kalshi, naive_match


def execute_leg_polymarket(market_id: str, side: str, price: float, size: int, live: bool):
    print(f"  [polymarket] {side} {size} @ {price:.3f} on {market_id[:16]}…")
    if not live:
        print("    [dry-run] no order sent")
        return
    # TODO: from py_clob_client.client import ClobClient
    # from py_clob_client.clob_types import OrderArgs
    # client = ClobClient(host, key=PK, chain_id=137, funder=FUNDER)
    # order = client.create_order(OrderArgs(price=price, size=size, side=side, token_id=...))
    # client.post_order(order)
    raise NotImplementedError("wire up py-clob-client before going live")


def execute_leg_kalshi(ticker: str, side: str, price_cents: int, count: int, live: bool):
    print(f"  [kalshi] {side} {count} @ {price_cents}¢ on {ticker}")
    if not live:
        print("    [dry-run] no order sent")
        return
    # TODO: kalshi POST /trade-api/v2/portfolio/orders with RSA signature
    raise NotImplementedError("wire up Kalshi auth before going live")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="bitcoin")
    p.add_argument("--threshold", type=float, default=0.97,
                   help="execute when total cost <= this (lower = wider edge required)")
    p.add_argument("--size-usd", type=float, default=50, help="per-arb capital")
    p.add_argument("--live", action="store_true")
    p.add_argument("--once", action="store_true", help="single pass instead of loop")
    args = p.parse_args()

    mode = "LIVE" if args.live else "DRY-RUN"
    print(f"=== polymarket↔kalshi arb [{mode}] threshold={args.threshold} ===\n")

    while True:
        try:
            poly = fetch_polymarket(args.tag)
            kal = fetch_kalshi("KXBTC" if args.tag == "bitcoin" else None)
            arbs = [a for a in naive_match(poly, kal) if a[2] <= args.threshold]
            if arbs:
                print(f"[{time.strftime('%H:%M:%S')}] {len(arbs)} arb(s):")
                for yes_m, no_m, cost in arbs[:5]:
                    edge = 1 - cost
                    size = int(args.size_usd / cost)
                    print(f"  cost={cost:.3f} edge={edge:.3f} size={size}")
                    print(f"   YES leg ({yes_m.venue}): {yes_m.question[:60]}")
                    print(f"   NO  leg ({no_m.venue}): {no_m.question[:60]}")
                    if yes_m.venue == "polymarket":
                        execute_leg_polymarket(yes_m.id, "BUY_YES", yes_m.yes_ask, size, args.live)
                        execute_leg_kalshi(no_m.id, "BUY_NO", int(no_m.no_ask * 100), size, args.live)
                    else:
                        execute_leg_kalshi(yes_m.id, "BUY_YES", int(yes_m.yes_ask * 100), size, args.live)
                        execute_leg_polymarket(no_m.id, "BUY_NO", no_m.no_ask, size, args.live)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] no arbs (cost > {args.threshold})")
        except Exception as e:
            print(f"  error: {e}", file=sys.stderr)

        if args.once:
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
