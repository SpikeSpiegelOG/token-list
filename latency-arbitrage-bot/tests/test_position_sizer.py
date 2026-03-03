"""Tests for Kelly Criterion position sizing."""

from src.strategies.position_sizer import PositionSizer


def test_basic_sizing():
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 200,
        "max_open_positions": 10,
        "initial_bankroll_usd": 1000,
    })
    size = sizer.calculate_size(edge=0.05, confidence=0.8, current_price=0.50)
    assert size >= 5.0  # At least min bet
    assert size <= 50.0  # At most max bet


def test_no_edge_no_trade():
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 200,
        "max_open_positions": 10,
        "initial_bankroll_usd": 1000,
    })
    # Negative edge should return 0
    size = sizer.calculate_size(edge=-0.05, confidence=0.8, current_price=0.50)
    assert size == 0.0


def test_daily_loss_limit():
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 10,
        "max_open_positions": 10,
        "initial_bankroll_usd": 1000,
    })
    sizer.record_trade_result(-10)  # Hit daily loss limit
    size = sizer.calculate_size(edge=0.10, confidence=0.9, current_price=0.50)
    assert size == 0.0  # Should refuse to trade


def test_max_positions():
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 200,
        "max_open_positions": 2,
        "initial_bankroll_usd": 1000,
    })
    sizer.open_position()
    sizer.open_position()
    size = sizer.calculate_size(edge=0.10, confidence=0.9, current_price=0.50)
    assert size == 0.0  # Max positions reached
