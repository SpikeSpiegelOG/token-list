"""Polymarket CLOB v2 market-maker. Defaults to --dry-run.

Loop:
  1. fetch top-of-book on YES + NO outcome tokens
  2. compute target bid/ask = mid ± spread/2
  3. cancel stale orders, post new ones
  4. sleep N seconds, repeat

Live mode requires py-clob-client (see requirements.txt) and a funded wallet.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"


def get_market(condition_id: str):
    r = requests.get(GAMMA, params={"condition_ids": condition_id}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        sys.exit(f"market {condition_id} not found")
    m = data[0]
    tokens = m.get("clobTokenIds")
    if isinstance(tokens, str):
        tokens = json.loads(tokens)
    return m, tokens  # tokens = [yes_token_id, no_token_id]


def get_book(token_id: str):
    r = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15)
    r.raise_for_status()
    return r.json()


def make_client():
    """Lazy-import py-clob-client only when going live."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.constants import POLYGON
    except ImportError:
        sys.exit("install py-clob-client first: pip install py-clob-client")

    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    host = os.getenv("POLYMARKET_HOST", CLOB)
    if not pk or not funder:
        sys.exit("missing POLYMARKET_PRIVATE_KEY / POLYMARKET_FUNDER_ADDRESS in .env")

    client = ClobClient(host, key=pk, chain_id=POLYGON, funder=funder, signature_type=2)
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def post_orders(client, token_id: str, bid: float, ask: float, size: float):
    from py_clob_client.clob_types import OrderArgs, OrderType, BUY, SELL
    bid_args = OrderArgs(price=bid, size=size, side=BUY, token_id=token_id)
    ask_args = OrderArgs(price=ask, size=size, side=SELL, token_id=token_id)
    for args, label in [(bid_args, "BID"), (ask_args, "ASK")]:
        signed = client.create_order(args)
        resp = client.post_order(signed, OrderType.GTC)
        print(f"      {label} resp: {resp}")


def cancel_all(client, token_id: str):
    open_orders = client.get_orders(market=token_id)
    for o in open_orders:
        client.cancel(o["id"])


def loop(condition_id: str, notional: float, spread_bps: int,
         interval: int, live: bool):
    market, tokens = get_market(condition_id)
    print(f"market: {market.get('question')}")
    client = make_client() if live else None

    while True:
        try:
            for outcome, token_id in zip(["YES", "NO"], tokens):
                book = get_book(token_id)
                bids, asks = book.get("bids", []), book.get("asks", [])
                if not bids or not asks:
                    print(f"  {outcome} empty book, skipping")
                    continue
                best_bid = float(bids[-1]["price"])
                best_ask = float(asks[0]["price"])
                mid = (best_bid + best_ask) / 2
                half = spread_bps / 1e4 / 2
                my_bid = round(max(0.01, mid - half), 3)
                my_ask = round(min(0.99, mid + half), 3)
                size = round(notional / mid, 2)
                print(f"[{time.strftime('%H:%M:%S')}] {outcome} mid={mid:.3f} "
                      f"→ BID {my_bid}x{size}  ASK {my_ask}x{size}")
                if live:
                    cancel_all(client, token_id)
                    post_orders(client, token_id, my_bid, my_ask, size)
                else:
                    print("    [dry-run] no orders sent")
        except Exception as e:
            print(f" error: {e}", file=sys.stderr)
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--condition-id", required=True)
    p.add_argument("--notional", type=float, default=200, help="USD per side")
    p.add_argument("--spread-bps", type=int, default=200, help="200 = 2% total")
    p.add_argument("--interval", type=int, default=20)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()

    print(f"=== polymarket MM [{'LIVE' if args.live else 'DRY-RUN'}] ===")
    loop(args.condition_id, args.notional, args.spread_bps, args.interval, args.live)


if __name__ == "__main__":
    main()
