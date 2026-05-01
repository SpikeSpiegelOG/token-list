"""Delta-neutral funding-rate bot. Defaults to --dry-run (no orders sent).

Usage:
    python bot.py --symbol BTC/USDT --exchange binance --size 1000          # dry
    python bot.py --symbol BTC/USDT --exchange binance --size 1000 --live   # real
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

import ccxt
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    exchange: str
    symbol_spot: str       # e.g. BTC/USDT
    symbol_perp: str       # e.g. BTC/USDT:USDT
    size_usd: float
    live: bool
    min_funding_apr: float = 5.0   # don't open if APR below this
    exit_funding_apr: float = 0.0  # close if APR drops below this


def make_exchange(name: str, live: bool) -> ccxt.Exchange:
    cls = getattr(ccxt, name)
    if not live:
        return cls({"enableRateLimit": True})
    key = os.getenv(f"{name.upper()}_API_KEY")
    secret = os.getenv(f"{name.upper()}_API_SECRET")
    if not key or not secret:
        sys.exit(f"missing {name.upper()}_API_KEY/_SECRET in .env")
    cfg = {"apiKey": key, "secret": secret, "enableRateLimit": True}
    if name == "okx":
        cfg["password"] = os.getenv("OKX_PASSWORD") or sys.exit("missing OKX_PASSWORD")
    return cls(cfg)


def current_funding_apr(ex: ccxt.Exchange, perp_symbol: str) -> float:
    rate = ex.fetch_funding_rate(perp_symbol)
    return (rate["fundingRate"] or 0) * 3 * 365 * 100


def open_position(ex: ccxt.Exchange, cfg: Config, mark_price: float):
    qty = cfg.size_usd / mark_price
    print(f"  → BUY  spot {cfg.symbol_spot} qty={qty:.6f}")
    print(f"  → SELL perp {cfg.symbol_perp} qty={qty:.6f}")
    if not cfg.live:
        print("  [dry-run] no orders sent")
        return
    ex.options["defaultType"] = "spot"
    ex.create_market_buy_order(cfg.symbol_spot, qty)
    ex.options["defaultType"] = "swap"
    ex.create_market_sell_order(cfg.symbol_perp, qty)


def close_position(ex: ccxt.Exchange, cfg: Config, qty: float):
    print(f"  → SELL spot {cfg.symbol_spot} qty={qty:.6f}")
    print(f"  → BUY  perp {cfg.symbol_perp} qty={qty:.6f}")
    if not cfg.live:
        print("  [dry-run] no orders sent")
        return
    ex.options["defaultType"] = "spot"
    ex.create_market_sell_order(cfg.symbol_spot, qty)
    ex.options["defaultType"] = "swap"
    ex.create_market_buy_order(cfg.symbol_perp, qty)


def loop(cfg: Config):
    ex = make_exchange(cfg.exchange, cfg.live)
    in_position = False
    qty = 0.0

    while True:
        try:
            ticker = ex.fetch_ticker(cfg.symbol_perp)
            mark = ticker["last"]
            apr = current_funding_apr(ex, cfg.symbol_perp)
            print(f"[{time.strftime('%H:%M:%S')}] {cfg.symbol_perp} "
                  f"mark={mark:.2f} funding_apr={apr:+.2f}% in_pos={in_position}")

            if not in_position and apr >= cfg.min_funding_apr:
                print(" opening delta-neutral position")
                open_position(ex, cfg, mark)
                qty = cfg.size_usd / mark
                in_position = True
            elif in_position and apr < cfg.exit_funding_apr:
                print(" closing — funding dropped below threshold")
                close_position(ex, cfg, qty)
                in_position = False
                qty = 0.0
        except Exception as e:
            print(f" error: {e}")

        time.sleep(900)  # 15 min


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--exchange", required=True)
    p.add_argument("--symbol", required=True, help="base symbol, e.g. BTC/USDT")
    p.add_argument("--size", type=float, required=True, help="USD notional per leg")
    p.add_argument("--live", action="store_true", help="actually send orders")
    p.add_argument("--min-apr", type=float, default=5.0)
    p.add_argument("--exit-apr", type=float, default=0.0)
    args = p.parse_args()

    cfg = Config(
        exchange=args.exchange,
        symbol_spot=args.symbol,
        symbol_perp=f"{args.symbol}:{args.symbol.split('/')[1]}",
        size_usd=args.size,
        live=args.live,
        min_funding_apr=args.min_apr,
        exit_funding_apr=args.exit_apr,
    )

    mode = "LIVE" if cfg.live else "DRY-RUN"
    print(f"=== funding-rate bot [{mode}] ===")
    print(f" exchange:  {cfg.exchange}")
    print(f" spot:      {cfg.symbol_spot}")
    print(f" perp:      {cfg.symbol_perp}")
    print(f" size:      ${cfg.size_usd:,.0f}")
    print(f" min APR:   {cfg.min_funding_apr}%   exit APR: {cfg.exit_funding_apr}%")
    print()

    loop(cfg)


if __name__ == "__main__":
    main()
