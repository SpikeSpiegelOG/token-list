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
  .FACILITATOR { color: #f55; font-weight: bold; }
  .STRONG { color: #4f4; font-weight: bold; }
  .MODERATE { color: #fc4; }
  .WEAK { color: #888; }
  .bar { background:#222; height:10px; border-radius:4px; overflow:hidden; }
  .bar > div { background:#6cf; height:100%; }
  .small { color: #666; font-size: 11px; }
  a { color: #6cf; text-decoration: none; }
</style></head><body>
<h1>Binance Listing Scanner — local dashboard</h1>
<p class="small">
  Refreshes every 10s. Data path: {db_path}
  &nbsp;|&nbsp; <a href="/facilitators">facilitator graph</a>
  &nbsp;|&nbsp; <a href="/api/qualified-candidates">qualified-candidates JSON</a>
</p>

<h2>Live alerts (last 100)</h2>
<table>
<tr><th>when</th><th>severity</th><th>kind</th><th>subject</th><th>message</th></tr>
{alerts}
</table>

<h2>Qualified candidates — Binance-readiness score</h2>
<p class="small">
  Combined 0–100 score across <b>market</b> (volume/liquidity/holders),
  <b>social</b> (X mindshare/followers), <b>insider</b> (cluster accumulation),
  <b>payment</b> (team→facilitator transfers).
</p>
<table>
<tr><th>symbol</th><th>chain</th><th>total</th><th>M</th><th>S</th><th>I</th><th>P</th><th>verdict</th></tr>
{qualified}
</table>

<h2>Insider wallets — tier breakdown ({n_wallets} total: {n_primary} P / {n_facilitator} F / {n_expanded} E / {n_secondary} B2)</h2>
<p class="small">
  <b style="color:#4f4">PRIMARY</b>  — appears in ≥{min_listings} historical pre-listing windows<br>
  <b style="color:#f55">FACILITATOR</b> — receives recurring $50k+ stablecoin tranches from many distinct memecoin team wallets ("listing fixer" archetype, per the ACT1 story)<br>
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

    # Load qualified candidates from JSON (written by qualification_score.py)
    qualified = []
    qpath = config.DATA_DIR / "qualified_candidates.json"
    if qpath.exists():
        try:
            import json as _json
            qualified = _json.loads(qpath.read_text())[:25]
        except Exception:
            qualified = []
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

    qualified_html = "".join(
        f"<tr><td><b>{q.get('symbol') or q['token_addr'][:8]}</b></td>"
        f"<td>{q['chain']}</td>"
        f"<td><div class='bar'><div style='width:{q['total']}%'></div></div>"
        f"<span class='small'>{q['total']}</span></td>"
        f"<td class='small'>{q['score_market']}</td>"
        f"<td class='small'>{q['score_social']}</td>"
        f"<td class='small'>{q['score_insider']}</td>"
        f"<td class='small'>{q['score_payment']}</td>"
        f"<td class='{q['verdict']}'><b>{q['verdict']}</b></td></tr>"
        for q in qualified
    ) or "<tr><td colspan=8 class='small'>(none — run qualification.qualification_score)</td></tr>"

    return PAGE.format(
        db_path=config.DB_PATH,
        n_wallets=len(wallets),
        n_primary=tier_counts.get("PRIMARY", 0),
        n_expanded=tier_counts.get("EXPANDED", 0),
        n_secondary=tier_counts.get("BINANCE_2NDARY", 0),
        n_facilitator=tier_counts.get("FACILITATOR", 0),
        min_listings=config.MIN_LISTINGS_FOR_INSIDER,
        alerts=alerts_html,
        qualified=qualified_html,
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


@app.get("/api/qualified-candidates")
def api_qualified():
    import json as _json
    qpath = config.DATA_DIR / "qualified_candidates.json"
    if not qpath.exists():
        return JSONResponse([])
    return JSONResponse(_json.loads(qpath.read_text()))


@app.get("/api/facilitators")
def api_facilitators():
    """Return the FACILITATOR-tier wallets with full payment history."""
    import json as _json
    fpath = config.DATA_DIR / "facilitators.json"
    if not fpath.exists():
        return JSONResponse([])
    return JSONResponse(_json.loads(fpath.read_text()))


def _build_facilitator_graph(wallet: str) -> dict:
    """Construct a graph payload for one facilitator wallet.

    Nodes:
      - the facilitator itself
      - every team wallet that paid it (from facilitators.json)
      - every wallet the facilitator paid out to (from funding_edges)
      - Binance hot wallets if the facilitator deposited to them
    Edges:
      - inbound: team -> facilitator (stable transfers from facilitators.json)
      - outbound: facilitator -> downstream (funding_edges where from=wallet)
    """
    import json as _json
    fpath = config.DATA_DIR / "facilitators.json"
    facilitators = _json.loads(fpath.read_text()) if fpath.exists() else []
    fac = next((f for f in facilitators if f["wallet"].lower() == wallet.lower()),
               None)
    if not fac:
        return {"error": "not a known facilitator", "wallet": wallet}

    nodes: dict[str, dict] = {}
    nodes[fac["wallet"]] = {
        "id": fac["wallet"],
        "label": f"FACILITATOR\n{fac['wallet'][:10]}…",
        "tier": "FACILITATOR",
        "title": fac.get("notes") or "",
        "total_in_usd": fac.get("total_usd_received", 0),
        "color": "#f55",
    }
    edges: list[dict] = []

    # Inbound team→facilitator edges, grouped by team wallet to keep graph readable
    by_team: dict[str, dict] = {}
    for p in fac.get("payments", []):
        tw = p["from_team"]
        if tw not in by_team:
            by_team[tw] = {"total": 0, "listings": set(), "tx_count": 0}
        by_team[tw]["total"] += p["amount_usd"]
        by_team[tw]["listings"].add(p["listing_symbol"])
        by_team[tw]["tx_count"] += 1

    for tw, agg in by_team.items():
        nodes[tw] = {
            "id": tw,
            "label": f"TEAM\n{tw[:10]}…\n({','.join(sorted(agg['listings']))})",
            "tier": "TEAM",
            "title": f"team wallet for {sorted(agg['listings'])}",
            "color": "#6cf",
        }
        edges.append({
            "from": tw, "to": fac["wallet"],
            "label": f"${agg['total']:,.0f}",
            "value": int(agg["total"] / 10_000),  # thickness
            "title": (f"${agg['total']:,.0f} across {agg['tx_count']} txns, "
                      f"listings: {sorted(agg['listings'])}"),
            "color": "#4f4",
        })

    # Outbound facilitator → downstream, from funding_edges. Tables may
    # not exist yet on a fresh DB — degrade gracefully.
    out_rows = []
    downstream_tiers: dict[str, str] = {}
    try:
        with db.conn() as c:
            out_rows = c.execute(
                "SELECT * FROM funding_edges WHERE from_wallet=? "
                "ORDER BY ts DESC LIMIT 50", (wallet,),
            ).fetchall()
            if out_rows:
                ds_addrs = list({r["to_wallet"] for r in out_rows})
                placeholders = ",".join("?" * len(ds_addrs))
                tier_rows = c.execute(
                    f"SELECT wallet, tier FROM insider_wallets "
                    f"WHERE wallet IN ({placeholders})",
                    ds_addrs,
                ).fetchall()
                downstream_tiers = {r["wallet"]: r["tier"] for r in tier_rows}
    except Exception:
        pass  # DB not initialized — render with inbound edges only

    # Group outbound by recipient too
    by_recipient: dict[str, dict] = {}
    for r in out_rows:
        to = r["to_wallet"]
        if to not in by_recipient:
            by_recipient[to] = {"count": 0, "asset": r["asset"]}
        by_recipient[to]["count"] += 1

    BINANCE_HOT_LABELS = {
        "0x28c6c06298d514db089934071355e5743bf21d60": "Binance: Hot Wallet 14",
        "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance: Hot Wallet 20",
        "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance: Hot Wallet 15",
        "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance: Solana 1",
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance: Solana 2",
    }
    for to, agg in by_recipient.items():
        binance_label = BINANCE_HOT_LABELS.get(to)
        tier = downstream_tiers.get(to)
        if binance_label:
            label = f"BINANCE\n{binance_label}"
            color = "#fc4"
        elif tier:
            label = f"{tier}\n{to[:10]}…"
            color = {"PRIMARY": "#4f4", "EXPANDED": "#fc4",
                     "BINANCE_2NDARY": "#f9f"}.get(tier, "#888")
        else:
            label = f"DOWNSTREAM\n{to[:10]}…"
            color = "#888"
        nodes[to] = {"id": to, "label": label, "color": color}
        edges.append({
            "from": fac["wallet"], "to": to,
            "label": f"{agg['count']}×",
            "title": f"{agg['count']} transfers in {agg['asset']}",
            "color": "#fc4", "dashes": True,
        })

    return {
        "center": fac["wallet"],
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "total_in_usd": fac.get("total_usd_received", 0),
            "distinct_payers": fac.get("distinct_payers", 0),
            "distinct_listings": fac.get("distinct_listings", []),
        },
    }


@app.get("/api/facilitator-graph/{wallet}")
def api_facilitator_graph(wallet: str):
    return JSONResponse(_build_facilitator_graph(wallet))


FACILITATOR_INDEX_PAGE = """
<!doctype html><html><head><title>Facilitators</title>
<style>
  body { font-family: ui-monospace, monospace; background:#0c0c0c; color:#ddd;
         padding: 18px; font-size: 13px; }
  h1 { color: #f55; }
  a { color: #6cf; text-decoration: none; }
  table { width: 100%; border-collapse: collapse; }
  td, th { padding: 6px 10px; text-align: left; border-bottom: 1px solid #222; }
  th { color: #888; font-weight: normal; }
</style></head><body>
<h1>Facilitator wallets</h1>
<p>Wallets receiving recurring $50k+ stablecoin tranches from many distinct
memecoin team wallets. Click a wallet to see its graph.</p>
<table>
<tr><th>wallet</th><th>distinct payers</th><th>total received</th>
    <th>listings</th><th>chains</th></tr>
{rows}
</table>
<p><a href="/">← back to dashboard</a></p>
</body></html>
"""


@app.get("/facilitators", response_class=HTMLResponse)
def facilitators_index() -> str:
    import json as _json
    fpath = config.DATA_DIR / "facilitators.json"
    if not fpath.exists():
        return "<p>No facilitators.json yet. Run qualification.facilitator_finder.</p>"
    facs = _json.loads(fpath.read_text())
    rows = "".join(
        f"<tr>"
        f"<td><a href='/facilitator-graph/{f['wallet']}'>{f['wallet']}</a></td>"
        f"<td>{f.get('distinct_payers', 0)}</td>"
        f"<td>${f.get('total_usd_received', 0):,.0f}</td>"
        f"<td>{', '.join(f.get('distinct_listings', []))}</td>"
        f"<td>{', '.join(f.get('chains', []))}</td>"
        f"</tr>"
        for f in facs
    ) or "<tr><td colspan=5>(none)</td></tr>"
    return FACILITATOR_INDEX_PAGE.format(rows=rows)


GRAPH_PAGE = """
<!doctype html><html><head><title>Facilitator graph</title>
<script src="https://unpkg.com/vis-network@9/standalone/umd/vis-network.min.js"></script>
<style>
  html, body { margin:0; padding:0; height:100%; background:#0c0c0c; color:#ddd;
               font-family: ui-monospace, monospace; }
  #hdr { padding:12px 18px; border-bottom:1px solid #222; font-size: 13px; }
  #hdr a { color:#6cf; text-decoration:none; }
  #graph { width:100%; height: calc(100vh - 110px); }
  .stat { display:inline-block; margin-right: 24px; }
  .stat b { color: #ffb500; }
  .legend { display:inline-block; margin-right:14px; font-size:11px; }
  .legend .dot { display:inline-block; width:10px; height:10px;
                 border-radius:50%; margin-right:4px; vertical-align:middle; }
</style></head><body>
<div id="hdr">
  <a href="/facilitators">← all facilitators</a>
  &nbsp;|&nbsp;
  <a href="/">dashboard</a>
  &nbsp;&nbsp;&nbsp;
  <span class="stat">facilitator: <b id="addr">{addr}</b></span>
  <span class="stat">payers: <b id="payers">…</b></span>
  <span class="stat">total in: <b id="total">…</b></span>
  <span class="stat">listings: <b id="listings">…</b></span>
  <br>
  <span class="legend"><span class="dot" style="background:#f55"></span>FACILITATOR</span>
  <span class="legend"><span class="dot" style="background:#6cf"></span>TEAM (paid in)</span>
  <span class="legend"><span class="dot" style="background:#4f4"></span>PRIMARY</span>
  <span class="legend"><span class="dot" style="background:#fc4"></span>EXPANDED / Binance</span>
  <span class="legend"><span class="dot" style="background:#f9f"></span>BINANCE_2NDARY</span>
  <span class="legend"><span class="dot" style="background:#888"></span>downstream</span>
</div>
<div id="graph"></div>
<script>
fetch('/api/facilitator-graph/{addr}').then(r=>r.json()).then(data=>{{
  if (data.error) {{ document.getElementById('graph').innerText = data.error; return; }}
  const stats = data.stats || {{}};
  document.getElementById('payers').innerText = stats.distinct_payers || 0;
  document.getElementById('total').innerText = '$' + (stats.total_in_usd || 0).toLocaleString();
  document.getElementById('listings').innerText = (stats.distinct_listings || []).join(', ');
  const container = document.getElementById('graph');
  new vis.Network(container, {{
    nodes: new vis.DataSet(data.nodes),
    edges: new vis.DataSet(data.edges),
  }}, {{
    nodes: {{ shape: 'box', font: {{ color: '#0c0c0c', size: 11 }},
              margin: 8, borderWidth: 0 }},
    edges: {{ font: {{ color: '#ccc', size: 10, strokeWidth: 0 }},
              arrows: 'to', smooth: {{ type: 'continuous' }} }},
    physics: {{ stabilization: {{ iterations: 200 }} }},
  }});
}});
</script></body></html>
"""


@app.get("/facilitator-graph/{wallet}", response_class=HTMLResponse)
def facilitator_graph_page(wallet: str) -> str:
    return GRAPH_PAGE.replace("{addr}", wallet)
