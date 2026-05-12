"""Expand the seed insider wallet set by walking funding lineage.

Given a PRIMARY wallet (appears in N+ Binance pre-listing buys), we look for
other wallets that:

  (a) FUNDED the seed wallet (the parent)         — upstream of insider
  (b) Were FUNDED BY the seed wallet (the child)  — downstream of insider
  (c) Share the same FUNDING PARENT (siblings)    — co-funded cluster

Only the "first hop" funding txn is interesting — we want the wallet that
seeded this account from a CEX/bridge/mixer/another EOA. Subsequent
DEX-router-or-token transfers are excluded.

For each candidate edge we score:
  - same_funder_within_1h    : 1.0  (siblings funded near-simultaneously)
  - direct_funder_or_funded  : 0.8  (parent or child)
  - funded_pre_listing_buy   : +0.3 bonus if the wallet also appears as a
                               pre-listing buyer in any listing window
Anything >= 0.7 gets written into the DB as tier='EXPANDED'.

Output: extends data/insider_wallets.json + populates funding_edges table.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

EVM_CHAINS = {
    "ethereum": 1, "binance-smart-chain": 56, "polygon-pos": 137,
    "base": 8453, "arbitrum-one": 42161, "optimistic-ethereum": 10,
}

# Routers, DEX aggregators, and other contracts that should NOT count as
# "funding source" — they're tx counterparties, not capital sources.
NON_FUNDER_CONTRACTS = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 router
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch v5 router
    "0x10ed43c718714eb63d5aa57b78b54704e256024e",  # PancakeSwap router
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}

# Native + major stable seeds count as "real" funding events
FUNDING_ASSETS = {"ETH", "BNB", "MATIC", "USDC", "USDT", "DAI", "USDC.e", "WETH"}

# How far back to look for the seed's own funding event
LOOKBACK_DAYS = 180
SIBLING_WINDOW_S = 3600  # within 1h of seed funding = sibling


def _evm_first_inflows(chain_id: int, wallet: str, lookback_s: int) -> list[dict]:
    """Pull all inbound native + ERC-20 txs to `wallet` in lookback window.

    Returns dict-per-tx, oldest first. Filters out tokens from DEX routers
    (those are swap proceeds, not funding).
    """
    since = int(time.time()) - lookback_s
    # 1) native ETH/BNB transfers
    r1 = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "txlist",
        "address": wallet, "page": 1, "offset": 100, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    out: list[dict] = []
    for tx in (r1.get("result") or []):
        if not isinstance(tx, dict):
            continue
        if int(tx.get("timeStamp", 0)) < since:
            continue
        if tx.get("to", "").lower() != wallet.lower():
            continue
        if int(tx.get("value", "0")) == 0:
            continue
        out.append({
            "from": tx["from"].lower(),
            "asset": {1: "ETH", 56: "BNB", 137: "MATIC", 8453: "ETH",
                      42161: "ETH", 10: "ETH"}.get(chain_id, "NATIVE"),
            "amount": tx["value"],
            "tx": tx["hash"],
            "ts": int(tx["timeStamp"]),
        })
    # 2) major stables (USDC/USDT inflows)
    r2 = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "address": wallet, "page": 1, "offset": 200, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    for tx in (r2.get("result") or []):
        if not isinstance(tx, dict):
            continue
        if int(tx.get("timeStamp", 0)) < since:
            continue
        if tx.get("to", "").lower() != wallet.lower():
            continue
        sym = tx.get("tokenSymbol", "")
        if sym not in FUNDING_ASSETS:
            continue
        if tx["from"].lower() in NON_FUNDER_CONTRACTS:
            continue
        out.append({
            "from": tx["from"].lower(),
            "asset": sym,
            "amount": tx["value"],
            "tx": tx["hash"],
            "ts": int(tx["timeStamp"]),
        })
    out.sort(key=lambda x: x["ts"])
    return out


def _evm_first_outflows(chain_id: int, wallet: str, lookback_s: int) -> list[dict]:
    """Pull all native+stable outbound (this wallet funding others)."""
    since = int(time.time()) - lookback_s
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "txlist",
        "address": wallet, "page": 1, "offset": 100, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    out = []
    for tx in (r.get("result") or []):
        if not isinstance(tx, dict):
            continue
        if int(tx.get("timeStamp", 0)) < since:
            continue
        if tx.get("from", "").lower() != wallet.lower():
            continue
        if int(tx.get("value", "0")) == 0:
            continue
        to = tx["to"].lower()
        if to in NON_FUNDER_CONTRACTS:
            continue
        out.append({
            "to": to,
            "asset": "NATIVE",
            "amount": tx["value"],
            "tx": tx["hash"],
            "ts": int(tx["timeStamp"]),
        })
    return out


def _evm_siblings(chain_id: int, funder: str, anchor_ts: int) -> list[dict]:
    """Find all wallets the funder seeded within SIBLING_WINDOW_S of anchor_ts."""
    # Native outflows from the funder around the anchor time
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "txlist",
        "address": funder, "page": 1, "offset": 1000, "sort": "desc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    out = []
    for tx in (r.get("result") or []):
        if not isinstance(tx, dict):
            continue
        ts = int(tx.get("timeStamp", 0))
        if abs(ts - anchor_ts) > SIBLING_WINDOW_S:
            continue
        if tx.get("from", "").lower() != funder:
            continue
        to = tx["to"].lower()
        if to in NON_FUNDER_CONTRACTS:
            continue
        out.append({
            "wallet": to,
            "ts": ts,
            "tx": tx["hash"],
        })
    return out


def expand_seed(seed_wallet: str, seed_chain: str) -> list[dict]:
    """Return EXPANDED-tier candidates for one seed wallet."""
    chain_id = EVM_CHAINS.get(seed_chain)
    if not chain_id:
        return []  # Solana lineage walk is a separate module

    lookback = LOOKBACK_DAYS * 86400
    candidates: dict[str, dict] = {}

    # 1) Parents (who funded the seed) + siblings (other wallets funded
    # by the same parent in the same window)
    inflows = _evm_first_inflows(chain_id, seed_wallet, lookback)
    if inflows:
        # Take the first 'real' inflow as the seed's birth funding event
        first = inflows[0]
        parent = first["from"]
        candidates[parent] = {
            "wallet": parent, "edge_kind": "parent",
            "confidence": 0.8, "tx": first["tx"], "ts": first["ts"],
            "parent_wallet": seed_wallet, "chain": seed_chain,
        }
        # Persist edge
        with db.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO funding_edges"
                "(from_wallet, to_wallet, chain, asset, amount, tx, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (parent, seed_wallet, seed_chain, first["asset"],
                 first["amount"], first["tx"], first["ts"]),
            )
        # Siblings funded by the same parent within 1h
        for sib in _evm_siblings(chain_id, parent, first["ts"]):
            if sib["wallet"] == seed_wallet:
                continue
            if sib["wallet"] in candidates:
                continue
            candidates[sib["wallet"]] = {
                "wallet": sib["wallet"], "edge_kind": "sibling",
                "confidence": 1.0, "tx": sib["tx"], "ts": sib["ts"],
                "parent_wallet": seed_wallet, "chain": seed_chain,
            }
            with db.conn() as c:
                c.execute(
                    "INSERT OR IGNORE INTO funding_edges"
                    "(from_wallet, to_wallet, chain, asset, amount, tx, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (parent, sib["wallet"], seed_chain, "NATIVE",
                     "0", sib["tx"], sib["ts"]),
                )

    # 2) Children (wallets the seed funded)
    for out in _evm_first_outflows(chain_id, seed_wallet, lookback):
        ch = out["to"]
        if ch in candidates:
            continue
        candidates[ch] = {
            "wallet": ch, "edge_kind": "child",
            "confidence": 0.7, "tx": out["tx"], "ts": out["ts"],
            "parent_wallet": seed_wallet, "chain": seed_chain,
        }
        with db.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO funding_edges"
                "(from_wallet, to_wallet, chain, asset, amount, tx, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (seed_wallet, ch, seed_chain, out["asset"],
                 out["amount"], out["tx"], out["ts"]),
            )

    return list(candidates.values())


def main() -> None:
    """Iterate all PRIMARY insiders, expand, write EXPANDED tier rows."""
    db.init()
    with db.conn() as c:
        primary = c.execute(
            "SELECT wallet, chains FROM insider_wallets WHERE tier='PRIMARY'"
        ).fetchall()

    if not primary:
        print("No PRIMARY wallets in DB. Run monitor/load_insiders.py first.")
        return

    expanded_total = 0
    for row in primary:
        seed_wallet = row["wallet"]
        for chain in row["chains"].split(","):
            try:
                cands = expand_seed(seed_wallet, chain)
            except Exception as e:
                print(f"err expanding {seed_wallet[:10]} on {chain}: {e}")
                continue
            for c in cands:
                if c["confidence"] < 0.7:
                    continue
                with db.conn() as conn_:
                    conn_.execute(
                        "INSERT OR IGNORE INTO insider_wallets"
                        "(wallet, hit_count, chains, symbols, "
                        " avg_lead_time_h, notes, tier, parent_wallet, "
                        " confidence) "
                        "VALUES (?, 0, ?, '', NULL, ?, 'EXPANDED', ?, ?)",
                        (c["wallet"], chain,
                         f"{c['edge_kind']} of {seed_wallet[:10]}",
                         seed_wallet, c["confidence"]),
                    )
                expanded_total += 1
            time.sleep(0.25)
    print(f"Added {expanded_total} EXPANDED-tier wallet candidates.")


if __name__ == "__main__":
    main()
