"""Find wallets that withdraw from Binance hot wallets and then immediately
exhibit insider-like behavior (sniping memecoins on DEX).

Hypothesis: when a Binance employee or counterparty front-runs a listing,
they typically:
  1. Withdraw capital from Binance to a fresh wallet
  2. Use the fresh wallet to snipe the about-to-be-listed memecoin on DEX
  3. Sell back to Binance for fiat after the listing pump

This module pulls recent withdrawal recipients from each Binance hot wallet,
filters to those exhibiting the post-withdrawal sniper pattern, and writes
them to insider_wallets with tier='BINANCE_2NDARY'.

Scoring per candidate:
  +0.4  if wallet is < 30 days old at time of Binance withdrawal
  +0.3  if first DEX swap occurred within 24h of withdrawal
  +0.2  if it received from Binance >= 3 times in last 60d (recurring)
  +0.2  if first DEX trade was a memecoin (not blue chip)
  +0.3  if wallet appears in any historical pre-listing buyer set
Anything >= 0.6 is written.

Tunables:
  WITHDRAWAL_LOOKBACK_DAYS    how far back to scan Binance outflows
  SNIPER_WINDOW_HOURS         time-to-DEX-swap that counts as "immediate"
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from pathlib import Path

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402
from monitor.wallet_watcher import BINANCE_HOTS  # noqa: E402

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

EVM_CHAINS = {
    "ethereum": 1, "binance-smart-chain": 56, "polygon-pos": 137,
    "base": 8453, "arbitrum-one": 42161, "optimistic-ethereum": 10,
}

DEX_ROUTERS = {
    # Uniswap, 1inch, 0x, Sushi, Pancake, Jupiter (sol), etc.
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uni V3 universal
    "0x1111111254eeb25477b68fb85ed929f73a960582",
    "0x10ed43c718714eb63d5aa57b78b54704e256024e",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",  # Sushi
}

WITHDRAWAL_LOOKBACK_DAYS = 30
SNIPER_WINDOW_HOURS = 24
RECURRING_THRESHOLD = 3
RECURRING_WINDOW_DAYS = 60
BLUE_CHIPS = {"WETH", "WBTC", "USDT", "USDC", "DAI", "LINK", "UNI"}


def _binance_outflows(chain_id: int, hot_addr: str, lookback_days: int) -> list[dict]:
    """Pull outbound native + ERC-20 from a Binance hot wallet."""
    since = int(time.time()) - lookback_days * 86400
    out: list[dict] = []
    page = 1
    while True:
        r = requests.get(ETHERSCAN_V2, params={
            "chainid": chain_id, "module": "account", "action": "txlist",
            "address": hot_addr, "page": page, "offset": 1000, "sort": "desc",
            "apikey": config.ETHERSCAN_API_KEY,
        }, timeout=20).json()
        batch = r.get("result")
        if not isinstance(batch, list) or not batch:
            break
        stop = False
        for tx in batch:
            ts = int(tx.get("timeStamp", 0))
            if ts < since:
                stop = True
                break
            if tx.get("from", "").lower() != hot_addr:
                continue
            if int(tx.get("value", 0)) == 0:
                continue
            to = tx["to"].lower()
            if to in DEX_ROUTERS:
                continue
            out.append({
                "recipient": to,
                "tx": tx["hash"],
                "ts": ts,
                "amount": tx["value"],
            })
        if stop or len(batch) < 1000:
            break
        page += 1
        time.sleep(0.25)
    return out


def _wallet_age_days(chain_id: int, wallet: str) -> int:
    """Returns days since first ever tx for the wallet."""
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "txlist",
        "address": wallet, "page": 1, "offset": 1, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    res = r.get("result")
    if not isinstance(res, list) or not res:
        return 9999
    first_ts = int(res[0].get("timeStamp", 0))
    return (int(time.time()) - first_ts) // 86400


def _first_dex_swap_after(chain_id: int, wallet: str, after_ts: int) -> dict | None:
    """Find the first ERC-20 inflow from a DEX router after `after_ts`."""
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "address": wallet, "page": 1, "offset": 100, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    for tx in (r.get("result") or []):
        if not isinstance(tx, dict):
            continue
        ts = int(tx.get("timeStamp", 0))
        if ts < after_ts:
            continue
        if tx.get("to", "").lower() != wallet.lower():
            continue
        frm = tx.get("from", "").lower()
        if frm in DEX_ROUTERS or "router" in tx.get("from", "").lower():
            return {
                "ts": ts,
                "symbol": tx.get("tokenSymbol", ""),
                "token": tx.get("contractAddress", "").lower(),
                "tx": tx["hash"],
            }
    return None


def _binance_withdrawal_count(chain_id: int, wallet: str, hot_addrs: set,
                              lookback_days: int) -> int:
    """Count distinct Binance withdrawals to wallet in window."""
    since = int(time.time()) - lookback_days * 86400
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "txlist",
        "address": wallet, "page": 1, "offset": 1000, "sort": "desc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    n = 0
    for tx in (r.get("result") or []):
        if not isinstance(tx, dict):
            continue
        if int(tx.get("timeStamp", 0)) < since:
            break
        if tx.get("to", "").lower() != wallet.lower():
            continue
        if tx.get("from", "").lower() in hot_addrs:
            n += 1
    return n


def _is_in_prelisting_buyers(wallet: str) -> bool:
    """Check if wallet exists in any data/buyers/<SYMBOL>.json."""
    buyers_dir = config.DATA_DIR / "buyers"
    if not buyers_dir.exists():
        return False
    w = wallet.lower()
    for p in buyers_dir.glob("*.json"):
        try:
            for b in json.loads(p.read_text()):
                if b.get("wallet", "").lower() == w:
                    return True
        except Exception:
            pass
    return False


def score_secondary(chain: str, hot_addr: str, recipient: str,
                    withdraw_ts: int) -> tuple[float, dict]:
    chain_id = EVM_CHAINS[chain]
    score = 0.0
    detail: dict = {"chain": chain, "hot_wallet": hot_addr}

    age_days = _wallet_age_days(chain_id, recipient)
    detail["age_days_at_withdrawal"] = age_days
    if age_days < 30:
        score += 0.4

    first_swap = _first_dex_swap_after(chain_id, recipient, withdraw_ts)
    if first_swap:
        dt_h = (first_swap["ts"] - withdraw_ts) / 3600
        detail["time_to_first_swap_h"] = round(dt_h, 2)
        detail["first_swap_token"] = first_swap["symbol"]
        if dt_h <= SNIPER_WINDOW_HOURS:
            score += 0.3
        if first_swap["symbol"] not in BLUE_CHIPS and first_swap["symbol"]:
            score += 0.2

    hot_set = {a.lower() for a in BINANCE_HOTS.keys()}
    n_with = _binance_withdrawal_count(chain_id, recipient, hot_set,
                                       RECURRING_WINDOW_DAYS)
    detail["binance_withdrawals_60d"] = n_with
    if n_with >= RECURRING_THRESHOLD:
        score += 0.2

    if _is_in_prelisting_buyers(recipient):
        score += 0.3
        detail["historical_prelisting_buyer"] = True

    return score, detail


def scan(chain: str) -> int:
    """Scan one EVM chain's Binance hot wallets. Returns rows added."""
    chain_id = EVM_CHAINS[chain]
    # Pick hot wallets that look like they're on EVM (0x prefix)
    hot_addrs = [a for a in BINANCE_HOTS.keys() if a.startswith("0x")]

    seen_recipients: set[str] = set()
    added = 0

    for hot in hot_addrs:
        try:
            outflows = _binance_outflows(chain_id, hot, WITHDRAWAL_LOOKBACK_DAYS)
        except Exception as e:
            print(f"err pulling outflows for {hot[:10]} on {chain}: {e}")
            continue
        print(f"[{chain}] {BINANCE_HOTS[hot]}: {len(outflows)} outflows")

        # Process one outflow per recipient (most recent — already desc order)
        for o in outflows:
            r = o["recipient"]
            if r in seen_recipients:
                continue
            seen_recipients.add(r)
            try:
                score, detail = score_secondary(chain, hot, r, o["ts"])
            except Exception as e:
                print(f"  err scoring {r[:10]}: {e}")
                continue
            if score < 0.6:
                continue
            with db.conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO insider_wallets"
                    "(wallet, hit_count, chains, symbols, avg_lead_time_h, "
                    " notes, tier, funding_source, confidence) "
                    "VALUES (?, 0, ?, '', NULL, ?, 'BINANCE_2NDARY', ?, ?)",
                    (r, chain, json.dumps(detail), hot, round(score, 2)),
                )
            added += 1
            time.sleep(0.15)
    return added


def main() -> None:
    db.init()
    total = 0
    for chain in ("ethereum", "binance-smart-chain", "base", "arbitrum-one"):
        try:
            total += scan(chain)
        except Exception as e:
            print(f"err on {chain}: {e}")
    print(f"Added {total} BINANCE_2NDARY wallets total.")


if __name__ == "__main__":
    main()
