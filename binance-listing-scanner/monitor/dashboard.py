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

<h2>Insider wallets ({n_wallets})</h2>
<table>
<tr><th>wallet</th><th>hits</th><th>chains</th><th>avg lead (h)</th><th>symbols</th></tr>
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
        wallets = c.execute(
            "SELECT * FROM insider_wallets ORDER BY hit_count DESC LIMIT 50"
        ).fetchall()
        anns = c.execute(
            "SELECT * FROM binance_announcements ORDER BY release_date DESC LIMIT 20"
        ).fetchall()
        tgs = c.execute(
            "SELECT * FROM tg_messages WHERE contains_token_address=1 "
            "ORDER BY ts DESC LIMIT 30"
        ).fetchall()
    alerts_html = "".join(
        f"<tr><td class='small'>{_fmt_ts(a['ts'])}</td>"
        f"<td class='{a['severity']}'>{a['severity']}</td>"
        f"<td>{a['kind']}</td><td>{a['subject'] or ''}</td>"
        f"<td>{a['message']}</td></tr>"
        for a in alerts
    ) or "<tr><td colspan=5 class='small'>(no alerts yet)</td></tr>"
    wallets_html = "".join(
        f"<tr><td>{w['wallet']}</td><td>{w['hit_count']}</td>"
        f"<td>{w['chains']}</td><td>{w['avg_lead_time_h'] or ''}</td>"
        f"<td class='small'>{w['symbols']}</td></tr>"
        for w in wallets
    ) or "<tr><td colspan=5 class='small'>(none — run scanner)</td></tr>"
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
