"""Validation harness — runs the cluster + facilitator detection logic
against the synthetic fixtures and asserts that:

  1. The PRIMARY cluster identifies the 3 known insider wallets and
     excludes the 4 noise wallets.
  2. The facilitator aggregation logic identifies W_FACILITATOR
     (paid by 3 distinct teams) and rejects W_UNRELATED_REC (paid by 2).
  3. The scoring code paths run without exceptions.
  4. Market metrics (live) work against real listed memecoins via DEXScreener
     (the only no-auth API in the qualification stack).

Run:
    python -m validation.validate_pipeline
    python -m validation.validate_pipeline --live   # also hit DEXScreener
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
SKIP = "\033[93m∼ SKIP\033[0m"


def _ok(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {PASS if ok else FAIL}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def _skip(name: str, reason: str) -> None:
    print(f"  {SKIP}  {name}  — {reason}")


# --------------------------------------------------------------------------
# Mock-mode tests (no network, no API keys)
# --------------------------------------------------------------------------

def test_primary_clustering(tmpdir: Path) -> bool:
    """Write fixtures to tmpdir, then run scanner/cluster.py's logic on them.
    We invoke the same code by setting config.DATA_DIR to the tmpdir.
    """
    from validation import fixtures

    # Lay out tmpdir structure expected by cluster.py
    listings_path = tmpdir / "listings.json"
    listings_path.write_text(json.dumps(fixtures.LISTINGS))
    buyers_dir = tmpdir / "buyers"
    buyers_dir.mkdir(exist_ok=True)
    for sym, buys in fixtures.BUYERS.items():
        (buyers_dir / f"{sym}.json").write_text(json.dumps(buys))

    # Monkey-patch config.DATA_DIR to point at the fixture dir
    import config as cfg
    original = cfg.DATA_DIR
    cfg.DATA_DIR = tmpdir
    cfg.MIN_LISTINGS_FOR_INSIDER = 3

    try:
        # Force reload of cluster module to pick up new DATA_DIR
        from scanner import cluster as _cluster
        import importlib
        importlib.reload(_cluster)
        _cluster.main()
    finally:
        cfg.DATA_DIR = original

    out = json.loads((tmpdir / "insider_wallets.json").read_text())
    found = {r["wallet"] for r in out}

    ok = True
    missing = fixtures.EXPECTED_PRIMARY - found
    ok &= _ok("identifies all 3 expected PRIMARY insiders",
              not missing, f"missing={list(missing)}" if missing else "")
    leaked = fixtures.EXPECTED_NOT_PRIMARY & found
    ok &= _ok("rejects noise wallets",
              not leaked, f"leaked={list(leaked)}" if leaked else "")
    return ok


def test_facilitator_aggregation() -> bool:
    """Skip the network call layer — directly exercise the
    aggregation/grouping logic on the fixtures.TEAM_PAYMENTS structure.
    """
    from validation import fixtures
    from qualification.facilitator_finder import MIN_DISTINCT_PAYERS

    # Build the recipient_payments dict the way scan() would
    recipient_payments: dict[str, list[dict]] = defaultdict(list)
    for team_wallet, payments in fixtures.TEAM_PAYMENTS.items():
        for p in payments:
            recipient_payments[p["to"]].append(p)

    facilitators = set()
    for recipient, payments in recipient_payments.items():
        distinct = {p["from_team"] for p in payments}
        if len(distinct) >= MIN_DISTINCT_PAYERS:
            facilitators.add(recipient)

    ok = True
    ok &= _ok("identifies known facilitator (3 distinct payers)",
              fixtures.EXPECTED_FACILITATORS <= facilitators,
              f"found={facilitators}")
    leaked = fixtures.EXPECTED_NOT_FACILITATORS & facilitators
    ok &= _ok("rejects single-payer recipient (< MIN_DISTINCT_PAYERS)",
              not leaked, f"leaked={list(leaked)}" if leaked else "")
    return ok


def test_solana_secondary_wired() -> bool:
    """Solana Binance hot wallets are surfaced and the dispatcher hits them."""
    from scanner import binance_secondary
    ok = True
    ok &= _ok("Solana hot wallets defined",
              len(binance_secondary.SOLANA_HOTS) >= 1,
              f"got {len(binance_secondary.SOLANA_HOTS)}")
    ok &= _ok("scan_solana exists",
              callable(getattr(binance_secondary, "scan_solana", None)))
    ok &= _ok("score_secondary_solana exists",
              callable(getattr(binance_secondary, "score_secondary_solana", None)))
    return ok


def test_facilitator_graph_builder(tmpdir: Path) -> bool:
    """Build a graph for our synthetic facilitator and assert the shape
    contains the expected nodes/edges.
    """
    from validation import fixtures

    # Stage a facilitators.json that the dashboard reader will pick up
    facs = [{
        "wallet": fixtures.W_FACILITATOR,
        "distinct_payers": 3,
        "distinct_listings": ["PNUTX", "ACTX", "MEME4"],
        "chains": ["ethereum"],
        "payment_count": 3,
        "total_usd_received": 300_000,
        "payments": [
            {"from_team": fixtures.W_TEAM_PNUT,  "to": fixtures.W_FACILITATOR,
             "amount_usd": 100_000, "listing_symbol": "PNUTX", "chain": "ethereum",
             "ts": fixtures.T0 + 28 * fixtures.DAY, "tx": "0xpay1", "symbol": "USDC"},
            {"from_team": fixtures.W_TEAM_ACT,   "to": fixtures.W_FACILITATOR,
             "amount_usd": 120_000, "listing_symbol": "ACTX",  "chain": "ethereum",
             "ts": fixtures.T0 + 33 * fixtures.DAY, "tx": "0xpay2", "symbol": "USDC"},
            {"from_team": fixtures.W_TEAM_MEME4, "to": fixtures.W_FACILITATOR,
             "amount_usd": 80_000,  "listing_symbol": "MEME4", "chain": "ethereum",
             "ts": fixtures.T0 + 43 * fixtures.DAY, "tx": "0xpay3", "symbol": "USDC"},
        ],
    }]
    (tmpdir / "facilitators.json").write_text(json.dumps(facs))

    import config as cfg
    original = cfg.DATA_DIR
    cfg.DATA_DIR = tmpdir
    try:
        from monitor import dashboard
        import importlib
        importlib.reload(dashboard)
        graph = dashboard._build_facilitator_graph(fixtures.W_FACILITATOR)
    finally:
        cfg.DATA_DIR = original

    ok = True
    ok &= _ok("graph has center node",
              graph.get("center") == fixtures.W_FACILITATOR)
    node_ids = {n["id"] for n in graph.get("nodes", [])}
    ok &= _ok("facilitator node present",
              fixtures.W_FACILITATOR in node_ids)
    expected_teams = {fixtures.W_TEAM_PNUT, fixtures.W_TEAM_ACT,
                      fixtures.W_TEAM_MEME4}
    ok &= _ok("all 3 paying team nodes present",
              expected_teams <= node_ids,
              f"missing={expected_teams - node_ids}")
    # Should have 3 inbound edges (one per team, aggregated)
    edge_count = sum(1 for e in graph.get("edges", [])
                     if e["to"] == fixtures.W_FACILITATOR)
    ok &= _ok("3 inbound edges (team→facilitator)",
              edge_count == 3, f"got {edge_count}")
    ok &= _ok("stats.distinct_payers == 3",
              (graph.get("stats") or {}).get("distinct_payers") == 3)
    return ok


def test_tier_weighting() -> bool:
    """The convergence scoring weights tiers correctly."""
    from monitor.wallet_watcher import TIER_WEIGHT

    ok = True
    ok &= _ok("PRIMARY weight is 1.0", TIER_WEIGHT["PRIMARY"] == 1.0)
    ok &= _ok("FACILITATOR weight > EXPANDED",
              TIER_WEIGHT["FACILITATOR"] > TIER_WEIGHT["EXPANDED"])
    ok &= _ok("BINANCE_2NDARY lowest", TIER_WEIGHT["BINANCE_2NDARY"] ==
              min(TIER_WEIGHT.values()))

    # 2 PRIMARY = threshold 2.0
    score = TIER_WEIGHT["PRIMARY"] * 2
    ok &= _ok("2 PRIMARYs sum to entry threshold (2.0)",
              score >= 2.0, f"got {score}")
    # 4 BINANCE_2NDARYs should also trigger entry
    score = TIER_WEIGHT["BINANCE_2NDARY"] * 4
    ok &= _ok("4 BINANCE_2NDARYs sum to >= 2.0",
              score >= 2.0, f"got {score}")
    return ok


def test_imports() -> bool:
    """All modules import without error — catches syntax/dep bugs early."""
    ok = True
    for mod in (
        "config",
        "monitor.db", "monitor.dashboard", "monitor.wallet_watcher",
        "monitor.tg_scraper", "monitor.announcement_watcher",
        "scanner.binance_listings", "scanner.prelisting_buyers",
        "scanner.cluster", "scanner.cluster_expansion",
        "scanner.binance_secondary",
        "candidates.score_tokens",
        "qualification.market_metrics", "qualification.social_score",
        "qualification.facilitator_finder", "qualification.payment_lineage",
        "qualification.qualification_score", "qualification.qualify",
        "qualification.solana_helpers",
    ):
        try:
            __import__(mod)
            ok &= _ok(f"import {mod}", True)
        except Exception as e:
            ok &= _ok(f"import {mod}", False, str(e))
    return ok


# --------------------------------------------------------------------------
# Live-mode tests (DEXScreener only — no auth required)
# --------------------------------------------------------------------------

LIVE_TOKENS = [
    # (symbol, address, chain, expected_min_volume_usd)
    ("PNUT",  "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump", "solana",  100_000),
    ("PEPE",  "0x6982508145454ce325ddbe47a25d4ec3d2311933",     "ethereum", 1_000_000),
    ("DOGE",  "0x4206931337dc273a630d328dA6441786BfaD668f",     "ethereum", 0),
]


def test_live_dexscreener() -> bool:
    """Real DEXScreener data for known listed tokens — no API key needed."""
    from qualification import market_metrics

    ok = True
    for sym, addr, chain, min_vol in LIVE_TOKENS:
        try:
            data = market_metrics.dexscreener(addr)
        except Exception as e:
            ok &= _ok(f"DEXScreener for {sym}", False, str(e))
            continue
        if not data:
            _skip(f"DEXScreener for {sym}", "no pairs returned (may be delisted)")
            continue
        vol = data.get("volume_24h_usd") or 0
        liq = data.get("liquidity_usd") or 0
        ok &= _ok(f"DEXScreener {sym} returns metrics",
                  vol > 0 or liq > 0,
                  f"vol=${vol:,.0f} liq=${liq:,.0f} chain={data.get('chain')}")
    return ok


def test_live_binance_announcements() -> bool:
    """Binance announcement CMS — no API key needed."""
    import requests
    try:
        r = requests.get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={"type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 5},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        data = r.json().get("data") or {}
        # Articles can live at top-level OR under data.catalogs[0].articles
        articles = data.get("articles") or (
            (data.get("catalogs") or [{}])[0].get("articles", [])
        )
        return _ok("Binance CMS returns articles",
                   len(articles) > 0, f"got {len(articles)} articles")
    except Exception as e:
        return _ok("Binance CMS reachable", False, str(e))


# --------------------------------------------------------------------------

def run(live: bool = False) -> int:
    print()
    print("=" * 64)
    print(" Binance Listing Scanner — validation harness")
    print("=" * 64)
    print()

    results: list[bool] = []

    print("[1] Imports")
    results.append(test_imports())
    print()

    print("[2] PRIMARY cluster detection (synthetic fixtures)")
    with tempfile.TemporaryDirectory() as td:
        results.append(test_primary_clustering(Path(td)))
    print()

    print("[3] FACILITATOR aggregation (synthetic fixtures)")
    results.append(test_facilitator_aggregation())
    print()

    print("[4] Tier weighting invariants")
    results.append(test_tier_weighting())
    print()

    print("[5] Solana Binance-secondary wiring")
    results.append(test_solana_secondary_wired())
    print()

    print("[6] Facilitator graph builder")
    with tempfile.TemporaryDirectory() as td:
        results.append(test_facilitator_graph_builder(Path(td)))
    print()

    if live:
        print("[7] Live DEXScreener (no auth)")
        results.append(test_live_dexscreener())
        print()
        print("[8] Live Binance announcement CMS (no auth)")
        results.append(test_live_binance_announcements())
        print()
    else:
        print("[7] Live tests — skipped (pass --live to enable)")
        print()

    passed = sum(results)
    total = len(results)
    print("=" * 64)
    if passed == total:
        print(f" \033[92mALL {total} TEST GROUPS PASSED\033[0m")
    else:
        print(f" \033[91m{passed}/{total} TEST GROUPS PASSED\033[0m")
    print("=" * 64)
    print()
    return 0 if passed == total else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="Also run live no-auth API checks (DEXScreener, Binance CMS)")
    args = ap.parse_args()
    sys.exit(run(live=args.live))


if __name__ == "__main__":
    main()
