"""News data source adapters.

Breaking news can move prediction markets instantly. We monitor multiple news
feeds for keywords relevant to active prediction markets (elections, court
rulings, natural disasters, etc.).

Strategy: Poll NewsAPI and GDELT rapidly for keyword matches. When breaking
news hits, assess sentiment and impact, then trade before markets adjust.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import aiohttp

from src.core.base import BaseDataSource
from src.core.event_bus import EventBus
from src.core.models import DataSignal, SignalType


class NewsAPISource(BaseDataSource):
    """NewsAPI.org adapter - aggregates news from 80,000+ sources."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("newsapi", event_bus, config)
        self.base_url = config.get("base_url", "https://newsapi.org/v2")
        self.api_key = config.get("api_key", "")
        self.tracked_keywords = config.get("tracked_keywords", [])
        self._session: aiohttp.ClientSession | None = None
        self._seen_articles: set[str] = set()  # Track seen article hashes
        self._max_seen = 10000

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        self._session = aiohttp.ClientSession(timeout=timeout)
        if not self.api_key:
            self.logger.warning("NewsAPI key not set — source disabled")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def poll(self) -> list[DataSignal]:
        if not self._session or not self.api_key:
            return []

        signals: list[DataSignal] = []

        # Poll top headlines for breaking news
        try:
            headline_signals = await self._poll_headlines()
            signals.extend(headline_signals)
        except Exception:
            self.logger.exception("Error polling headlines")

        # Poll for keyword-specific news
        for keyword in self.tracked_keywords:
            try:
                kw_signals = await self._poll_keyword(keyword)
                signals.extend(kw_signals)
            except Exception:
                self.logger.exception(f"Error polling keyword: {keyword}")

        return signals

    async def _poll_headlines(self) -> list[DataSignal]:
        """Poll top breaking headlines."""
        signals: list[DataSignal] = []
        url = f"{self.base_url}/top-headlines"
        params = {"country": "us", "apiKey": self.api_key, "pageSize": 20}

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return signals
            data = await resp.json()

        for article in data.get("articles", []):
            signal = self._process_article(article, "headlines")
            if signal:
                signals.append(signal)

        return signals

    async def _poll_keyword(self, keyword: str) -> list[DataSignal]:
        """Poll for articles matching a keyword."""
        signals: list[DataSignal] = []
        url = f"{self.base_url}/everything"
        params = {
            "q": keyword,
            "apiKey": self.api_key,
            "sortBy": "publishedAt",
            "pageSize": 10,
            "language": "en",
        }

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return signals
            data = await resp.json()

        for article in data.get("articles", []):
            signal = self._process_article(article, f"keyword:{keyword}")
            if signal:
                signals.append(signal)

        return signals

    def _process_article(self, article: dict[str, Any], source_tag: str) -> DataSignal | None:
        """Process a single article, returning a signal if it's new."""
        title = article.get("title", "")
        url = article.get("url", "")

        # Deduplicate
        article_hash = hashlib.md5(f"{title}{url}".encode()).hexdigest()
        if article_hash in self._seen_articles:
            return None
        self._seen_articles.add(article_hash)

        # Trim seen set if too large
        if len(self._seen_articles) > self._max_seen:
            # Remove oldest half (set doesn't preserve order, so just clear half)
            to_remove = list(self._seen_articles)[:self._max_seen // 2]
            for h in to_remove:
                self._seen_articles.discard(h)

        # Determine if this is likely breaking/important
        description = article.get("description", "") or ""
        content = article.get("content", "") or ""
        full_text = f"{title} {description} {content}".lower()

        # Score importance based on keyword matches
        importance_keywords = [
            "breaking", "just in", "urgent", "alert",
            "winner", "declared", "ruling", "verdict",
            "hurricane", "earthquake", "tornado", "flood",
            "rate decision", "fed", "supreme court",
            "championship", "final score", "upset",
        ]
        importance_score = sum(1 for kw in importance_keywords if kw in full_text)
        confidence = min(0.5 + (importance_score * 0.1), 0.95)

        return DataSignal(
            source="newsapi",
            signal_type=SignalType.NEWS_BREAKING if importance_score >= 2 else SignalType.NEWS_SENTIMENT,
            event_id=article_hash,
            data={
                "title": title,
                "description": description,
                "url": url,
                "source": article.get("source", {}).get("name", ""),
                "published_at": article.get("publishedAt", ""),
                "source_tag": source_tag,
                "importance_score": importance_score,
            },
            confidence=confidence,
            raw_payload=article,
        )


class GDELTSource(BaseDataSource):
    """GDELT Project adapter - real-time global event monitoring.

    GDELT monitors news worldwide and updates every 15 minutes. Free, no key needed.
    Useful for geopolitical events that may affect prediction markets.
    """

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("gdelt", event_bus, config)
        self.base_url = config.get("base_url", "https://api.gdeltproject.org/api/v2")
        self.tracked_keywords = config.get("tracked_keywords", [])
        self._session: aiohttp.ClientSession | None = None
        self._seen_urls: set[str] = set()

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def poll(self) -> list[DataSignal]:
        if not self._session:
            return []

        signals: list[DataSignal] = []
        for keyword in self.tracked_keywords:
            try:
                kw_signals = await self._poll_keyword(keyword)
                signals.extend(kw_signals)
            except Exception:
                self.logger.exception(f"Error polling GDELT for: {keyword}")

        return signals

    async def _poll_keyword(self, keyword: str) -> list[DataSignal]:
        signals: list[DataSignal] = []
        url = f"{self.base_url}/doc/doc"
        params = {
            "query": keyword,
            "mode": "artlist",
            "maxrecords": 10,
            "format": "json",
            "sort": "datedesc",
        }

        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return signals
                data = await resp.json(content_type=None)
        except Exception:
            return signals

        articles = data.get("articles", [])
        for article in articles:
            article_url = article.get("url", "")
            if article_url in self._seen_urls:
                continue
            self._seen_urls.add(article_url)

            title = article.get("title", "")
            signals.append(DataSignal(
                source="gdelt",
                signal_type=SignalType.NEWS_BREAKING,
                event_id=hashlib.md5(article_url.encode()).hexdigest(),
                data={
                    "title": title,
                    "url": article_url,
                    "domain": article.get("domain", ""),
                    "language": article.get("language", ""),
                    "source_country": article.get("sourcecountry", ""),
                    "keyword": keyword,
                    "seendate": article.get("seendate", ""),
                },
                confidence=0.7,
            ))

        return signals
