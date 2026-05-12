"""Poll all insider wallets for new transfers. Two events of special interest:

1. NEW BUY  — wallet receives a token via DEX swap. If 2+ insider wallets buy
   the same token in the same window → emit ENTRY alert.

2. BINANCE DEPOSIT — wallet sends a token to a known Binance hot wallet.
   Near-certain "dump incoming" signal → emit URGENT_EXIT alert.

Run as a long-lived loop; cadence configurable. Uses Etherscan V2 + Helius.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from typing import Iterable

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

# Known Binance hot wallets (extend in data/labels/binance_hotwallets.json)
BINANCE_HOTS = {
    # EVM
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance: Hot Wallet 14",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance: Hot Wallet 20",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance: Hot Wallet 15",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance: Hot Wallet 16",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance: Hot Wallet 7",
    "0x564286362092d8e7936f0549571a803b203aaced": "Binance: Hot Wallet 18",
    "0x9696f59e4d72e237be84ffd425dcad154bf96976": "Binance: Hot Wallet 3",
    # Solana
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance: Solana 1",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance: Solana 2",
}

POLL_INTERVAL = 60  # seconds
CONVERGENCE_WINDOW = 6 * 3600  # within last 6h, 2+ insider buys → ENTRY


def _evm_recent_tx(chain_id: int, wallet: str, since_ts: int) -> list[dict]:
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "address": wallet, "page": 1, "offset": 100, "sort": "desc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    res = r.get("result")
    if not isinstance(res, list):
        return []
    out = []
    for tx in res:
        if int(tx["timeStamp"]) < since_ts:
            break
        out.append(tx)
    return out


def _helius_recent_tx(wallet: str, since_ts: int) -> list[dict]:
    if not config.HELIUS_API_KEY:
        return []
    base = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
    r = requests.get(base, params={"api-key": config.HELIUS_API_KEY, "limit": 50},
                     timeout=15)
    if r.status_code != 200:
        return []
    return [t for t in r.json() if t.get("timestamp", 0) >= since_ts]


def process_evm_tx(wallet: str, chain: str, tx: dict) -> None:
    ts = int(tx["timeStamp"])
    frm = tx["from"].lower()
    to = tx["to"].lower()
    direction = "in" if to == wallet.lower() else "out"
    counterparty = frm if direction == "in" else to
    label = BINANCE_HOTS.get(counterparty, "")
    with db.conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO wallet_events"
            "(wallet, chain, direction, counterparty, counterparty_label, "
            " token_addr, token_symbol, amount, tx, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (wallet, chain, direction, counterparty, label,
             tx["contractAddress"].lower(), tx["tokenSymbol"], tx["value"],
             tx["hash"], ts),
        )
    if direction == "out" and label:
        db.add_alert(
            severity="URGENT_EXIT", kind="binance_deposit", subject=tx["tokenSymbol"],
            message=f"{wallet[:10]}… sent {tx['tokenSymbol']} to {label}",
            payload=json.dumps({"tx": tx["hash"], "chain": chain}),
        )


def process_solana_tx(wallet: str, tx: dict) -> None:
    ts = tx.get("timestamp", 0)
    sig = tx.get("signature", "")
    for tt in tx.get("tokenTransfers", []):
        frm = tt.get("fromUserAccount") or ""
        to = tt.get("toUserAccount") or ""
        direction = "in" if to == wallet else ("out" if frm == wallet else None)
        if not direction:
            continue
        counterparty = frm if direction == "in" else to
        label = BINANCE_HOTS.get(counterparty, "")
        with db.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO wallet_events"
                "(wallet, chain, direction, counterparty, counterparty_label, "
                " token_addr, token_symbol, amount, tx, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (wallet, "solana", direction, counterparty, label,
                 tt.get("mint", ""), tt.get("mint", "")[:6],
                 str(tt.get("tokenAmount", 0)), sig, ts),
            )
        if direction == "out" and label:
            db.add_alert(
                severity="URGENT_EXIT", kind="binance_deposit",
                subject=tt.get("mint", "")[:8],
                message=f"{wallet[:10]}… sent SPL token to {label}",
                payload=json.dumps({"tx": sig, "mint": tt.get("mint")}),
            )


TIER_WEIGHT = {"PRIMARY": 1.0, "EXPANDED": 0.6, "BINANCE_2NDARY": 0.5}


def detect_convergence() -> None:
    """Tier-weighted convergence: PRIMARY hits count fully, EXPANDED 0.6×,
    BINANCE_2NDARY 0.5×. ENTRY fires when weighted score >= 2.0 (≈ 2 primaries
    or 3 expandeds or 4 secondaries) in the window. Records wallet tiers in
    the payload for inspection.
    """
    cutoff = int(time.time()) - CONVERGENCE_WINDOW
    with db.conn() as c:
        rows = c.execute(
            "SELECT we.token_addr, we.token_symbol, we.wallet, iw.tier "
            "FROM wallet_events we "
            "JOIN insider_wallets iw ON iw.wallet = we.wallet "
            "WHERE we.direction='in' AND we.ts >= ?",
            (cutoff,),
        ).fetchall()

    by_token: dict[str, dict] = defaultdict(
        lambda: {"symbol": "", "wallets": [], "score": 0.0, "tiers": []}
    )
    for r in rows:
        entry = by_token[r["token_addr"]]
        entry["symbol"] = r["token_symbol"]
        if r["wallet"] in [w for w, _ in zip(entry["wallets"], entry["tiers"])]:
            continue  # dedupe per-wallet per-token in window
        entry["wallets"].append(r["wallet"])
        entry["tiers"].append(r["tier"] or "PRIMARY")
        entry["score"] += TIER_WEIGHT.get(r["tier"] or "PRIMARY", 0.5)

    for token_addr, e in by_token.items():
        if e["score"] < 2.0:
            continue
        with db.conn() as c:
            existing = c.execute(
                "SELECT id FROM alerts WHERE kind='cluster_buy' "
                "AND subject=? AND ts >= ?",
                (e["symbol"], cutoff),
            ).fetchone()
        if existing:
            continue
        tier_breakdown = {t: e["tiers"].count(t) for t in set(e["tiers"])}
        db.add_alert(
            severity="ENTRY", kind="cluster_buy", subject=e["symbol"],
            message=(f"{e['symbol']}: weighted score {e['score']:.1f} from "
                     f"{len(e['wallets'])} wallets — "
                     f"{', '.join(f'{n}× {t}' for t, n in tier_breakdown.items())}"),
            payload=json.dumps({
                "token_addr": token_addr,
                "score": e["score"],
                "wallets": e["wallets"],
                "tiers": e["tiers"],
            }),
        )


def loop() -> None:
    db.init()
    while True:
        with db.conn() as c:
            wallets = c.execute(
                "SELECT wallet, chains FROM insider_wallets"
            ).fetchall()
        since = int(time.time()) - 24 * 3600
        for w in wallets:
            chains = w["chains"].split(",")
            for chain in chains:
                try:
                    if chain == "solana":
                        for tx in _helius_recent_tx(w["wallet"], since):
                            process_solana_tx(w["wallet"], tx)
                    elif chain in EVM_CHAINS:
                        for tx in _evm_recent_tx(EVM_CHAINS[chain], w["wallet"], since):
                            process_evm_tx(w["wallet"], chain, tx)
                except Exception as e:
                    print(f"err {w['wallet'][:10]} {chain}: {e}")
                time.sleep(0.2)  # rate limit
        detect_convergence()
        print(f"poll done; sleeping {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    loop()
