"""Local FastAPI dashboard at http://localhost:8000.

Surfaces:
  - Live alert feed (URGENT_EXIT, ENTRY, WATCH, INFO)
  - Insider wallet table with click-through to wallet activity
  - Recent Binance announcements
  - Recent TG messages (filtered to those with contract addresses)

Single-process, single-SQLite-file. Run with:
    uvicorn monitor.dashboard:app --reload --port 8000
"""
from __future__ import annotations
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402

app = FastAPI(title="Binance Listing Scanner")

PAGE = """
<!doctype html>
<html><head><title>Binance Listing Scanner</title>
<meta http-equiv="refresh" content="10">
<style>
  body { font-family: ui-monospace, monospace; background:#0c0c0c; color:#ddd;
         margin: 0; padding: 18px; font-size: 13px; }
  h1 { color: #ffb500; margin: 0 0 12px; }
  h2 { color: #6cf; margin: 24px 0 6px; border-bottom: 1px solid #333; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; }
  td, th { padding: 4px 8px; text-align: left; border-bottom: 1px solid #1f1f1f; }
  th { color: #888; font-weight: normal; }
  .URGENT_EXIT { color: #f55; font-weight: bold; }
  .ENTRY { color: #4f4; font-weight: bold; }
  .WATCH { color: #fc4; }
  .INFO { color: #6cf; }
  .PRIMARY { color: #4f4; }
  .EXPANDED { color: #fc4; }
  .BINANCE_2NDARY { color: #f9f; }
  .small { color: #666; font-size: 11px; }
  a { color: #6cf; text-decoration: none; }
</style></head><body>
<h1>Binance Listing Scanner — local dashboard</h1>
<p class="small">Refreshes every 10s. Data path: {db_path}</p>

<h2>Live alerts (last 100)</h2>
<table>
<tr><th>when</th><th>severity</th><th>kind</th><th>subject</th><th>message</th></tr>
{alerts}
</table>

<h2>Insider wallets — tier breakdown ({n_wallets} total: {n_primary} P / {n_expanded} E / {n_secondary} B2)</h2>
<p class="small">
  <b style="color:#4f4">PRIMARY</b>  — appears in ≥{min_listings} historical pre-listing windows<br>
  <b style="color:#fc4">EXPANDED</b> — linked to a PRIMARY via funding lineage (parent/child/sibling)<br>
  <b style="color:#f9f">BINANCE_2NDARY</b> — wallet funded from a Binance hot wallet + post-withdrawal sniper behavior
</p>
<table>
<tr><th>tier</th><th>wallet</th><th>hits / conf</th><th>chains</th>
    <th>avg lead (h)</th><th>parent / source</th><th>notes</th></tr>
{wallets}
</table>

<h2>Recent Binance announcements</h2>
<table>
<tr><th>when</th><th>title</th></tr>
{announcements}
</table>

<h2>Telegram leaks (with contract addresses)</h2>
<table>
<tr><th>when</th><th>channel</th><th>text</th><th>addresses</th></tr>
{tg}
</table>
</body></html>
"""


