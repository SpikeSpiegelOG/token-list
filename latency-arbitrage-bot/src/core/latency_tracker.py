"""Tracks latency between data sources and prediction markets.

This is the core edge measurement tool. We measure how fast data sources
deliver information vs how fast prediction markets react to the same events.
The delta is our trading window.
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class LatencyStats:
    source: str
    platform: str
    count: int
    mean_ms: float
    median_ms: float
    min_ms: float
    max_ms: float
    p95_ms: float
    p99_ms: float
    stddev_ms: float
    window_size: int


class LatencyTracker:
    """Tracks and analyzes latency differentials between data sources and markets."""

    def __init__(self, window_size: int = 100) -> None:
        self.window_size = window_size
        # Key: (source, platform) -> deque of latency measurements in ms
        self._measurements: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        # Timestamps of data source signals: event_id -> timestamp_ms
        self._signal_timestamps: dict[str, int] = {}
        self._signal_ttl_ms = 60_000  # Clean up after 60s

    def record_signal(self, source: str, event_id: str, timestamp_ms: int | None = None) -> None:
        """Record when a data source delivers a signal."""
        ts = timestamp_ms or int(time.time() * 1000)
        self._signal_timestamps[f"{source}:{event_id}"] = ts
        self._cleanup_old_signals()

    def record_market_update(self, platform: str, event_id: str, source: str, timestamp_ms: int | None = None) -> None:
        """Record when a market updates in response to the same event."""
        ts = timestamp_ms or int(time.time() * 1000)
        key = f"{source}:{event_id}"
        if key in self._signal_timestamps:
            latency = ts - self._signal_timestamps[key]
            self._measurements[(source, platform)].append(latency)

    def get_stats(self, source: str, platform: str) -> LatencyStats | None:
        """Get latency statistics for a source-platform pair."""
        key = (source, platform)
        measurements = list(self._measurements.get(key, []))
        if len(measurements) < 2:
            return None

        sorted_m = sorted(measurements)
        n = len(sorted_m)

        return LatencyStats(
            source=source,
            platform=platform,
            count=n,
            mean_ms=statistics.mean(sorted_m),
            median_ms=statistics.median(sorted_m),
            min_ms=sorted_m[0],
            max_ms=sorted_m[-1],
            p95_ms=sorted_m[int(n * 0.95)],
            p99_ms=sorted_m[int(n * 0.99)],
            stddev_ms=statistics.stdev(sorted_m) if n > 1 else 0,
            window_size=self.window_size,
        )

    def get_all_stats(self) -> list[LatencyStats]:
        """Get stats for all tracked source-platform pairs."""
        results = []
        for (source, platform) in self._measurements:
            stats = self.get_stats(source, platform)
            if stats:
                results.append(stats)
        return results

    def estimated_edge_window_ms(self, source: str, platform: str) -> float | None:
        """Estimate the time window we have to trade before the market catches up.

        This is the key metric — how many milliseconds of edge do we have?
        """
        stats = self.get_stats(source, platform)
        if not stats:
            return None
        # Conservative estimate: use the median latency as our edge window
        # The market will typically update around this time after our signal
        return stats.median_ms

    def _cleanup_old_signals(self) -> None:
        """Remove signal timestamps older than TTL."""
        now = int(time.time() * 1000)
        expired = [k for k, v in self._signal_timestamps.items() if now - v > self._signal_ttl_ms]
        for k in expired:
            del self._signal_timestamps[k]
