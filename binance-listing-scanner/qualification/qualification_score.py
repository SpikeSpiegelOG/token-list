"""Combine all four signal classes into a single 0–100 "Binance-ready score"
per candidate token.

Modeled directly on the ACT1 story's reported listing criteria:

  1. MARKET METRICS    — volume / liquidity / holders / txns
                         (market_metrics.evaluate)
  2. SOCIAL ACTIVITY   — X mindshare / followers / mentions
                         (social_score.evaluate)
  3. INSIDER FLOW      — insider clusters accumulating on-chain
                         (candidates/score_tokens.py output)
  4. PAYMENT LINEAGE   — team has paid a known facilitator
                         (payment_lineage.check_token)

Each contributes up to 25 points. A token scoring >= 70 satisfies enough of
the (allegedly) real Binance memecoin listing playbook that the listing
probability is materially elevated.

Note: a HIGH PAYMENT_LINEAGE score on its own is a red flag, not a buy
signal — it suggests insider/facilitator activity has begun, which is when
PRIMARY clusters typically front-run. Layer with INSIDER_FLOW for entry.

Usage:
    python -m qualification.qualification_score
        → reads data/candidates.json (from candidates.score_tokens)
        → writes data/qualified_candidates.json with full breakdown
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402
from qualification import market_metrics, social_score, payment_lineage

WEIGHTS = {
    "market": 25,
    "social": 25,
    "insider": 25,
    "payment": 25,
}


def score_token(token_addr: str, chain: str, symbol: str = "",
                twitter_handle: str = "",
                insider_buyers: int = 0,
                median_buyer_strength: float = 0.0) -> dict:
    out: dict = {"token_addr": token_addr, "chain": chain, "symbol": symbol}

    # 1. Market
    try:
        m = market_metrics.evaluate(
            token_addr, chain=chain,
            helius_key=config.HELIUS_API_KEY,
            etherscan_key=config.ETHERSCAN_API_KEY,
        )
        out["market"] = m
        # 25 points proportional to gates passed (0..4)
        out["score_market"] = round(m["gates_passed"] / 4 * WEIGHTS["market"], 1)
    except Exception as e:
        out["market"] = {"error": str(e)}
        out["score_market"] = 0

    # 2. Social
    try:
        s = social_score.evaluate(symbol, twitter_handle=twitter_handle,
                                  lunarcrush_key="")
        out["social"] = s
        out["score_social"] = round(s["gates_passed"] / 3 * WEIGHTS["social"], 1)
    except Exception as e:
        out["social"] = {"error": str(e)}
        out["score_social"] = 0

    # 3. Insider flow — already computed by candidates.score_tokens; we
    # parameterize so caller passes pre-computed values.
    insider_pts = 0.0
    if insider_buyers >= 5:
        insider_pts = WEIGHTS["insider"]
    elif insider_buyers >= 3:
        insider_pts = WEIGHTS["insider"] * 0.7
    elif insider_buyers >= 2:
        insider_pts = WEIGHTS["insider"] * 0.4
    insider_pts *= min(1.0, median_buyer_strength / 4.0)  # scale by hit-strength
    out["insider_buyers"] = insider_buyers
    out["median_buyer_strength"] = median_buyer_strength
    out["score_insider"] = round(insider_pts, 1)

    # 4. Payment lineage — now supports EVM + Solana
    try:
        p = payment_lineage.check_token(token_addr, chain)
        out["payment"] = p
        # Normalize: payment score of 1.5+ caps at 25 pts
        out["score_payment"] = round(
            min(p.get("score", 0) / 1.5 * WEIGHTS["payment"],
                WEIGHTS["payment"]), 1
        )
    except Exception as e:
        out["payment"] = {"error": str(e)}
        out["score_payment"] = 0

    out["total"] = round(
        out["score_market"] + out["score_social"] +
        out["score_insider"] + out["score_payment"], 1
    )
    out["verdict"] = (
        "STRONG" if out["total"] >= 70 else
        "MODERATE" if out["total"] >= 45 else
        "WEAK"
    )
    return out


def main() -> None:
    cand_path = config.DATA_DIR / "candidates.json"
    if not cand_path.exists():
        print("Run candidates/score_tokens.py first.")
        return
    candidates = json.loads(cand_path.read_text())

    out_rows = []
    for cand in candidates[:50]:
        token_addr = cand["token"]
        symbol = cand.get("symbol") or ""
        chain = "solana" if (cand.get("chains") and "solana" in cand["chains"]) \
                else "ethereum"
        print(f"scoring {symbol}…")
        try:
            row = score_token(
                token_addr, chain, symbol,
                insider_buyers=cand.get("insider_buyers", 0),
                median_buyer_strength=cand.get("median_buyer_strength", 0),
            )
        except Exception as e:
            print(f"  err: {e}")
            continue
        out_rows.append(row)
        time.sleep(0.5)
    out_rows.sort(key=lambda r: -r["total"])

    out = config.DATA_DIR / "qualified_candidates.json"
    out.write_text(json.dumps(out_rows, indent=2))
    print(f"Wrote {len(out_rows)} scored candidates → {out}")
    print()
    print(f"{'SYMBOL':<10} {'TOTAL':>6}  M    S    I    P    VERDICT")
    for r in out_rows[:20]:
        print(f"{(r['symbol'] or r['token_addr'][:8]):<10} "
              f"{r['total']:>6.1f}  "
              f"{r['score_market']:>4.1f} "
              f"{r['score_social']:>4.1f} "
              f"{r['score_insider']:>4.1f} "
              f"{r['score_payment']:>4.1f}  "
              f"{r['verdict']}")


if __name__ == "__main__":
    main()