def _fmt_ts(ts: int) -> str:
    if not ts:
        return ""
    delta = int(time.time()) - ts
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    with db.conn() as c:
        alerts = c.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT 100"
        ).fetchall()
        # Order so PRIMARY appears first, then EXPANDED, then BINANCE_2NDARY
        wallets = c.execute(
            "SELECT * FROM insider_wallets "
            "ORDER BY CASE tier WHEN 'PRIMARY' THEN 0 "
            "                   WHEN 'EXPANDED' THEN 1 "
            "                   WHEN 'BINANCE_2NDARY' THEN 2 ELSE 3 END, "
            "         hit_count DESC, confidence DESC LIMIT 100"
        ).fetchall()
        counts = c.execute(
            "SELECT tier, COUNT(*) AS n FROM insider_wallets GROUP BY tier"
        ).fetchall()
        anns = c.execute(
            "SELECT * FROM binance_announcements ORDER BY release_date DESC LIMIT 20"
        ).fetchall()
        tgs = c.execute(
            "SELECT * FROM tg_messages WHERE contains_token_address=1 "
            "ORDER BY ts DESC LIMIT 30"
        ).fetchall()
    tier_counts = {r["tier"]: r["n"] for r in counts}
    alerts_html = "".join(
        f"<tr><td class='small'>{_fmt_ts(a['ts'])}</td>"
        f"<td class='{a['severity']}'>{a['severity']}</td>"
        f"<td>{a['kind']}</td><td>{a['subject'] or ''}</td>"
        f"<td>{a['message']}</td></tr>"
        for a in alerts
    ) or "<tr><td colspan=5 class='small'>(no alerts yet)</td></tr>"
    def _hitconf(w):
        if w["tier"] == "PRIMARY":
            return f"{w['hit_count']} hits"
        return f"conf {w['confidence']:.2f}" if w["confidence"] else "—"

    wallets_html = "".join(
        f"<tr><td class='{w['tier']}'><b>{w['tier']}</b></td>"
        f"<td>{w['wallet']}</td>"
        f"<td>{_hitconf(w)}</td>"
        f"<td>{w['chains']}</td>"
        f"<td>{w['avg_lead_time_h'] or ''}</td>"
        f"<td class='small'>{(w['parent_wallet'] or w['funding_source'] or '')[:18]}</td>"
        f"<td class='small'>{(w['symbols'] or w['notes'] or '')[:80]}</td></tr>"
        for w in wallets
    ) or "<tr><td colspan=7 class='small'>(none — run scanner)</td></tr>"
    ann_html = "".join(
        f"<tr><td class='small'>{_fmt_ts(a['release_date'])}</td>"
        f"<td><a href='{a['url']}' target='_blank'>{a['title']}</a></td></tr>"
        for a in anns
    ) or "<tr><td colspan=2 class='small'>(none)</td></tr>"
    tg_html = "".join(
        f"<tr><td class='small'>{_fmt_ts(t['ts'])}</td>"
        f"<td>{t['channel']}</td>"
        f"<td>{(t['text'] or '')[:200]}</td>"
        f"<td class='small'>{t['extracted_addresses']}</td></tr>"
        for t in tgs
    ) or "<tr><td colspan=4 class='small'>(no tg leaks captured)</td></tr>"

    return PAGE.format(
        db_path=config.DB_PATH,
        n_wallets=len(wallets),
        n_primary=tier_counts.get("PRIMARY", 0),
        n_expanded=tier_counts.get("EXPANDED", 0),
        n_secondary=tier_counts.get("BINANCE_2NDARY", 0),
        min_listings=config.MIN_LISTINGS_FOR_INSIDER,
        alerts=alerts_html,
        wallets=wallets_html,
        announcements=ann_html,
        tg=tg_html,
    )


@app.get("/api/alerts")
def api_alerts(limit: int = 100):
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/insider-wallets")
def api_wallets():
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM insider_wallets ORDER BY hit_count DESC"
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/wallet/{wallet}")
def api_wallet(wallet: str):
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM wallet_events WHERE wallet=? ORDER BY ts DESC LIMIT 200",
            (wallet,),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/insider-wallets/{tier}")
def api_wallets_by_tier(tier: str):
    """tier ∈ {PRIMARY, EXPANDED, BINANCE_2NDARY, all}"""
    with db.conn() as c:
        if tier.lower() == "all":
            rows = c.execute(
                "SELECT * FROM insider_wallets ORDER BY tier, confidence DESC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM insider_wallets WHERE tier=? "
                "ORDER BY confidence DESC, hit_count DESC",
                (tier.upper(),),
            ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/funding-edges/{wallet}")
def api_edges(wallet: str):
    """Return funding lineage edges touching `wallet` (in or out)."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM funding_edges "
            "WHERE from_wallet=? OR to_wallet=? "
            "ORDER BY ts DESC LIMIT 200",
            (wallet, wallet),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])
