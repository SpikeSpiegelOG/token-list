"""Given the insider wallet list (data/insider_wallets.json), find what they
are accumulating right now and score by insider-buy convergence.

Score per token:
  insider_buyers      # distinct insider wallets that bought it in window
  total_usd_inflow    # rough USD value of insider inflows
  oldest_insider_buy  # how long the cluster has been accumulating
  median_lead_time    # median historical lead time of these wallets

Higher convergence + earlier accumulation = stronger candidate.

Output: data/candidates.json sorted by `insider_buyers` desc.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from statistics import median

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

EVM_CHAINS = {
    "ethereum": 1, "binance-smart-chain": 56, "polygon-pos": 137,
    "base": 8453, "arbitrum-one": 42161, "optimistic-ethereum": 10,
}

LOOKBACK_DAYS = 14


def evm_recent_token_inflows(chain_id: int, wallet: str, since_ts: int) -> list[dict]:
    """All ERC-20 inflows to `wallet` since `since_ts`."""
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "address": wallet, "startblock": 0, "endblock": 99999999,
        "page": 1, "offset": 1000, "sort": "desc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=20).json()
    res = r.get("result")
    if not isinstance(res, list):
        return []
    out = []
    for tx in res:
        ts = int(tx["timeStamp"])
        if ts < since_ts:
            break
        if tx["to"].lower() != wallet.lower():
            continue
        out.append({
            "token": tx["contractAddress"].lower(),
            "symbol": tx["tokenSymbol"],
            "ts": ts,
            "amount": tx["value"],
            "decimals": int(tx.get("tokenDecimal", 18) or 18),
        })
    return out


def helius_recent_token_inflows(wallet: str, since_ts: int) -> list[dict]:
    """Solana inflows for `wallet` since `since_ts` via Helius enhanced API."""
    if not config.HELIUS_API_KEY:
        return []
    base = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
    params = {"api-key": config.HELIUS_API_KEY, "limit": 100}
    out, before = [], None
    for _ in range(5):  # cap pages
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
            if ts < since_ts:
                return out
            for tt in tx.get("tokenTransfers", []):
                if tt.get("toUserAccount") == wallet:
                    out.append({
                        "token": tt.get("mint"),
                        "symbol": tt.get("mint", "")[:6],
                        "ts": ts,
                        "amount": str(tt.get("tokenAmount", 0)),
                        "decimals": 0,
                    })
        before = batch[-1].get("signature")
        if not before:
            break
        time.sleep(0.2)
    return out


def main() -> None:
    insiders = json.loads((config.DATA_DIR / "insider_wallets.json").read_text())
    since_ts = int(time.time()) - LOOKBACK_DAYS * 86400

    # token_addr → { insider_buyers: set, buys: [...] }
    by_token: dict[str, dict] = defaultdict(
        lambda: {"insider_buyers": set(), "buys": [], "symbol": None, "chains": set()}
    )

    for ins in insiders:
        wallet = ins["wallet"]
        chains = ins["chains"]
        inflows = []
        for chain in chains:
            if chain == "solana":
                inflows += helius_recent_token_inflows(wallet, since_ts)
            elif chain in EVM_CHAINS:
                inflows += evm_recent_token_inflows(EVM_CHAINS[chain], wallet, since_ts)
        for f in inflows:
            tok = f["token"]
            if not tok:
                continue
            entry = by_token[tok]
            entry["symbol"] = f["symbol"]
            entry["insider_buyers"].add(wallet)
            entry["chains"].add("solana" if f["decimals"] == 0 else "evm")
            entry["buys"].append({
                "wallet": wallet,
                "ts": f["ts"],
                "amount": f["amount"],
                "wallet_hit_count": ins["hit_count"],
            })

    rows = []
    for tok, e in by_token.items():
        if len(e["insider_buyers"]) < 2:
            continue  # need at least 2 insiders converging
        ts_list = [b["ts"] for b in e["buys"]]
        rows.append({
            "token": tok,
            "symbol": e["symbol"],
            "insider_buyers": len(e["insider_buyers"]),
            "wallets": sorted(e["insider_buyers"]),
            "chains": sorted(e["chains"]),
            "first_insider_buy": min(ts_list),
            "last_insider_buy": max(ts_list),
            "buy_count": len(e["buys"]),
            "median_buyer_strength": median(b["wallet_hit_count"] for b in e["buys"]),
        })
    rows.sort(key=lambda r: (-r["insider_buyers"], -r["median_buyer_strength"]))

    out = config.DATA_DIR / "candidates.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {len(rows)} candidate tokens → {out}")
    for r in rows[:25]:
        print(f"  {r['symbol'] or r['token'][:10]:>10}  "
              f"insiders={r['insider_buyers']:2d}  "
              f"buys={r['buy_count']:3d}  "
              f"med_strength={r['median_buyer_strength']}")


if __name__ == "__main__":
    main()
