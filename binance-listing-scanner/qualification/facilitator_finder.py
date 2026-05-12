"""Find "listing facilitator" wallets — operators who repeatedly receive
$50K–$500K USDC/USDT tranches from many different memecoin team/deployer
wallets in the days/weeks before those tokens get listed.

The ACT1 story claims a "$100k fat check" was paid to get on Binance.
On-chain, this archetype looks like:

  team_wallet_A  ──$100k USDC──┐
  team_wallet_B  ──$120k USDC──┼──> FACILITATOR
  team_wallet_C  ──$80k  USDC──┘    │
                                    ├──> Binance hot deposits
                                    └──> downstream consolidator wallets

We discover facilitators by working backwards:
  1. Take every listing in data/listings.json
  2. For each token, find the *deployer* / largest pre-launch holder wallet
  3. Pull that wallet's outbound stablecoin transfers in the 60 days
     before the listing announcement
  4. Group recipients across all listings — wallets that received
     50K+ stablecoin from >=3 distinct team wallets are facilitators

Output: data/facilitators.json + insider_wallets rows with tier='FACILITATOR'.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from typing import Any

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402
from qualification import solana_helpers  # noqa: E402

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

EVM_CHAINS = {
    "ethereum": 1, "binance-smart-chain": 56, "polygon-pos": 137,
    "base": 8453, "arbitrum-one": 42161, "optimistic-ethereum": 10,
}

STABLE_SYMBOLS = {"USDC", "USDT", "DAI", "USDC.e", "BUSD", "FDUSD"}

# Minimum tranche size to count as a "facilitator payment" (USD)
MIN_TRANCHE_USD = 50_000
# How many distinct team wallets must pay one wallet for it to qualify
MIN_DISTINCT_PAYERS = 3
# Window before announcement to consider payments suspicious
PAYMENT_WINDOW_DAYS = 60

# Known DEX/router/CEX exclusions — these receive stables from teams for
# legit reasons (liquidity provisioning, listing fees on bona fide exchanges).
EXCLUDE_RECIPIENTS = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 router
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch
    "0x10ed43c718714eb63d5aa57b78b54704e256024e",  # PancakeSwap
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance 14
    "0xf977814e90da44bfa03b6295a0616a897441acec",  # Binance 20
}


def _evm_deployer(chain_id: int, token_addr: str) -> str | None:
    """Get contract creator via Etherscan V2."""
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "contract", "action": "getcontractcreation",
        "contractaddresses": token_addr, "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    res = r.get("result")
    if isinstance(res, list) and res:
        return res[0].get("contractCreator", "").lower()
    return None


def _is_likely_pool(chain_id: int, candidate: str, token_addr: str) -> bool:
    """A pool address receives the token from many distinct senders and is
    typically created in the first hour of the token's life. Heuristic:
    if >50% of the candidate's interactions are with this single token, it's
    a pool, not a team wallet.
    """
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "address": candidate, "page": 1, "offset": 100, "sort": "desc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    res = r.get("result")
    if not isinstance(res, list) or len(res) < 10:
        return False
    same_token = sum(
        1 for t in res if t.get("contractAddress", "").lower() == token_addr.lower()
    )
    return same_token / len(res) >= 0.5


def _evm_largest_holders(chain_id: int, token_addr: str) -> list[str]:
    """Pull early supply receivers — likely team/insider wallets pre-launch.
    Filters out pool/LP contracts via behavioral heuristic.
    """
    r = requests.get(ETHERSCAN_V2, params={
        "chainid": chain_id, "module": "account", "action": "tokentx",
        "contractaddress": token_addr, "page": 1, "offset": 100, "sort": "asc",
        "apikey": config.ETHERSCAN_API_KEY,
    }, timeout=15).json()
    res = r.get("result")
    if not isinstance(res, list):
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for tx in res[:40]:
        to = tx.get("to", "").lower()
        if to and to not in seen and to not in EXCLUDE_RECIPIENTS:
            seen.add(to)
            candidates.append(to)
    # Filter out DEX pool addresses
    holders = []
    for c in candidates[:15]:  # cap the pool-check API spend
        try:
            if not _is_likely_pool(chain_id, c, token_addr):
                holders.append(c)
        except Exception:
            holders.append(c)
        time.sleep(0.1)
    return holders


def _evm_stable_outflows(chain_id: int, wallet: str,
                        before_ts: int, window_days: int) -> list[dict]:
    """Pull stable outflows (USDC/USDT/etc) from a wallet in the window.

    Paginates Etherscan results in 1000-row pages until we reach the
    `since` cutoff or run out of results.
    """
    since = before_ts - window_days * 86400
    out: list[dict] = []
    page = 1
    while page <= 10:  # cap to ~10k txns per wallet
        r = requests.get(ETHERSCAN_V2, params={
            "chainid": chain_id, "module": "account", "action": "tokentx",
            "address": wallet, "page": page, "offset": 1000, "sort": "desc",
            "apikey": config.ETHERSCAN_API_KEY,
        }, timeout=20).json()
        res = r.get("result")
        if not isinstance(res, list) or not res:
            break
        stop = False
        for tx in res:
            if not isinstance(tx, dict):
                continue
            ts = int(tx.get("timeStamp", 0))
            if ts < since:
                stop = True
                break
            if ts > before_ts:
                continue
            if tx.get("from", "").lower() != wallet.lower():
                continue
            sym = tx.get("tokenSymbol", "")
            if sym not in STABLE_SYMBOLS:
                continue
            decimals = int(tx.get("tokenDecimal", 6) or 6)
            usd_amount = int(tx["value"]) / (10 ** decimals)
            if usd_amount < MIN_TRANCHE_USD:
                continue
            to = tx.get("to", "").lower()
            if to in EXCLUDE_RECIPIENTS:
                continue
            out.append({
                "to": to,
                "amount_usd": usd_amount,
                "symbol": sym,
                "ts": ts,
                "tx": tx["hash"],
                "from_team": wallet.lower(),
            })
        if stop or len(res) < 1000:
            break
        page += 1
        time.sleep(0.25)
    return out


def scan(listings: list[dict]) -> dict:
    """For each listing, find team wallets and their stable outflows.
    Aggregate recipients across all listings.
    """
    recipient_payments: dict[str, list[dict]] = defaultdict(list)

    for listing in listings:
        sym = listing["symbol"]
        anno_ts = listing["announced_at"]
        for chain, addr in (listing.get("platforms") or {}).items():
            if not addr:
                continue
            team_wallets: set[str] = set()
            # Resolve team wallets per chain
            if chain == "solana":
                try:
                    dep = solana_helpers.solana_deployer(addr)
                    if dep:
                        team_wallets.add(dep)
                    team_wallets.update(solana_helpers.solana_team_holders(addr))
                except Exception as e:
                    print(f"    err sol team {sym}: {e}")
                    continue
            elif chain in EVM_CHAINS:
                chain_id = EVM_CHAINS[chain]
                dep = _evm_deployer(chain_id, addr)
                if dep:
                    team_wallets.add(dep)
                team_wallets.update(_evm_largest_holders(chain_id, addr))
            else:
                continue

            print(f"  {sym} ({chain}): {len(team_wallets)} team-candidate wallets")
            for tw in team_wallets:
                try:
                    if chain == "solana":
                        outs = solana_helpers.solana_stable_outflows(
                            tw, anno_ts, PAYMENT_WINDOW_DAYS
                        )
                    else:
                        outs = _evm_stable_outflows(
                            EVM_CHAINS[chain], tw, anno_ts, PAYMENT_WINDOW_DAYS
                        )
                except Exception as e:
                    print(f"    err pulling outflows {tw[:10]}: {e}")
                    continue
                for o in outs:
                    o["listing_symbol"] = sym
                    o["chain"] = chain
                    recipient_payments[o["to"]].append(o)
                time.sleep(0.15)
    return recipient_payments


def main() -> None:
    db.init()
    listings_path = config.DATA_DIR / "listings.json"
    if not listings_path.exists():
        print("Run scanner.binance_listings first.")
        return
    listings = json.loads(listings_path.read_text())

    print(f"Scanning team outflows across {len(listings)} listings…")
    rec = scan(listings)

    facilitators = []
    for recipient, payments in rec.items():
        distinct_payers = {p["from_team"] for p in payments}
        if len(distinct_payers) < MIN_DISTINCT_PAYERS:
            continue
        distinct_listings = {p["listing_symbol"] for p in payments}
        chains_seen = sorted({p["chain"] for p in payments})
        total_usd = sum(p["amount_usd"] for p in payments)
        facilitators.append({
            "wallet": recipient,
            "distinct_payers": len(distinct_payers),
            "distinct_listings": sorted(distinct_listings),
            "chains": chains_seen,
            "payment_count": len(payments),
            "total_usd_received": round(total_usd, 2),
            "payments": payments,
        })

    facilitators.sort(key=lambda f: -f["distinct_payers"])

    out = config.DATA_DIR / "facilitators.json"
    out.write_text(json.dumps(facilitators, indent=2))
    print(f"Wrote {len(facilitators)} facilitators → {out}")

    # Push to insider_wallets table as FACILITATOR tier
    with db.conn() as c:
        for f in facilitators:
            notes = (f"received ${f['total_usd_received']:,.0f} from "
                     f"{f['distinct_payers']} distinct team wallets across "
                     f"listings: {', '.join(f['distinct_listings'][:8])}")
            confidence = min(1.0, 0.3 + 0.15 * f["distinct_payers"])
            c.execute(
                "INSERT OR REPLACE INTO insider_wallets"
                "(wallet, hit_count, chains, symbols, avg_lead_time_h, "
                " notes, tier, confidence) "
                "VALUES (?, ?, ?, ?, NULL, ?, 'FACILITATOR', ?)",
                (f["wallet"], f["distinct_payers"], ",".join(f["chains"]),
                 ",".join(f["distinct_listings"]), notes, confidence),
            )
    print(f"Loaded {len(facilitators)} FACILITATOR wallets to DB")

    for f in facilitators[:15]:
        print(f"  {f['wallet'][:14]}…  "
              f"{f['distinct_payers']} payers  "
              f"${f['total_usd_received']:>12,.0f}  "
              f"{','.join(f['distinct_listings'][:5])}")


if __name__ == "__main__":
    main()
