"""Tests for fair value calculator."""

from src.core.models import DataSignal, MarketState, MarketType, Platform, SignalType
from src.strategies.fair_value import FairValueCalculator, _estimate_game_progress


def test_sports_score_home_leading():
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="game_1",
        data={
            "sport": "basketball/nba",
            "home_score": 105,
            "away_score": 95,
            "scores": {
                "LAL": {"score": 105, "home_away": "home"},
                "BOS": {"score": 95, "home_away": "away"},
            },
            "game_state": "in",
            "detail": "4th Quarter",
        },
    )
    market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="lakers_win",
        question="Will the Lakers win tonight?",
        yes_price=0.60,
        no_price=0.40,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.5  # Home team leading, should be >50%


def test_sports_game_over():
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="game_2",
        data={
            "sport": "football/nfl",
            "home_score": 31,
            "away_score": 28,
            "scores": {
                "KC": {"score": 31, "home_away": "home"},
                "PHI": {"score": 28, "home_away": "away"},
            },
            "game_state": "post",
            "detail": "Final",
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="kc_win",
        question="Will Chiefs win?",
        yes_price=0.50,
        no_price=0.50,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.90  # Game over, home team won


def test_crypto_price_above_threshold():
    calc = FairValueCalculator()
    signal = DataSignal(
        source="binance",
        signal_type=SignalType.CRYPTO_PRICE,
        event_id="btc_1",
        data={
            "symbol": "BTCUSDT",
            "price": 72000,
            "pct_change": 2.5,
        },
    )
    market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="btc_70k",
        question="Will Bitcoin be above $70000 at end of month?",
        yes_price=0.55,
        no_price=0.45,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.5  # Price is already above threshold


def test_extract_number():
    calc = FairValueCalculator()
    assert calc._extract_number("Will temperature be above 75 degrees?") == 75.0
    assert calc._extract_number("Will Bitcoin exceed $100,000?") == 100000.0
    assert calc._extract_number("Temperature over 32 fahrenheit") == 32.0


# ---- New tests for spread and total models ----

def test_spread_home_covering():
    """Home team leading by more than the spread."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SPREAD,
        event_id="game_spread_1",
        data={
            "sport": "football/nfl",
            "score_differential": 10,  # Home leading by 10
            "game_state": "in",
            "detail": "3rd Quarter",
            "home_score": 24,
            "away_score": 14,
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="kc_spread",
        question="Will Chiefs win by more than 3.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.SPREAD,
        spread_line=3.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.5  # Leading by 10 with spread of 3.5 → should cover


def test_spread_not_covering():
    """Home team leading but by less than the spread."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SPREAD,
        event_id="game_spread_2",
        data={
            "sport": "football/nfl",
            "score_differential": 1,  # Home leading by 1
            "game_state": "in",
            "detail": "4th Quarter 2:00",
            "home_score": 17,
            "away_score": 16,
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="kc_spread_2",
        question="Will Chiefs win by more than 7.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.SPREAD,
        spread_line=7.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv < 0.5  # Leading by 1 with spread of 7.5 → unlikely to cover


def test_spread_game_final():
    """Spread evaluation when game is final."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SPREAD,
        event_id="game_spread_3",
        data={
            "sport": "football/nfl",
            "score_differential": 7,
            "game_state": "post",
            "detail": "Final",
            "home_score": 28,
            "away_score": 21,
            "final_margin": 7,
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="kc_spread_3",
        question="Will Chiefs win by more than 3.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.SPREAD,
        spread_line=3.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.95  # Won by 7, spread was 3.5 → definitive cover


def test_total_over():
    """Combined score on pace to go over the line."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_TOTAL,
        event_id="game_total_1",
        data={
            "sport": "basketball/nba",
            "combined_total": 140,  # Already 140 at halftime
            "game_state": "in",
            "detail": "Halftime",
            "home_score": 72,
            "away_score": 68,
        },
    )
    market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="nba_total",
        question="Will total score be over 220.5?",
        yes_price=0.55,
        no_price=0.45,
        market_type=MarketType.TOTAL,
        total_line=220.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.5  # Pace of 280 at halftime → should be well over 220.5


def test_total_under():
    """Combined score on pace to go under the line."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_TOTAL,
        event_id="game_total_2",
        data={
            "sport": "football/nfl",
            "combined_total": 10,  # Only 10 points at halftime
            "game_state": "in",
            "detail": "Halftime",
            "home_score": 7,
            "away_score": 3,
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="nfl_total",
        question="Will total score be over 47.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.TOTAL,
        total_line=47.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv < 0.5  # Pace of 20 at halftime → unlikely to hit 47.5


def test_total_game_final_over():
    """Total evaluation when game is final — over."""
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_TOTAL,
        event_id="game_total_3",
        data={
            "sport": "football/nfl",
            "combined_total": 55,
            "game_state": "post",
            "detail": "Final",
            "home_score": 31,
            "away_score": 24,
            "final_total": 55,
        },
    )
    market = MarketState(
        platform=Platform.KALSHI,
        market_id="nfl_total_3",
        question="Will total score be over 47.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.TOTAL,
        total_line=47.5,
    )
    fv = calc.calculate(signal, market)
    assert fv is not None
    assert fv > 0.95  # Final total 55 > 47.5 → definitive over


def test_game_progress_estimation():
    """Test game progress estimation from ESPN detail strings."""
    # 4th quarter NFL
    assert _estimate_game_progress("4th 2:30", "football/nfl") > 0.8
    # Halftime
    assert _estimate_game_progress("Halftime", "basketball/nba") == 0.5
    # Final
    assert _estimate_game_progress("Final", "football/nfl") == 1.0
    # 1st quarter
    assert _estimate_game_progress("1st Quarter", "football/nfl") < 0.2
    # Overtime
    assert _estimate_game_progress("Overtime", "basketball/nba") > 0.9
