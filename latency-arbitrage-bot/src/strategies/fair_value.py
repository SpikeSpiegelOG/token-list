"""Fair value calculator for prediction market events.

This module estimates the "true" probability of an event based on
data signals. The gap between fair value and market price is our edge.

Models:
- Moneyline: Win probability from score differential + time remaining
- Spread: Probability of winning by > N points, using current margin + pace
- Total (O/U): Probability of combined score exceeding N, using pace projection
- Weather: Logistic models with trend adjustment
- Crypto: Price momentum with volatility adjustment
- News: Sentiment-based probability shifts
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from src.core.models import DataSignal, MarketState, MarketType, SignalType

logger = logging.getLogger(__name__)


# Sport-specific constants for modeling
SPORT_CONFIG = {
    "football/nfl": {
        "scale": 4.0,          # Score differential impact
        "total_periods": 4,    # Quarters
        "avg_total": 46.0,     # Average combined score
        "comeback_factor": 0.3,  # Comeback rate multiplier
        "late_periods": ["4th", "overtime", "ot"],
    },
    "basketball/nba": {
        "scale": 12.0,
        "total_periods": 4,
        "avg_total": 225.0,
        "comeback_factor": 0.5,  # NBA leads are less safe
        "late_periods": ["4th", "overtime", "ot"],
    },
    "baseball/mlb": {
        "scale": 2.0,
        "total_periods": 9,
        "avg_total": 8.5,
        "comeback_factor": 0.25,
        "late_periods": ["9th", "extra", "extras"],
    },
    "hockey/nhl": {
        "scale": 2.5,
        "total_periods": 3,
        "avg_total": 6.0,
        "comeback_factor": 0.35,
        "late_periods": ["3rd", "overtime", "ot"],
    },
    "football/college-football": {
        "scale": 5.0,
        "total_periods": 4,
        "avg_total": 52.0,
        "comeback_factor": 0.3,
        "late_periods": ["4th", "overtime", "ot"],
    },
    "basketball/mens-college-basketball": {
        "scale": 10.0,
        "total_periods": 2,
        "avg_total": 145.0,
        "comeback_factor": 0.45,
        "late_periods": ["2nd", "overtime", "ot"],
    },
}


def _estimate_game_progress(detail: str, sport: str) -> float:
    """Estimate game progress (0.0 = start, 1.0 = end) from ESPN detail string.

    Examples: "4th 2:30", "End of 3rd Quarter", "Halftime", "9th Inning"
    """
    d = detail.lower()
    config = SPORT_CONFIG.get(sport, {})
    total_periods = config.get("total_periods", 4)

    if "final" in d or "end" in d:
        return 1.0
    if "halftime" in d or "half" in d:
        return 0.5

    # Try to extract period/quarter number
    period_match = re.search(r'(\d+)(?:st|nd|rd|th)', d)
    if period_match:
        period = int(period_match.group(1))
        # Estimate progress within the period (rough: assume midpoint)
        progress = (period - 0.5) / total_periods
        return min(progress, 0.99)

    if "overtime" in d or "ot" in d:
        return 0.95

    return 0.5  # Default: assume mid-game


class FairValueCalculator:
    """Estimates fair probability for prediction market outcomes."""

    def calculate(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value probability based on signal and market type.

        Returns probability between 0 and 1, or None if unable to calculate.
        """
        handler = self._handlers.get(signal.signal_type)
        if handler:
            return handler(self, signal, market)
        return None

    # ---- Moneyline (Win Probability) ----

    def _calc_sports_score(self, signal: DataSignal, market: MarketState) -> float | None:
        """Estimate win probability based on current scores and time remaining.

        Improved model using game progress for more accurate late-game estimates.
        """
        data = signal.data
        game_state = data.get("game_state", "")
        detail = data.get("detail", "")
        sport = data.get("sport", "")

        if game_state == "post":
            return self._calc_final_moneyline(data)

        if game_state != "in":
            return None

        home_score = data.get("home_score", 0)
        away_score = data.get("away_score", 0)

        # Fall back to extracting from scores dict if direct fields missing
        if home_score == 0 and away_score == 0:
            scores = data.get("scores", {})
            for team_data in scores.values():
                if team_data.get("home_away") == "home":
                    home_score = team_data.get("score", 0)
                else:
                    away_score = team_data.get("score", 0)

        diff = home_score - away_score

        config = SPORT_CONFIG.get(sport, {"scale": 5.0, "comeback_factor": 0.3, "late_periods": []})
        scale = config["scale"]
        late_periods = config["late_periods"]

        # Base logistic model
        prob = 1.0 / (1.0 + math.exp(-diff / scale))

        # Adjust based on game progress — leads become more decisive over time
        progress = _estimate_game_progress(detail, sport)
        if progress > 0.1:
            # As game progresses, push probability toward extremes
            amplification = 1.0 + progress * 1.0
            prob = 0.5 + (prob - 0.5) * amplification

        # Extra amplification in late-game situations
        if any(late in detail.lower() for late in late_periods):
            prob = 0.5 + (prob - 0.5) * 1.3

        return round(max(0.02, min(0.98, prob)), 4)

    def _calc_final_moneyline(self, data: dict[str, Any]) -> float:
        """Calculate definitive probability when game is final."""
        home_score = data.get("home_score", 0)
        away_score = data.get("away_score", 0)

        # Fall back to scores dict
        if home_score == 0 and away_score == 0:
            scores = data.get("scores", {})
            for team_data in scores.values():
                if team_data.get("home_away") == "home":
                    home_score = team_data.get("score", 0)
                else:
                    away_score = team_data.get("score", 0)

        if home_score > away_score:
            return 0.98  # Home won
        elif away_score > home_score:
            return 0.02  # Away won
        return 0.50  # Tie

    # ---- Spread (Margin of Victory) ----

    def _calc_sports_spread(self, signal: DataSignal, market: MarketState) -> float | None:
        """Estimate probability of home team winning by more than the spread line.

        For a market like "Chiefs -3.5": probability that Chiefs win by > 3.5 points.
        Uses current margin, pace, and time remaining.
        """
        data = signal.data
        game_state = data.get("game_state", "")
        sport = data.get("sport", "")
        detail = data.get("detail", "")

        spread_line = market.spread_line
        if spread_line is None:
            return None

        current_diff = data.get("score_differential", 0)  # home - away

        if game_state == "post":
            # Game over — definitive
            if current_diff > spread_line:
                return 0.98  # Home covered the spread
            elif current_diff < spread_line:
                return 0.02
            return 0.50  # Push

        if game_state != "in":
            return None

        config = SPORT_CONFIG.get(sport, {"scale": 5.0, "avg_total": 50.0})
        progress = _estimate_game_progress(detail, sport)

        # How far is current margin from the spread?
        margin_vs_spread = current_diff - spread_line

        # Uncertainty decreases as game progresses
        remaining_factor = max(0.1, 1.0 - progress)
        uncertainty = config["scale"] * remaining_factor

        # Logistic model: probability of covering
        prob = 1.0 / (1.0 + math.exp(-margin_vs_spread / uncertainty))

        return round(max(0.02, min(0.98, prob)), 4)

    # ---- Total / Over-Under ----

    def _calc_sports_total(self, signal: DataSignal, market: MarketState) -> float | None:
        """Estimate probability of combined score exceeding the total line.

        Projects final total based on current pace and time remaining.
        """
        data = signal.data
        game_state = data.get("game_state", "")
        sport = data.get("sport", "")
        detail = data.get("detail", "")

        total_line = market.total_line
        if total_line is None:
            return None

        combined = data.get("combined_total", 0)

        if game_state == "post":
            # Game over — definitive
            if combined > total_line:
                return 0.98  # Over hit
            elif combined < total_line:
                return 0.02  # Under hit
            return 0.50  # Push

        if game_state != "in":
            return None

        config = SPORT_CONFIG.get(sport, {"avg_total": 50.0, "scale": 5.0})
        progress = _estimate_game_progress(detail, sport)

        if progress < 0.05:
            return None  # Not enough data yet

        # Project final total based on current pace
        projected_total = combined / progress if progress > 0 else config["avg_total"]

        # Blend projection with league average (regress to mean early in game)
        avg_total = config["avg_total"]
        weight_current = min(progress * 1.5, 1.0)  # Trust pace more as game progresses
        blended_projection = projected_total * weight_current + avg_total * (1.0 - weight_current)

        # How far is projection from the line?
        diff = blended_projection - total_line

        # Uncertainty decreases as game progresses
        remaining_factor = max(0.1, 1.0 - progress)
        uncertainty = config["scale"] * remaining_factor * 2  # Totals have wider variance

        prob = 1.0 / (1.0 + math.exp(-diff / uncertainty))

        return round(max(0.02, min(0.98, prob)), 4)

    # ---- Game Status Changes ----

    def _calc_sports_status(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for game status changes."""
        data = signal.data
        new_status = data.get("new_status", "")

        if new_status == "post":
            # Game ended — route to appropriate model based on market type
            if market.market_type == MarketType.SPREAD:
                return self._calc_sports_spread(signal, market)
            elif market.market_type == MarketType.TOTAL:
                return self._calc_sports_total(signal, market)
            else:
                return self._calc_final_moneyline(data)

        return None

    # ---- Weather Models ----

    def _calc_weather_temp(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for temperature-based weather markets."""
        data = signal.data
        temp_c = data.get("temperature_c")
        delta_c = data.get("delta_c", 0)

        if temp_c is None:
            return None

        temp_f = temp_c * 9 / 5 + 32
        question = market.question.lower()
        threshold = self._extract_number(question)
        if threshold is None:
            return None

        diff = temp_f - threshold
        trend_adjustment = delta_c * 9 / 5 * 0.5
        adjusted_diff = diff + trend_adjustment
        uncertainty = 3.0
        prob = 1.0 / (1.0 + math.exp(-adjusted_diff / uncertainty))

        return round(prob, 4)

    def _calc_weather_wind(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for wind-based markets."""
        data = signal.data
        wind_speed = data.get("wind_speed_kmh")
        if wind_speed is None:
            return None

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

        if any(severe in event_type for severe in ["hurricane", "tornado", "blizzard"]):
            return 0.85
        elif any(moderate in event_type for moderate in ["storm", "flood", "wind"]):
            return 0.70
        elif any(mild in event_type for mild in ["advisory", "watch"]):
            return 0.55

        return None

    # ---- Crypto Models ----

    def _calc_crypto_price(self, signal: DataSignal, market: MarketState) -> float | None:
        """Calculate fair value for crypto price prediction markets."""
        data = signal.data
        price = data.get("price")
        pct_change = data.get("pct_change", 0)

        if price is None:
            return None

        question = market.question.lower()
        threshold = self._extract_number(question)
        if threshold is None:
            return None

        diff_pct = (price - threshold) / threshold * 100
        momentum = pct_change * 0.3
        adjusted_diff = diff_pct + momentum
        prob = 1.0 / (1.0 + math.exp(-adjusted_diff / 2.0))
        return round(prob, 4)

    # ---- News Models ----

    def _calc_news_breaking(self, signal: DataSignal, market: MarketState) -> float | None:
        """Breaking news shifts probabilities based on content analysis."""
        data = signal.data
        importance = data.get("importance_score", 0)
        title = data.get("title", "").lower()

        if importance < 2:
            return None

        positive_words = ["win", "victory", "approve", "pass", "agree", "success", "record"]
        negative_words = ["lose", "defeat", "reject", "fail", "crash", "collapse", "deny"]

        pos_count = sum(1 for w in positive_words if w in title)
        neg_count = sum(1 for w in negative_words if w in title)

        if pos_count > neg_count:
            return min(market.yes_price + 0.05 * importance, 0.95)
        elif neg_count > pos_count:
            return max(market.yes_price - 0.05 * importance, 0.05)

        return None

    def _calc_news_sentiment(self, signal: DataSignal, market: MarketState) -> float | None:
        """Sentiment-based fair value (lower confidence than breaking news)."""
        result = self._calc_news_breaking(signal, market)
        if result is not None:
            diff = result - market.yes_price
            return market.yes_price + diff * 0.5
        return None

    # ---- Utilities ----

    @staticmethod
    def _extract_number(text: str) -> float | None:
        """Extract a numeric threshold from a market question."""
        patterns = [
            r'(?:above|over|more than|greater than|exceed)\s*\$?([\d,]+\.?\d*)',
            r'(?:below|under|less than|fewer than)\s*\$?([\d,]+\.?\d*)',
            r'\$?([\d,]+\.?\d*)\s*(?:degrees|°|fahrenheit|celsius)',
            r'\$?([\d,]+\.?\d*)',
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
        SignalType.SPORTS_SPREAD: _calc_sports_spread,
        SignalType.SPORTS_TOTAL: _calc_sports_total,
        SignalType.WEATHER_TEMPERATURE: _calc_weather_temp,
        SignalType.WEATHER_WIND: _calc_weather_wind,
        SignalType.WEATHER_ALERT: _calc_weather_alert,
        SignalType.CRYPTO_PRICE: _calc_crypto_price,
        SignalType.NEWS_BREAKING: _calc_news_breaking,
        SignalType.NEWS_SENTIMENT: _calc_news_sentiment,
    }
