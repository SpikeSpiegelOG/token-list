"""For a *current candidate* token, check whether its team/deployer wallets
have already paid a known FACILITATOR or BINANCE_2NDARY wallet a meaningful
stablecoin tranche. This is the on-chain equivalent of "we cut the check".

Pipeline:
  candidate_token_addr
    → team_wallets (deployer + early holders)
    → outbound stable transfers >= $50k in last 90d
    → recipients matched against insider_wallets WHERE tier IN
      ('FACILITATOR', 'BINANCE_2NDARY', 'PRIMARY')
    → return matches with hop count + amount

A match means: the team has paid someone connected to the Binance listing
machinery. Single highest-signal off-narrative input.

Usage:
    python -m qualification.payment_lineage <token_addr> <chain>
"""
from __future__ import annotations
import sys
import time
from collections import defaultdict
from typing import Any

import requests

sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402
from qualification.facilitator_finder import (  # noqa: E402
    _evm_deployer, _evm_largest_holders, _evm_stable_outflows,
    EVM_CHAINS, STABLE_SYMBOLS,
)

LOOKBACK_DAYS = 90


def check_token(token_addr: str, chain: str) -> dict[str, Any]:
    chain_id = EVM_CHAINS.get(chain)
    if not chain_id:
        return {"error": f"chain {chain} not supported here"}

    # 1. Identify team wallets
    team: set[str] = set()
    dep = _evm_deployer(chain_id, token_addr)
    if dep:
        team.add(dep)
    team.update(_evm_largest_holders(chain_id, token_addr))

    # 2. Pull recent insider_wallets WHERE tier in (PRIMARY, EXPANDED,
    #    BINANCE_2NDARY, FACILITATOR) — these are our "flagged contacts"
    with db.conn() as c:
        rows = c.execute(
            "SELECT wallet, tier, confidence, notes FROM insider_wallets "
            "WHERE tier IN ('PRIMARY','EXPANDED','BINANCE_2NDARY','FACILITATOR')"
        ).fetchall()
    flagged = {r["wallet"].lower(): {
        "tier": r["tier"], "confidence": r["confidence"], "notes": r["notes"]
    } for r in rows}

    # 3. For each team wallet, pull stable outflows and check for matches
    now = int(time.time())
    matches: list[dict[str, Any]] = []
    for tw in team:
        try:
            outs = _evm_stable_outflows(chain_id, tw, now, LOOKBACK_DAYS)
        except Exception as e:
            print(f"err team={tw[:10]}: {e}")
            continue
        for o in outs:
            recipient = o["to"]
            if recipient in flagged:
                matches.append({
                    "team_wallet": tw,
                    "recipient": recipient,
                    "recipient_tier": flagged[recipient]["tier"],
                    "recipient_confidence": flagged[recipient]["confidence"],
                    "recipient_notes": flagged[recipient]["notes"],
                    "amount_usd": o["amount_usd"],
                    "symbol": o["symbol"],
                    "ts": o["ts"],
                    "tx": o["tx"],
                })
        time.sleep(0.15)

    # 4. Score
    score = 0.0
    weight = {"PRIMARY": 1.0, "FACILITATOR": 1.0,
              "BINANCE_2NDARY": 0.7, "EXPANDED": 0.5}
    for m in matches:
        score += weight.get(m["recipient_tier"], 0.3) * \
                 min(2.0, m["amount_usd"] / 100_000)

    return {
        "token_addr": token_addr,
        "chain": chain,
        "team_wallets_checked": list(team),
        "matches": matches,
        "score": round(score, 2),
        "verdict": (
            "HIGH" if score >= 1.5 else
            "MEDIUM" if score >= 0.7 else
            "LOW"
        ),
    }


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python -m qualification.payment_lineage <token_addr> <chain>")
        return
    result = check_token(sys.argv[1], sys.argv[2])
    import json as _json
    print(_json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
