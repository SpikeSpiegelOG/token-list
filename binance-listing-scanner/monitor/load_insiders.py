"""Load data/insider_wallets.json into the SQLite DB so the watcher
can poll them and the dashboard can render them.
"""
from __future__ import annotations
import json

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402


def main() -> None:
    db.init()
    path = config.DATA_DIR / "insider_wallets.json"
    if not path.exists():
        print(f"No {path} — run scanner first.")
        return
    rows = json.loads(path.read_text())
    with db.conn() as c:
        for r in rows:
            c.execute(
                "INSERT OR REPLACE INTO insider_wallets"
                "(wallet, hit_count, chains, symbols, avg_lead_time_h, "
                " notes, tier, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, 'PRIMARY', 1.0)",
                (r["wallet"], r["hit_count"], ",".join(r["chains"]),
                 ",".join(r["symbols"]), r.get("avg_lead_time_h"), ""),
            )
    print(f"Loaded {len(rows)} insider wallets into DB")


if __name__ == "__main__":
    main()
