"""Tests for core data models."""

import time
from src.core.models import (
    DataSignal,
    MarketState,
    OrderBook,
    OrderBookLevel,
    MarketSide,
    Platform,
    SignalType,
    TradeSignal,
)


def test_data_signal_age():
    signal = DataSignal(
        source="test",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="test_event",
        data={"score": 1},
        timestamp_ms=int(time.time() * 1000) - 1000,
    )
    assert signal.age_ms >= 1000
    assert not signal.is_stale  # 1s < 5s default


def test_data_signal_stale():
    signal = DataSignal(
        source="test",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="test_event",
        data={},
        timestamp_ms=int(time.time() * 1000) - 10000,
    )
    assert signal.is_stale  # 10s > 5s


def test_market_state():
    market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="test_market",
        question="Will it rain tomorrow?",
        yes_price=0.65,
        no_price=0.35,
        volume_24h=10000,
    )
    assert market.midpoint == 0.65
    assert abs(market.spread) < 0.01  # 0.65 + 0.35 = 1.0


def test_order_book():
    book = OrderBook(
        bids=[
            OrderBookLevel(price=0.60, size=100),
            OrderBookLevel(price=0.55, size=200),
        ],
        asks=[
            OrderBookLevel(price=0.65, size=150),
            OrderBookLevel(price=0.70, size=100),
        ],
    )
    assert book.best_bid == 0.60
    assert book.best_ask == 0.65
    assert abs(book.spread - 0.05) < 1e-10
