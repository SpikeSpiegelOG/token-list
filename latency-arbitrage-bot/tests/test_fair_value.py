"""Tests for fair value calculator."""

from src.core.models import DataSignal, MarketState, Platform, SignalType
from src.strategies.fair_value import FairValueCalculator


def test_sports_score_home_leading():
    calc = FairValueCalculator()
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="game_1",
        data={
            "sport": "basketball/nba",
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
