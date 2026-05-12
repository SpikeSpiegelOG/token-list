"""Single-token CLI: run the full qualification end-to-end for one address.

Usage:
    python -m qualification.qualify <token_addr>
    python -m qualification.qualify <token_addr> --chain solana
    python -m qualification.qualify <token_addr> --chain ethereum --symbol PEPE
    python -m qualification.qualify <token_addr> --twitter pepecoin --json

Defaults:
    - Chain auto-detected from address shape (0x… → ethereum; base58 → solana)
    - Symbol resolved via DEXScreener
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402
from qualification import qualification_score, market_metrics  # noqa: E402


def _guess_chain(addr: str) -> str:
    if addr.startswith("0x") and len(addr) == 42:
        return "ethereum"
    return "solana"


def _resolve_symbol_and_chain(addr: str, fallback_chain: str) -> tuple[str, str]:
    """Use DEXScreener to resolve the symbol + first pool's chainId."""
    try:
        m = market_metrics.dexscreener(addr) or {}
        chain_id = (m.get("chain") or "").lower()
        chain_map = {
            "ethereum": "ethereum", "bsc": "binance-smart-chain",
            "base": "base", "arbitrum": "arbitrum-one",
            "polygon": "polygon-pos", "solana": "solana",
            "optimism": "optimistic-ethereum",
        }
        chain = chain_map.get(chain_id, fallback_chain)
        # Symbol from any pool
        return "", chain
    except Exception:
        return "", fallback_chain


def _print_human(result: dict) -> None:
    sym = result.get("symbol") or result["token_addr"][:10]
    chain = result["chain"]
    print()
    print("=" * 64)
    print(f" QUALIFICATION REPORT — {sym}  ({chain})")
    print(f" {result['token_addr']}")
    print("=" * 64)
    print()
    print(f" Total:    {result['total']}/100   →   {result['verdict']}")
    print()
    print(" ┌─────────────┬───────┬─────────────────────────────────")
    print(" │ Component   │ Score │ Detail")
    print(" ├─────────────┼───────┼─────────────────────────────────")

    # MARKET
    m = result.get("market", {})
    metrics = m.get("metrics", {}) if isinstance(m, dict) else {}
    passes = m.get("passes", {}) if isinstance(m, dict) else {}
    print(f" │ Market      │ {result['score_market']:>5} │ "
          f"vol={metrics.get('volume_24h_usd', 0):>11,.0f}  "
          f"liq={metrics.get('liquidity_usd', 0):>9,.0f}  "
          f"holders={metrics.get('holders') or '?'}  "
          f"txns={metrics.get('txns_24h', 0)}")
    if passes:
        flags = " ".join(
            ("✓" if v else "·") + k.replace("_", "")[:3]
            for k, v in passes.items()
        )
        print(f" │             │       │ gates: {flags}")

    # SOCIAL
    s = result.get("social", {})
    lc = s.get("lunarcrush") if isinstance(s, dict) else {}
    tw = s.get("twitter") if isinstance(s, dict) else {}
    print(f" │ Social      │ {result['score_social']:>5} │ "
          f"galaxy={(lc or {}).get('galaxy_score') or '?'}  "
          f"social_vol={(lc or {}).get('social_volume_24h') or '?'}  "
          f"followers={(tw or {}).get('followers') or '?'}")

    # INSIDER
    print(f" │ Insider     │ {result['score_insider']:>5} │ "
          f"buyers={result.get('insider_buyers', 0)}  "
          f"strength_med={result.get('median_buyer_strength', 0)}")

    # PAYMENT
    p = result.get("payment", {})
    if isinstance(p, dict) and "matches" in p:
        print(f" │ Payment     │ {result['score_payment']:>5} │ "
              f"matches={len(p['matches'])}  verdict={p.get('verdict', '?')}")
        for m_ in (p.get("matches") or [])[:5]:
            print(f" │             │       │   {m_['team_wallet'][:14]}… → "
                  f"{m_['recipient'][:14]}…  ${m_['amount_usd']:>10,.0f}  "
                  f"({m_['recipient_tier']})")
    else:
        print(f" │ Payment     │ {result['score_payment']:>5} │ "
              f"{(p or {}).get('error') or (p or {}).get('note') or '—'}")
    print(" └─────────────┴───────┴─────────────────────────────────")
    print()
    print(" Verdict scale:  STRONG ≥70   MODERATE 45-69   WEAK <45")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("token", help="Token contract / mint address")
    ap.add_argument("--chain", choices=[
        "auto", "solana", "ethereum", "binance-smart-chain", "base",
        "arbitrum-one", "polygon-pos", "optimistic-ethereum",
    ], default="auto")
    ap.add_argument("--symbol", default="", help="Override the resolved symbol")
    ap.add_argument("--twitter", default="",
                    help="Twitter/X handle (no @) for social scoring")
    ap.add_argument("--insider-buyers", type=int, default=0,
                    help="Pre-computed insider convergence count (from "
                         "candidates.score_tokens). If 0, queries the local DB.")
    ap.add_argument("--strength", type=float, default=0.0,
                    help="Pre-computed median insider hit strength")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    chain = args.chain if args.chain != "auto" else _guess_chain(args.token)
    if args.chain == "auto":
        _, resolved = _resolve_symbol_and_chain(args.token, chain)
        chain = resolved

    # Auto-pull insider info from DB if not supplied
    insider_buyers = args.insider_buyers
    strength = args.strength
    if not insider_buyers:
        try:
            db.init()
            with db.conn() as c:
                row = c.execute(
                    "SELECT COUNT(DISTINCT we.wallet) AS n, "
                    "  AVG(iw.hit_count) AS s "
                    "FROM wallet_events we "
                    "JOIN insider_wallets iw ON iw.wallet = we.wallet "
                    "WHERE we.token_addr = ? AND we.direction='in'",
                    (args.token.lower(),),
                ).fetchone()
                if row and row["n"]:
                    insider_buyers = row["n"]
                    strength = float(row["s"] or 0)
        except Exception:
            pass

    result = qualification_score.score_token(
        token_addr=args.token,
        chain=chain,
        symbol=args.symbol,
        twitter_handle=args.twitter,
        insider_buyers=insider_buyers,
        median_buyer_strength=strength,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
