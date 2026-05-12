"""Pull recent Binance Spot listings, filter to memecoins, and resolve token contracts.

Binance has an undocumented but stable CMS endpoint that powers their
announcements page. catalogId=48 is "New Cryptocurrency Listing".

We then resolve the token symbol to an on-chain contract via CoinGecko, which
returns multi-chain addresses (eth, bsc, solana, base, etc).

Output (writes to data/listings.json):
[
  {
    "symbol": "PNUT",
    "name": "Peanut the Squirrel",
    "announced_at": 1731244800,    # unix seconds, UTC
    "announce_url": "https://www.binance.com/en/support/announcement/...",
    "platforms": {
        "solana": "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump",
        "ethereum": null,
        "binance-smart-chain": null
    }
  },
  ...
]
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, asdict
from typing import Iterable

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

LISTING_API = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
COINGECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
COINGECKO_COIN = "https://api.coingecko.com/api/v3/coins/{id}"

# Heuristics — Binance titles new spot listings as:
#   "Binance Will List X (SYMBOL)"
#   "Binance Lists X (SYMBOL)"
#   "Introducing X (SYMBOL) on Binance Spot"
TITLE_RE = re.compile(r"\(([A-Z0-9]{2,15})\)")

# Memecoin keywords — heuristic, biased false-positive (we'd rather scan extras)
MEME_KEYWORDS = (
    "meme", "dog", "cat", "frog", "pepe", "doge", "shib", "inu", "wojak",
    "chad", "wif", "bonk", "fart", "moodeng", "peanut", "squirrel",
    "mubarak", "broccoli", "banana", "neiro", "popcat", "turbo",
)


@dataclass
class Listing:
    symbol: str
    name: str
    announced_at: int
    announce_url: str
    platforms: dict[str, str | None]


def _looks_like_meme(title: str) -> bool:
    t = title.lower()
    if any(k in t for k in MEME_KEYWORDS):
        return True
    # Solana memecoins sometimes have addresses ending in `pump` — Binance often
    # mentions the chain in the article body, not title. Default false here;
    # strict mode would require Body fetch.
    return False


def fetch_recent_listings(n: int = 40) -> list[dict]:
    """Page through the Binance announcement CMS until we have N items.

    catalogId=48 → New Cryptocurrency Listing. pageSize max is 50.
    """
    out: list[dict] = []
    page = 1
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    while len(out) < n:
        params = {
            "type": 1,
            "catalogId": 48,
            "pageNo": page,
            "pageSize": 50,
        }
        r = requests.get(LISTING_API, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json().get("data") or {}
        # New (2026) response shape nests articles under data.catalogs[0].articles
        articles = data.get("articles") or (
            (data.get("catalogs") or [{}])[0].get("articles", [])
        )
        if not articles:
            break
        out.extend(articles)
        page += 1
        if page > 5:
            break
        time.sleep(0.5)
    return out[:n]


def coingecko_lookup(symbol: str) -> dict[str, str | None] | None:
    """Resolve a ticker → multi-chain platform addresses via CoinGecko."""
    headers = {}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
    r = requests.get(COINGECKO_SEARCH, params={"query": symbol}, headers=headers, timeout=10)
    if r.status_code != 200:
        return None
    coins = r.json().get("coins", [])
    # Prefer exact symbol match, ignore wrapped/IOU duplicates
    for c in coins:
        if c.get("symbol", "").upper() == symbol.upper():
            cid = c["id"]
            time.sleep(1.2)  # CoinGecko free tier is 30/min
            r2 = requests.get(COINGECKO_COIN.format(id=cid), headers=headers, timeout=10)
            if r2.status_code != 200:
                return None
            d = r2.json()
            return d.get("platforms", {})
    return None


def parse_listings(raw: Iterable[dict]) -> list[Listing]:
    out: list[Listing] = []
    for art in raw:
        title = art.get("title", "")
        if "Will List" not in title and "Lists" not in title and "Introducing" not in title:
            continue
        if not _looks_like_meme(title):
            continue
        m = TITLE_RE.search(title)
        if not m:
            continue
        symbol = m.group(1)
        name = title.split("(")[0].split("List")[-1].strip(" :")
        ts = int(art.get("releaseDate", 0)) // 1000
        code = art.get("code", "")
        url = f"https://www.binance.com/en/support/announcement/{code}" if code else ""
        platforms = coingecko_lookup(symbol) or {}
        out.append(Listing(symbol=symbol, name=name, announced_at=ts,
                           announce_url=url, platforms=platforms))
    return out


def main() -> None:
    raw = fetch_recent_listings(n=config.LOOKBACK_LISTINGS * 3)
    listings = parse_listings(raw)
    listings = listings[: config.LOOKBACK_LISTINGS]
    out_path = config.DATA_DIR / "listings.json"
    out_path.write_text(json.dumps([asdict(l) for l in listings], indent=2))
    print(f"Wrote {len(listings)} listings → {out_path}")


if __name__ == "__main__":
    main()
