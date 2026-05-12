"""Poll the Binance announcement CMS endpoint for new memecoin listings.

The announcement HTML often goes live a few seconds before the official tweet,
so polling the JSON endpoint at ~3s cadence is the fastest legal way to catch
listings without an X firehose subscription.
"""
from __future__ import annotations
import json
import time

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402

LISTING_API = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
POLL_INTERVAL = 3.0  # seconds


def poll_once() -> int:
    r = requests.get(LISTING_API, params={
        "type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 10,
    }, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    r.raise_for_status()
    new = 0
    data = r.json().get("data") or {}
    articles = data.get("articles") or (
        (data.get("catalogs") or [{}])[0].get("articles", [])
    )
    for art in articles:
        code = art.get("code")
        if not code:
            continue
        with db.conn() as c:
            existing = c.execute(
                "SELECT 1 FROM binance_announcements WHERE code=?", (code,)
            ).fetchone()
            if existing:
                continue
            url = f"https://www.binance.com/en/support/announcement/{code}"
            c.execute(
                "INSERT INTO binance_announcements"
                "(code, title, catalog_id, release_date, url) "
                "VALUES (?, ?, ?, ?, ?)",
                (code, art["title"], art.get("catalogId", 48),
                 int(art.get("releaseDate", 0)) // 1000, url),
            )
        db.add_alert(
            severity="INFO", kind="announcement", subject=art["title"][:60],
            message=f"NEW LISTING ANNOUNCEMENT: {art['title']}",
            payload=json.dumps({"url": url, "code": code}),
        )
        new += 1
    return new


def loop() -> None:
    db.init()
    while True:
        try:
            n = poll_once()
            if n:
                print(f"+{n} new announcements")
        except Exception as e:
            print(f"err: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    loop()
