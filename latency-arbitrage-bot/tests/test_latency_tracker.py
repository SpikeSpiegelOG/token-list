"""Tests for latency tracker."""

import time
from src.core.latency_tracker import LatencyTracker


def test_basic_measurement():
    tracker = LatencyTracker(window_size=10)
    now = int(time.time() * 1000)

    tracker.record_signal("espn", "event_1", now)
    tracker.record_market_update("polymarket", "event_1", "espn", now + 500)

    stats = tracker.get_stats("espn", "polymarket")
    # Need at least 2 measurements for stats
    assert stats is None  # Only 1 measurement

    tracker.record_signal("espn", "event_2", now + 1000)
    tracker.record_market_update("polymarket", "event_2", "espn", now + 1800)

    stats = tracker.get_stats("espn", "polymarket")
    assert stats is not None
    assert stats.count == 2
    assert stats.mean_ms == 650.0  # (500 + 800) / 2


def test_edge_window():
    tracker = LatencyTracker(window_size=10)
    now = int(time.time() * 1000)

    for i in range(5):
        tracker.record_signal("espn", f"event_{i}", now + i * 1000)
        tracker.record_market_update("polymarket", f"event_{i}", "espn", now + i * 1000 + 500)

    edge = tracker.estimated_edge_window_ms("espn", "polymarket")
    assert edge is not None
    assert edge == 500.0  # All measurements are 500ms
