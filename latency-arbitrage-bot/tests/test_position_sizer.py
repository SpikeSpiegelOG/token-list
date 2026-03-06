"""Tests for Kelly Criterion position sizing."""

from src.core.models import Platform
from src.strategies.position_sizer import PositionSizer, estimate_kalshi_fee_rate


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


def test_kalshi_fee_rate():
    """Kalshi fee formula: 0.07 * price * (1-price). Max at 0.50."""
    assert abs(estimate_kalshi_fee_rate(0.50) - 0.0175) < 0.001
    assert abs(estimate_kalshi_fee_rate(0.10) - 0.0063) < 0.001
    assert estimate_kalshi_fee_rate(0.0) == 0.0
    assert estimate_kalshi_fee_rate(1.0) == 0.0


def test_kalshi_fee_reduces_size():
    """Kalshi fees should reduce position size vs Polymarket (0% fees)."""
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 200,
        "max_open_positions": 10,
        "initial_bankroll_usd": 1000,
    })
    poly_size = sizer.calculate_size(
        edge=0.05, confidence=0.8, current_price=0.50, platform=Platform.POLYMARKET
    )
    kalshi_size = sizer.calculate_size(
        edge=0.05, confidence=0.8, current_price=0.50, platform=Platform.KALSHI
    )
    # Kalshi has fees, so effective edge is smaller → smaller size or same min
    assert kalshi_size <= poly_size


def test_kalshi_edge_below_fee_no_trade():
    """If edge doesn't exceed Kalshi fee rate, should not trade."""
    sizer = PositionSizer({
        "kelly_fraction": 0.25,
        "max_bet_size_usd": 50,
        "min_bet_size_usd": 5,
        "max_daily_loss_usd": 200,
        "max_open_positions": 10,
        "initial_bankroll_usd": 1000,
    })
    # At price=0.50, Kalshi fee rate is 0.0175
    # Edge of 0.01 is less than fee → should not trade
    size = sizer.calculate_size(
        edge=0.01, confidence=0.9, current_price=0.50, platform=Platform.KALSHI
    )
    assert size == 0.0
