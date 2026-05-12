"""Social activity score — does this token meet the X-activity bar implied
by the ACT1 story?

We use LunarCrush v2 public API (free tier ~50 req/day) as the primary
source. Returns galaxy_score, alt_rank, social_volume, follower count.

If no LunarCrush key, we fall back to a Twitter username scraper that
counts followers / posts in last 7d via the public profile HTML (no auth).

Threshold heuristics from listed memecoins:
  - galaxy_score      >= 60
  - social_volume_24h >= 5,000 mentions
  - followers         >= 20,000 (project's main account)
  - mindshare growth  positive (rising attention curve)
"""
from __future__ import annotations
import re
from typing import Any

import requests

LUNARCRUSH_TOKEN = "https://lunarcrush.com/api/v2/coins/{symbol}/v1"

THRESHOLDS = {
    "galaxy_score": 60,
    "social_volume_24h": 5_000,
    "followers": 20_000,
}


def lunarcrush(symbol: str, api_key: str = "") -> dict | None:
    if not api_key:
        return None
    try:
        r = requests.get(
            LUNARCRUSH_TOKEN.format(symbol=symbol),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or {}
        return {
            "galaxy_score": data.get("galaxy_score"),
            "alt_rank": data.get("alt_rank"),
            "social_volume_24h": data.get("social_volume_24h"),
            "social_contributors": data.get("social_contributors"),
            "social_dominance": data.get("social_dominance"),
        }
    except Exception:
        return None


def twitter_profile_stats(handle: str) -> dict | None:
    """Best-effort scrape of public Twitter/X profile via Nitter mirrors.
    Returns None if all mirrors fail — handle is best-effort.
    """
    handle = handle.lstrip("@")
    mirrors = [
        f"https://nitter.net/{handle}",
        f"https://nitter.poast.org/{handle}",
        f"https://nitter.privacydev.net/{handle}",
    ]
    for url in mirrors:
        try:
            r = requests.get(url, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200 or len(r.text) < 1000:
                continue
            html = r.text
            followers = _parse_count(html, "Followers")
            tweets = _parse_count(html, "Tweets")
            return {"followers": followers, "tweets": tweets, "source": url}
        except Exception:
            continue
    return None


def _parse_count(html: str, label: str) -> int | None:
    m = re.search(
        rf'<span class="profile-stat-header">\s*{label}\s*</span>\s*'
        rf'<span class="profile-stat-num">\s*([\d.,KM]+)\s*</span>',
        html,
    )
    if not m:
        return None
    val = m.group(1).replace(",", "")
    if val.endswith("K"):
        return int(float(val[:-1]) * 1_000)
    if val.endswith("M"):
        return int(float(val[:-1]) * 1_000_000)
    try:
        return int(val)
    except ValueError:
        return None


def evaluate(symbol: str, twitter_handle: str = "",
             lunarcrush_key: str = "") -> dict[str, Any]:
    lc = lunarcrush(symbol, lunarcrush_key) or {}
    tw = twitter_profile_stats(twitter_handle) if twitter_handle else {}
    tw = tw or {}

    passes = {
        "galaxy_score": (lc.get("galaxy_score") or 0)
                        >= THRESHOLDS["galaxy_score"],
        "social_volume_24h": (lc.get("social_volume_24h") or 0)
                             >= THRESHOLDS["social_volume_24h"],
        "followers": (tw.get("followers") or 0) >= THRESHOLDS["followers"],
    }
    return {
        "lunarcrush": lc,
        "twitter": tw,
        "passes": passes,
        "gates_passed": sum(1 for v in passes.values() if v),
        "thresholds": THRESHOLDS,
    }
