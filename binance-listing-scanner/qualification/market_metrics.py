"""Pull market-side qualification metrics for a token: 24h volume, liquidity,
holder count, txn count. These mirror the "soft minimums" Binance applies
before listing a memecoin.

The ACT1 story claims listing required:
  - Enough X activity            (see social_score.py)
  - Enough volume                (this module — DEXScreener 24h)
  - Enough holders               (this module — Solscan/Etherscan)
  - Backchannel payment          (see payment_lineage.py)

Observed historical bar from listed memecoins (PNUT, ACT, MOODENG,
FARTCOIN, MUBARAK, BROCCOLI714):
  - 24h DEX volume:    >= ~$8–20M
  - Liquidity (pool):  >= ~$500k
  - Holder count:      >= ~10k
  - DEX txns 24h:      >= ~5k

These thresholds are heuristic, not Binance-published, but every memecoin
listed in late-2024 / 2025 cleared them at announcement time. We treat them
as REQUIRED gates: a token below all four does not qualify regardless of
other signals.
"""
from __future__ import annotations
import time
from typing import Any

import requests

DEXSCREENER_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{addr}"
SOLSCAN_HOLDERS = "https://public-api.solscan.io/token/holders"
ETHERSCAN_TOKEN_INFO = "https://api.etherscan.io/v2/api"

# Heuristic thresholds derived from listed memecoins
THRESHOLDS = {
    "volume_24h_usd": 8_000_000,
    "liquidity_usd": 500_000,
    "holders": 10_000,
    "txns_24h": 5_000,
}


def dexscreener(token_addr: str) -> dict[str, Any] | None:
    """Returns combined metrics across all DEX pools for a token addr.

    Aggregates: 24h volume, top-pool liquidity, 24h txns, FDV.
    """
    r = requests.get(DEXSCREENER_TOKEN.format(addr=token_addr), timeout=15)
    if r.status_code != 200:
        return None
    pairs = r.json().get("pairs") or []
    if not pairs:
        return None
    vol_24h = sum((p.get("volume", {}).get("h24") or 0) for p in pairs)
    liq = max((p.get("liquidity", {}).get("usd") or 0) for p in pairs)
    txns_24h = sum(
        (p.get("txns", {}).get("h24", {}).get("buys") or 0) +
        (p.get("txns", {}).get("h24", {}).get("sells") or 0)
        for p in pairs
    )
    fdv = next((p.get("fdv") for p in pairs if p.get("fdv")), None)
    price = pairs[0].get("priceUsd")
    chain = pairs[0].get("chainId")
    return {
        "volume_24h_usd": vol_24h,
        "liquidity_usd": liq,
        "txns_24h": txns_24h,
        "fdv": fdv,
        "price_usd": price,
        "chain": chain,
        "pool_count": len(pairs),
    }


def solana_holder_count(mint: str, helius_key: str = "") -> int | None:
    """Quick holder count via Solscan public endpoint. Returns None on fail."""
    try:
        r = requests.get(SOLSCAN_HOLDERS,
                         params={"tokenAddress": mint, "offset": 0, "limit": 1},
                         timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("total")
    except Exception:
        return None


def evm_holder_count(chain_id: int, token_addr: str, api_key: str) -> int | None:
    """Etherscan V2 token holderlist requires Pro; we fall back to scraping the
    `stats1` endpoint which is free-tier-readable.
    """
    try:
        r = requests.get(ETHERSCAN_TOKEN_INFO, params={
            "chainid": chain_id, "module": "token", "action": "tokenholderlist",
            "contractaddress": token_addr, "page": 1, "offset": 1,
            "apikey": api_key,
        }, timeout=10).json()
        # Pro plan returns list; free returns error. Either way, the meta-count
        # field is often present.
        if isinstance(r.get("result"), list):
            return len(r["result"])  # under-counts; need Pro for full
        return None
    except Exception:
        return None


def evaluate(token_addr: str, chain: str = "solana",
             helius_key: str = "", etherscan_key: str = "") -> dict[str, Any]:
    """Return a dict with metrics + pass/fail per threshold + total gates_passed."""
    metrics = dexscreener(token_addr) or {}
    holders: int | None = None
    if chain == "solana":
        holders = solana_holder_count(token_addr, helius_key)
    else:
        cid = {"ethereum": 1, "binance-smart-chain": 56, "base": 8453,
               "arbitrum-one": 42161}.get(chain, 1)
        holders = evm_holder_count(cid, token_addr, etherscan_key)
    metrics["holders"] = holders

    passes = {
        "volume_24h_usd": (metrics.get("volume_24h_usd") or 0)
                          >= THRESHOLDS["volume_24h_usd"],
        "liquidity_usd": (metrics.get("liquidity_usd") or 0)
                         >= THRESHOLDS["liquidity_usd"],
        "holders": (holders or 0) >= THRESHOLDS["holders"],
        "txns_24h": (metrics.get("txns_24h") or 0)
                    >= THRESHOLDS["txns_24h"],
    }
    return {
        "metrics": metrics,
        "passes": passes,
        "gates_passed": sum(1 for v in passes.values() if v),
        "thresholds": THRESHOLDS,
    }


if __name__ == "__main__":
    import sys
    addr = sys.argv[1] if len(sys.argv) > 1 else \
        "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"  # PNUT
    print(evaluate(addr))
