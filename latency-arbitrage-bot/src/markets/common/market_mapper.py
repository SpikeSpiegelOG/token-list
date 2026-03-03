"""Market mapper - links data signals to relevant prediction markets.

This is a critical component. When we get a data signal (e.g., "Lakers scored"),
we need to quickly find all prediction markets that could be affected by this
signal (e.g., "Will Lakers win tonight?", "Will Lakers score over 110?").

The mapper maintains a registry of active markets and their associations with
data signals. It can be updated dynamically as new markets open/close.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.core.models import DataSignal, MarketState, Platform, SignalType


@dataclass
class MarketMapping:
    """A mapping between a data signal pattern and a prediction market."""
    market: MarketState
    signal_types: list[SignalType]
    keywords: list[str]  # Keywords that must match in the signal data
    weight: float = 1.0  # How relevant this market is to matching signals
    last_matched: int = 0
    match_count: int = 0


class MarketMapper:
    """Maps incoming data signals to relevant prediction markets."""

    def __init__(self) -> None:
        self._mappings: list[MarketMapping] = []
        self._market_index: dict[str, MarketMapping] = {}  # market_id -> mapping
        # Pre-built keyword patterns for fast matching
        self._keyword_patterns: dict[str, re.Pattern] = {}

    def register_market(
        self,
        market: MarketState,
        signal_types: list[SignalType],
        keywords: list[str],
        weight: float = 1.0,
    ) -> None:
        """Register a market and its signal associations."""
        mapping = MarketMapping(
            market=market,
            signal_types=signal_types,
            keywords=[kw.lower() for kw in keywords],
            weight=weight,
        )
        self._mappings.append(mapping)
        self._market_index[f"{market.platform.value}:{market.market_id}"] = mapping

        # Pre-compile keyword patterns
        for kw in keywords:
            if kw.lower() not in self._keyword_patterns:
                self._keyword_patterns[kw.lower()] = re.compile(re.escape(kw.lower()))

    def unregister_market(self, platform: Platform, market_id: str) -> None:
        """Remove a market from the mapper."""
        key = f"{platform.value}:{market_id}"
        if key in self._market_index:
            mapping = self._market_index[key]
            self._mappings.remove(mapping)
            del self._market_index[key]

    def find_markets(self, signal: DataSignal) -> list[tuple[MarketState, float]]:
        """Find all markets relevant to a data signal.

        Returns list of (market, relevance_score) tuples, sorted by relevance.
        """
        results: list[tuple[MarketState, float]] = []

        # Build searchable text from signal data
        search_text = self._signal_to_text(signal).lower()

        for mapping in self._mappings:
            # Check signal type match
            if signal.signal_type not in mapping.signal_types:
                continue

            # Check keyword match
            score = 0.0
            matched_keywords = 0
            for kw in mapping.keywords:
                pattern = self._keyword_patterns.get(kw)
                if pattern and pattern.search(search_text):
                    matched_keywords += 1
                    score += 1.0

            if matched_keywords > 0:
                # Normalize score
                score = (score / len(mapping.keywords)) * mapping.weight
                mapping.last_matched = int(time.time() * 1000)
                mapping.match_count += 1
                results.append((mapping.market, score))

        # Sort by relevance score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _signal_to_text(self, signal: DataSignal) -> str:
        """Convert a signal's data to searchable text."""
        parts = [signal.source, signal.signal_type.value, signal.event_id]
        data = signal.data
        for key, value in data.items():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                parts.extend(str(v) for v in value.values() if isinstance(v, str))
        return " ".join(parts)

    def auto_map_from_question(self, market: MarketState) -> None:
        """Automatically infer signal types and keywords from market question.

        This is a heuristic approach — it parses the market question to figure
        out what data sources might be relevant.
        """
        question = market.question.lower()

        signal_types: list[SignalType] = []
        keywords: list[str] = []

        # Sports detection
        sports_teams = self._extract_sports_entities(question)
        if sports_teams:
            signal_types.extend([SignalType.SPORTS_SCORE, SignalType.SPORTS_STATUS])
            keywords.extend(sports_teams)

        # Weather detection
        weather_keywords = ["temperature", "rain", "snow", "hurricane", "tornado",
                          "wind", "weather", "degrees", "celsius", "fahrenheit"]
        if any(wk in question for wk in weather_keywords):
            signal_types.extend([SignalType.WEATHER_TEMPERATURE, SignalType.WEATHER_WIND, SignalType.WEATHER_ALERT])
            # Extract city names
            cities = self._extract_cities(question)
            keywords.extend(cities)
            keywords.extend([wk for wk in weather_keywords if wk in question])

        # Crypto detection
        crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "price"]
        if any(ck in question for ck in crypto_keywords):
            signal_types.append(SignalType.CRYPTO_PRICE)
            keywords.extend([ck for ck in crypto_keywords if ck in question])

        # News/politics detection
        news_keywords = ["election", "president", "vote", "congress", "supreme court",
                        "ruling", "legislation", "bill", "senate", "governor"]
        if any(nk in question for nk in news_keywords):
            signal_types.extend([SignalType.NEWS_BREAKING, SignalType.NEWS_SENTIMENT])
            keywords.extend([nk for nk in news_keywords if nk in question])

        if signal_types and keywords:
            self.register_market(market, signal_types, keywords)

    def _extract_sports_entities(self, text: str) -> list[str]:
        """Extract team names and sports terms from text."""
        # Common team name patterns
        nfl_teams = ["chiefs", "eagles", "49ers", "cowboys", "packers", "bills",
                    "ravens", "dolphins", "lions", "bengals", "jets", "patriots",
                    "steelers", "broncos", "raiders", "chargers", "texans", "colts",
                    "titans", "jaguars", "bears", "vikings", "saints", "falcons",
                    "buccaneers", "panthers", "cardinals", "rams", "seahawks", "commanders"]
        nba_teams = ["lakers", "celtics", "warriors", "bucks", "nuggets", "heat",
                    "suns", "76ers", "knicks", "nets", "clippers", "mavericks",
                    "grizzlies", "cavaliers", "thunder", "timberwolves", "kings",
                    "pelicans", "hawks", "bulls", "raptors", "rockets", "spurs",
                    "blazers", "jazz", "pacers", "pistons", "hornets", "magic", "wizards"]
        mlb_teams = ["yankees", "dodgers", "astros", "braves", "phillies", "padres",
                    "mets", "cubs", "red sox", "cardinals", "rangers", "orioles",
                    "twins", "mariners", "rays", "guardians", "brewers", "blue jays",
                    "giants", "reds", "tigers", "angels", "royals", "pirates",
                    "diamondbacks", "marlins", "nationals", "rockies", "white sox", "athletics"]

        all_teams = nfl_teams + nba_teams + mlb_teams
        found = [team for team in all_teams if team in text]

        # Also check for generic sports terms
        sports_terms = ["win", "score", "game", "match", "championship", "playoff",
                       "super bowl", "world series", "finals", "mvp"]
        found.extend([term for term in sports_terms if term in text])

        return found

    def _extract_cities(self, text: str) -> list[str]:
        """Extract city names from text."""
        cities = ["new york", "los angeles", "chicago", "miami", "dallas",
                 "houston", "phoenix", "philadelphia", "san antonio", "san diego",
                 "denver", "seattle", "boston", "atlanta", "washington",
                 "las vegas", "portland", "detroit", "minneapolis", "tampa"]
        return [city for city in cities if city in text]

    @property
    def registered_count(self) -> int:
        return len(self._mappings)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_mappings": len(self._mappings),
            "markets_by_platform": {
                "polymarket": sum(1 for m in self._mappings if m.market.platform == Platform.POLYMARKET),
                "kalshi": sum(1 for m in self._mappings if m.market.platform == Platform.KALSHI),
            },
            "top_matched": sorted(
                [{"market_id": m.market.market_id, "matches": m.match_count}
                 for m in self._mappings if m.match_count > 0],
                key=lambda x: x["matches"],
                reverse=True,
            )[:10],
        }
