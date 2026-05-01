"""Scan Polymarket and Kalshi for cross-venue arbitrage. Read-only, no keys.

Strategy: pull active YES/NO binary markets from both venues, group by similar
question, flag any pairing where (YES_a + NO_b) < $0.99.

This is a *scaffold* — the question-matching is naive (substring + tag).
Production matchers use embeddings or hand-curated mappings.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import requests
from tabulate import tabulate

POLY_GAMMA = "https://gamma-api.polymarket.com/markets"
KALSHI_REST = "https://api.elections.kalshi.com/trade-api/v2/markets"


@dataclass
class Market:
    venue: str
    id: str
    question: str
    yes_ask: float | None  # cost to buy YES
    no_ask: float | None   # cost to buy NO
    volume: float
    end_ts: str | None


def fetch_polymarket(tag: str | None, limit: int = 200) -> list[Market]:
    params = {"limit": limit, "active": "true", "closed": "false", "order": "volume24hr",
              "ascending": "false"}
    if tag:
        params["tag_slug"] = tag
    r = requests.get(POLY_GAMMA, params=params, timeout=15)
    r.raise_for_status()
    out = []
    for m in r.json():
        # Polymarket binary markets have outcome_prices = ["YES_price", "NO_price"]
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            import json
            prices = json.loads(prices)
        if not prices or len(prices) != 2:
            continue
        yes_p, no_p = float(prices[0]), float(prices[1])
        out.append(Market(
            venue="polymarket",
            id=m.get("conditionId") or m.get("id", ""),
            question=m.get("question", ""),
            yes_ask=yes_p,
            no_ask=no_p,
            volume=float(m.get("volume24hr") or 0),
            end_ts=m.get("endDate"),
        ))
    return out


def fetch_kalshi(tag: str | None, limit: int = 200) -> list[Market]:
    params = {"limit": min(limit, 200), "status": "open"}
    if tag:
        params["tickers"] = tag.upper()
    r = requests.get(KALSHI_REST, params=params, timeout=15)
    r.raise_for_status()
    data = r.json().get("markets", [])
    out = []
    for m in data:
        yes_ask = m.get("yes_ask")  # cents 0-100
        no_ask = m.get("no_ask")
        if yes_ask is None or no_ask is None:
            continue
        out.append(Market(
            venue="kalshi",
            id=m.get("ticker", ""),
            question=m.get("title") or m.get("subtitle") or "",
            yes_ask=yes_ask / 100.0,
            no_ask=no_ask / 100.0,
            volume=float(m.get("volume_24h") or 0),
            end_ts=m.get("close_time"),
        ))
    return out


def naive_match(poly: list[Market], kal: list[Market]) -> list[tuple[Market, Market, float]]:
    """Return (poly_market, kalshi_market, total_cost) for any pairing < $1.

    Naive: matches markets where question text shares ≥3 substantive words.
    """
    arbs = []
    stop = {"the", "a", "an", "of", "to", "in", "on", "by", "at", "for",
            "is", "be", "will", "be", "than", "or", "and", "above", "below"}

    def words(s: str) -> set[str]:
        return {w.lower() for w in s.split() if len(w) > 2 and w.lower() not in stop}

    for p in poly:
        pw = words(p.question)
        for k in kal:
            kw = words(k.question)
            if len(pw & kw) < 3:
                continue
            # buy YES on the cheaper-YES side, NO on the other
            for (yes_m, no_m) in [(p, k), (k, p)]:
                if yes_m.yes_ask and no_m.no_ask:
                    cost = yes_m.yes_ask + no_m.no_ask
                    if cost < 1.0:
                        arbs.append((yes_m, no_m, cost))
    arbs.sort(key=lambda x: x[2])
    return arbs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="bitcoin", help="topic filter (bitcoin, sports, ...)")
    p.add_argument("--threshold", type=float, default=0.99, help="alert if cost <")
    args = p.parse_args()

    print(f"Fetching Polymarket markets (tag={args.tag})…")
    poly = fetch_polymarket(args.tag)
    print(f"  got {len(poly)}")

    kalshi_tag = "KXBTC" if args.tag == "bitcoin" else None
    print(f"Fetching Kalshi markets (tickers={kalshi_tag})…")
    kal = fetch_kalshi(kalshi_tag)
    print(f"  got {len(kal)}")

    arbs = [a for a in naive_match(poly, kal) if a[2] < args.threshold]
    if not arbs:
        print("\nNo cross-venue arbs found right now (this is the common case).")
        print("Top liquid Polymarket questions:")
        print(tabulate(
            [[m.question[:60], f"{m.yes_ask:.3f}", f"{m.no_ask:.3f}",
              f"${m.volume:,.0f}"] for m in sorted(poly, key=lambda m: -m.volume)[:10]],
            headers=["question", "yes", "no", "vol24h"]))
        return

    print(f"\n{len(arbs)} potential arbs (verify resolution criteria match!):\n")
    print(tabulate(
        [[f"{cost:.3f}", f"{1-cost:.3f}",
          f"YES@{y.venue}: {y.question[:40]} ({y.yes_ask:.3f})",
          f"NO@{n.venue}: {n.question[:40]} ({n.no_ask:.3f})"]
         for y, n, cost in arbs[:20]],
        headers=["total cost", "edge", "yes leg", "no leg"]))


if __name__ == "__main__":
    main()
