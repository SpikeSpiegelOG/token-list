"""Cluster pre-listing buyers across all listings to find recurring wallets.

A wallet that shows up in the pre-listing window of N or more separate
Binance memecoin listings is by definition either (a) extremely lucky, or
(b) part of an insider/leak network. Statistically (b) dominates above N=3.

We score each wallet by:
  - hit_count: # of listings it appears in
  - avg_lead_time_h: average hours before announcement they bought
  - chains_seen: how many chains
  - first_seen / last_seen
  - rough_realized_pnl: sum of (announce_day_price - buy_price) * amount
    (skipped here — needs price API; see candidates/score_tokens.py)

Output: data/insider_wallets.json sorted by hit_count desc.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def main() -> None:
    listings = {l["symbol"]: l for l in
                json.loads((config.DATA_DIR / "listings.json").read_text())}
    buyers_dir = config.DATA_DIR / "buyers"

    by_wallet: dict[str, dict] = defaultdict(lambda: {
        "wallet": None, "chains": set(), "listings": [],
        "first_seen": None, "last_seen": None,
    })

    for path in buyers_dir.glob("*.json"):
        sym = path.stem
        anno_ts = listings.get(sym, {}).get("announced_at", 0)
        for b in json.loads(path.read_text()):
            w = b["wallet"].lower() if b["chain"] != "solana" else b["wallet"]
            entry = by_wallet[w]
            entry["wallet"] = w
            entry["chains"].add(b["chain"])
            entry["listings"].append({
                "symbol": sym,
                "lead_time_h": round((anno_ts - b["ts"]) / 3600, 2),
                "tx": b["tx"],
                "amount": b["amount"],
            })
            entry["first_seen"] = min(entry["first_seen"] or b["ts"], b["ts"])
            entry["last_seen"] = max(entry["last_seen"] or b["ts"], b["ts"])

    rows = []
    for w, e in by_wallet.items():
        symbols = sorted({l["symbol"] for l in e["listings"]})
        if len(symbols) < config.MIN_LISTINGS_FOR_INSIDER:
            continue
        avg_lead = sum(l["lead_time_h"] for l in e["listings"]) / len(e["listings"])
        rows.append({
            "wallet": w,
            "hit_count": len(symbols),
            "symbols": symbols,
            "chains": sorted(e["chains"]),
            "avg_lead_time_h": round(avg_lead, 2),
            "first_seen": e["first_seen"],
            "last_seen": e["last_seen"],
            "trades": e["listings"],
        })
    rows.sort(key=lambda r: (-r["hit_count"], -r["avg_lead_time_h"]))

    out = config.DATA_DIR / "insider_wallets.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {len(rows)} insider wallets → {out}")
    for r in rows[:20]:
        print(f"  {r['wallet'][:14]}…  {r['hit_count']} hits  "
              f"avg_lead={r['avg_lead_time_h']}h  chains={','.join(r['chains'])}  "
              f"symbols={','.join(r['symbols'])}")


if __name__ == "__main__":
    main()
