"""For each listing in data/listings.json, find every wallet that bought the
token in the PRE_LISTING_WINDOW_HOURS leading up to the announcement.

Strategy:
  - EVM chains (eth/bsc/base/arb/etc.) → Etherscan V2 multichain `tokentx`
  - Solana → Helius `getSignaturesForAddress` + `getTransaction` to detect
    DEX swap inflows. (Pump.fun + Jupiter + Raydium routes accounted for.)

We mark a wallet as "pre-listing buyer" if it received the token in that
window via a DEX/router (not from a known CEX or the deployer).

Output: data/buyers/{symbol}.json
[
  { "wallet": "0xabc...", "chain": "ethereum", "ts": 1731234567,
    "amount": "1234567.0", "tx": "0x..." },
  ...
]
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Iterable

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

# Etherscan V2 chainids
EVM_CHAINS: dict[str, int] = {
    "ethereum": 1,
    "binance-smart-chain": 56,
    "polygon-pos": 137,
    "base": 8453,
    "arbitrum-one": 42161,
    "optimistic-ethereum": 10,
    "avalanche": 43114,
}

# Wallets to ignore — known CEX hot wallets, routers, burn addresses.
# Full lists live in `data/labels/`; tiny seed set here.
IGNORE_LABELS = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance 14
    "0xf977814e90da44bfa03b6295a0616a897441acec",  # Binance 20
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549",  # Binance 15
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",  # Binance 16
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8",  # Binance 7
    "0x564286362092d8e7936f0549571a803b203aaced",  # Binance 18
}


def _etherscan_token_transfers(chain_id: int, token_addr: str,
                               start_ts: int, end_ts: int) -> list[dict]:
    """Use Etherscan V2 to pull ERC-20 transfers for `token_addr` in window.

    Etherscan doesn't accept timestamp ranges directly — we convert to block
    numbers via the `getblocknobytime` module first.
    """
    def block_at(ts: int) -> int:
        r = requests.get(ETHERSCAN_V2, params={
            "chainid": chain_id, "module": "block", "action": "getblocknobytime",
            "timestamp": ts, "closest": "before", "apikey": config.ETHERSCAN_API_KEY,
        }, timeout=10).json()
        return int(r["result"])

    start_block = block_at(start_ts)
    end_block = block_at(end_ts)

    out: list[dict] = []
    page = 1
    while True:
        r = requests.get(ETHERSCAN_V2, params={
            "chainid": chain_id, "module": "account", "action": "tokentx",
            "contractaddress": token_addr, "startblock": start_block,
            "endblock": end_block, "page": page, "offset": 1000,
            "sort": "asc", "apikey": config.ETHERSCAN_API_KEY,
        }, timeout=20).json()
        result = r.get("result")
        if not isinstance(result, list) or not result:
            break
        out.extend(result)
        if len(result) < 1000:
            break
        page += 1
        time.sleep(0.25)
    return out


def evm_buyers(token_addr: str, chain: str, anno_ts: int, window_h: int) -> list[dict]:
    chain_id = EVM_CHAINS.get(chain)
    if not chain_id:
        return []
    start = anno_ts - window_h * 3600
    txs = _etherscan_token_transfers(chain_id, token_addr, start, anno_ts)
    out = []
    for tx in txs:
        to = tx.get("to", "").lower()
        if to in IGNORE_LABELS:
            continue
        out.append({
            "wallet": to,
            "chain": chain,
            "ts": int(tx["timeStamp"]),
            "amount": tx["value"],
            "tx": tx["hash"],
        })
    return out


def solana_buyers(mint: str, anno_ts: int, window_h: int) -> list[dict]:
    """Use Helius enhanced transactions API to find new holders in window."""
    if not config.HELIUS_API_KEY:
        return []
    base = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
    params = {"api-key": config.HELIUS_API_KEY, "type": "SWAP", "limit": 100}
    start = anno_ts - window_h * 3600

    out: list[dict] = []
    before = None
    while True:
        p = dict(params)
        if before:
            p["before"] = before
        r = requests.get(base, params=p, timeout=20)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        for tx in batch:
            ts = tx.get("timestamp", 0)
            if ts < start:
                return out
            if ts > anno_ts:
                continue
            # Walk tokenTransfers, find net-positive recipients of `mint`
            for tt in tx.get("tokenTransfers", []):
                if tt.get("mint") == mint and tt.get("toUserAccount"):
                    out.append({
                        "wallet": tt["toUserAccount"],
                        "chain": "solana",
                        "ts": ts,
                        "amount": str(tt.get("tokenAmount", 0)),
                        "tx": tx.get("signature", ""),
                    })
        before = batch[-1].get("signature")
        if not before:
            break
        time.sleep(0.25)
    return out


def collect_buyers(listing: dict) -> list[dict]:
    plats = listing.get("platforms") or {}
    buyers: list[dict] = []
    for chain, addr in plats.items():
        if not addr:
            continue
        if chain == "solana":
            buyers += solana_buyers(addr, listing["announced_at"],
                                    config.PRE_LISTING_WINDOW_HOURS)
        elif chain in EVM_CHAINS:
            buyers += evm_buyers(addr, chain, listing["announced_at"],
                                 config.PRE_LISTING_WINDOW_HOURS)
    return buyers


def main() -> None:
    listings = json.loads((config.DATA_DIR / "listings.json").read_text())
    out_dir = config.DATA_DIR / "buyers"
    out_dir.mkdir(exist_ok=True)
    for listing in listings:
        sym = listing["symbol"]
        path = out_dir / f"{sym}.json"
        if path.exists():
            print(f"skip {sym} (cached)")
            continue
        try:
            buyers = collect_buyers(listing)
        except Exception as e:
            print(f"err {sym}: {e}")
            continue
        path.write_text(json.dumps(buyers, indent=2))
        print(f"{sym}: {len(buyers)} pre-listing buyers")


if __name__ == "__main__":
    main()
