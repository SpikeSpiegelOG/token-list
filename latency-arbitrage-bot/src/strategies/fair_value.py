"""Fair value calculator for prediction market events.

This module estimates the "true" probability of an event based on
data signals. The gap between fair value and market price is our edge.

For different signal types:
- Sports scores: Use game theory / win probability models
- Weather: Use ensemble forecast probabilities
- News: Use sentiment analysis + historical correlation
- Crypto: Use price momentum and options-implied probabilities
"""

from __future__ import annotations

import logging
import math
from typing import Any

from src.core.models import DataSignal, MarketState, SignalType

logger = logging.getLogger(__name__)


class FairValueCalculator:
    """Estimates fair probability for prediction market outcomes."""

    def calculate(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value probability based on signal type.

        Returns probability between 0 and 1, or None if unable to calculate.
        """
        handler = self._handlers.get(signal.signal_type)
        if handler:
            return handler(self, signal, market)
        return None

    def _calc_sports_score(self, signal: DataSignal, market: MarketState) -> float | None:
        """Estimate win probability based on current scores.

        Uses a simplified model based on score differential and game progress.
        For production, you'd want sport-specific win probability models
        (e.g., NFL win probability curves, NBA pace-adjusted models).
        """
        data = signal.data
        scores = data.get("scores", {})
        game_state = data.get("game_state", "")
        detail = data.get("detail", "")

        if not scores or game_state not in ("in", "post"):
            return None

        # Extract home and away scores
        home_score = 0
        away_score = 0
        for team_data in scores.values():
            if team_data.get("home_away") == "home":
                home_score = team_data.get("score", 0)
            else:
                away_score = team_data.get("score", 0)

        diff = home_score - away_score

        if game_state == "post":
            # Game is over — probability is 0 or 1
            if diff > 0:
                return 0.95  # Home team won (slight uncertainty for corrections)
            elif diff < 0:
                return 0.05
            else:
                return 0.50  # Tie/OT

        # During game: estimate based on score differential
        # This is a simplified logistic model
        # Better models: FiveThirtyEight-style, considering time remaining
        sport = data.get("sport", "")

        # Sport-specific scaling factors for score differential
        if "football" in sport:
            scale = 4.0  # NFL: each point matters a lot
        elif "basketball" in sport:
            scale = 12.0  # NBA: larger score swings, less decisive per point
        elif "baseball" in sport:
            scale = 2.0  # MLB: runs are very impactful
        elif "hockey" in sport:
            scale = 2.5  # NHL: goals are rare and impactful
        else:
            scale = 5.0  # Default

        # Logistic function: P(home_win) = 1 / (1 + exp(-diff/scale))
        prob = 1.0 / (1.0 + math.exp(-diff / scale))

        # Adjust toward extremes as game progresses
        # (larger leads late in game are more decisive)
        # Simple proxy: if "4th quarter" or "9th inning" in detail, amplify
        if any(late in detail.lower() for late in ["4th", "9th", "3rd period", "overtime"]):
            # Push probability further from 0.5
            prob = 0.5 + (prob - 0.5) * 1.3
            prob = max(0.02, min(0.98, prob))

        return round(prob, 4)

    def _calc_sports_status(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for game status changes (game start, end, etc.)."""
        data = signal.data
        new_status = data.get("new_status", "")
        scores = data.get("scores", {})

        if new_status == "post":
            # Game ended — calculate winner probability
            home_score = 0
            away_score = 0
            for team_data in scores.values():
                if team_data.get("home_away") == "home":
                    home_score = team_data.get("score", 0)
                else:
                    away_score = team_data.get("score", 0)

            if home_score > away_score:
                return 0.98
            elif away_score > home_score:
                return 0.02
            return 0.50

        return None

    def _calc_weather_temp(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for temperature-based weather markets.

        For Kalshi temperature markets: "Will the high in NYC be above X°F?"
        Uses current observation + trend to estimate probability.
        """
        data = signal.data
        temp_c = data.get("temperature_c")
        delta_c = data.get("delta_c", 0)

        if temp_c is None:
            return None

        # Convert to Fahrenheit for Kalshi markets (they use F)
        temp_f = temp_c * 9 / 5 + 32

        # Parse market question to find the temperature threshold
        question = market.question.lower()
        threshold = self._extract_number(question)
        if threshold is None:
            return None

        # Simple probability model based on current temp vs threshold
        # With trend adjustment
        diff = temp_f - threshold
        trend_adjustment = delta_c * 9 / 5 * 0.5  # Trend contributes partially

        adjusted_diff = diff + trend_adjustment

        # Use logistic function with temperature uncertainty (±3°F typical)
        uncertainty = 3.0
        prob = 1.0 / (1.0 + math.exp(-adjusted_diff / uncertainty))

        return round(prob, 4)

    def _calc_weather_wind(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for wind-based markets."""
        data = signal.data
        wind_speed = data.get("wind_speed_kmh")
        if wind_speed is None:
            return None

        # Similar logistic model for wind thresholds
        question = market.question.lower()
        threshold = self._extract_number(question)
        if threshold is None:
            return None

        diff = wind_speed - threshold
        prob = 1.0 / (1.0 + math.exp(-diff / 5.0))
        return round(prob, 4)

    def _calc_weather_alert(self, signal: DataSignal, market: MarketState) -> float | None:
        """Weather alerts strongly suggest extreme weather outcomes."""
        data = signal.data
        event_type = data.get("event", "").lower()

        # Weather alerts strongly shift probabilities
        if any(severe in event_type for severe in ["hurricane", "tornado", "blizzard"]):
            return 0.85  # High probability of extreme weather outcome
        elif any(moderate in event_type for moderate in ["storm", "flood", "wind"]):
            return 0.70
        elif any(mild in event_type for mild in ["advisory", "watch"]):
            return 0.55

        return None

    def _calc_crypto_price(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for crypto price prediction markets.

        For markets like "Will BTC be above $X at time Y?"
        Uses current price + momentum as signals.
        """
        data = signal.data
        price = data.get("price")
        pct_change = data.get("pct_change", 0)

        if price is None:
            return None

        question = market.question.lower()
        threshold = self._extract_number(question)
        if threshold is None:
            return None

        # How far is the current price from the threshold?
        diff_pct = (price - threshold) / threshold * 100

        # Momentum adjustment
        momentum = pct_change * 0.3  # Partial extrapolation

        adjusted_diff = diff_pct + momentum

        # Crypto is volatile, use wider uncertainty
        prob = 1.0 / (1.0 + math.exp(-adjusted_diff / 2.0))
        return round(prob, 4)

    def _calc_news_breaking(self, signal: DataSignal, market: MarketState) -> float | None:
        """Breaking news shifts probabilities based on content analysis."""
        data = signal.data
        importance = data.get("importance_score", 0)
        title = data.get("title", "").lower()
        question = market.question.lower()

        if importance < 2:
            return None  # Not important enough to shift markets

        # Basic sentiment/direction analysis from title
        positive_words = ["win", "victory", "approve", "pass", "agree", "success", "record"]
        negative_words = ["lose", "defeat", "reject", "fail", "crash", "collapse", "deny"]

        pos_count = sum(1 for w in positive_words if w in title)
        neg_count = sum(1 for w in negative_words if w in title)

        if pos_count > neg_count:
            # Positive news — shift up from current market price
            return min(market.yes_price + 0.05 * importance, 0.95)
        elif neg_count > pos_count:
            # Negative news — shift down
            return max(market.yes_price - 0.05 * importance, 0.05)

        return None

    def _calc_news_sentiment(self, signal: DataSignal, market: MarketState) -> float | None:
        """Sentiment-based fair value (lower confidence than breaking news)."""
        # Similar to breaking but with lower confidence
        result = self._calc_news_breaking(signal, market)
        if result is not None:
            # Moderate the shift for sentiment vs breaking
            diff = result - market.yes_price
            return market.yes_price + diff * 0.5
        return None

    @staticmethod
    def _extract_number(text: str) -> float | None:
        """Extract a numeric threshold from a market question."""
        import re
        # Match patterns like "above 75", "over 100", "below 32"
        patterns = [
            r'(?:above|over|more than|greater than|exceed)\s*\$?([\d,]+\.?\d*)',
            r'(?:below|under|less than|fewer than)\s*\$?([\d,]+\.?\d*)',
            r'\$?([\d,]+\.?\d*)\s*(?:degrees|°|fahrenheit|celsius)',
            r'\$?([\d,]+\.?\d*)',  # Fallback: just find a number
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    # Handler mapping
    _handlers = {
        SignalType.SPORTS_SCORE: _calc_sports_score,
        SignalType.SPORTS_STATUS: _calc_sports_status,
        SignalType.WEATHER_TEMPERATURE: _calc_weather_temp,
        SignalType.WEATHER_WIND: _calc_weather_wind,
        SignalType.WEATHER_ALERT: _calc_weather_alert,
        SignalType.CRYPTO_PRICE: _calc_crypto_price,
        SignalType.NEWS_BREAKING: _calc_news_breaking,
        SignalType.NEWS_SENTIMENT: _calc_news_sentiment,
    }
