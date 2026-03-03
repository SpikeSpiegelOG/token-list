"""Core arbitrage engine - the brain of the bot.

This engine receives data signals from fast data sources, maps them to
prediction markets, calculates fair values, detects edges, and generates
trade signals when the edge exceeds our threshold.

Flow:
1. Data signal arrives (e.g., "Lakers scored, now leading 105-98")
2. Find related prediction markets (e.g., "Will Lakers win tonight?")
3. Calculate fair value using the new data
4. Compare fair value to current market price
5. If edge > threshold, generate a trade signal
6. Apply risk checks
7. Publish trade signal for execution
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from src.core.event_bus import EventBus, Events
from src.core.latency_tracker import LatencyTracker
from src.core.models import (
    DataSignal,
    MarketSide,
    MarketState,
    Platform,
    SignalType,
    TradeSignal,
)
from src.markets.common.market_mapper import MarketMapper
from src.strategies.fair_value import FairValueCalculator
from src.strategies.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class ArbitrageEngine:
    """Main arbitrage engine - processes signals and generates trades."""

    def __init__(
        self,
        event_bus: EventBus,
        market_mapper: MarketMapper,
        latency_tracker: LatencyTracker,
        config: dict[str, Any],
    ) -> None:
        self.event_bus = event_bus
        self.market_mapper = market_mapper
        self.latency_tracker = latency_tracker
        self.config = config

        self.fair_value_calc = FairValueCalculator()
        self.position_sizer = PositionSizer(config)

        # Strategy parameters from config
        self.min_edge = config.get("min_edge_threshold", 0.03)
        self.max_signal_age_ms = config.get("max_signal_age_ms", 5000)
        self.min_confidence = config.get("min_confidence", 0.65)
        self.high_confidence = config.get("high_confidence", 0.85)

        # Stats
        self._signals_processed = 0
        self._trades_generated = 0
        self._signals_rejected = 0

    async def start(self) -> None:
        """Subscribe to data signals and start processing."""
        self.event_bus.subscribe(Events.DATA_SIGNAL, self._on_data_signal, priority=0)
        logger.info("Arbitrage engine started")

    async def stop(self) -> None:
        """Unsubscribe and stop."""
        self.event_bus.unsubscribe(Events.DATA_SIGNAL, self._on_data_signal)
        logger.info(
            f"Arbitrage engine stopped | "
            f"Signals processed: {self._signals_processed} | "
            f"Trades generated: {self._trades_generated} | "
            f"Signals rejected: {self._signals_rejected}"
        )

    async def _on_data_signal(self, signal: DataSignal) -> None:
        """Process an incoming data signal."""
        self._signals_processed += 1

        # Check signal freshness
        if signal.age_ms > self.max_signal_age_ms:
            self._signals_rejected += 1
            logger.debug(f"Signal too old ({signal.age_ms}ms): {signal.source}/{signal.signal_type.value}")
            return

        # Record signal timing for latency tracking
        self.latency_tracker.record_signal(signal.source, signal.event_id, signal.timestamp_ms)

        # Find relevant markets
        matched_markets = self.market_mapper.find_markets(signal)
        if not matched_markets:
            logger.debug(f"No markets matched for signal: {signal.source}/{signal.event_id}")
            return

        logger.info(
            f"Signal matched {len(matched_markets)} markets | "
            f"Source: {signal.source} | Type: {signal.signal_type.value} | "
            f"Event: {signal.event_id}"
        )

        # Evaluate each matched market for trading opportunities
        for market, relevance in matched_markets:
            try:
                await self._evaluate_opportunity(signal, market, relevance)
            except Exception:
                logger.exception(f"Error evaluating opportunity for market {market.market_id}")

    async def _evaluate_opportunity(
        self, signal: DataSignal, market: MarketState, relevance: float
    ) -> None:
        """Evaluate a potential trading opportunity."""
        # Calculate fair value based on the signal
        fair_value = self.fair_value_calc.calculate(signal, market)
        if fair_value is None:
            return

        # Determine which side to trade and calculate edge
        current_price = market.yes_price
        edge = fair_value - current_price

        # Determine trade direction
        if edge > self.min_edge:
            # Fair value is higher than market price — buy YES
            side = MarketSide.YES
            target_price = current_price  # Buy at current price
        elif edge < -self.min_edge:
            # Fair value is lower than market price — buy NO
            side = MarketSide.NO
            edge = abs(edge)
            target_price = market.no_price
            fair_value = 1.0 - fair_value  # Flip for NO side
        else:
            # Edge too small
            return

        # Adjust confidence based on signal quality and relevance
        confidence = signal.confidence * relevance
        if confidence < self.min_confidence:
            logger.debug(f"Confidence too low ({confidence:.2f}) for market {market.market_id}")
            return

        # Calculate position size
        suggested_size = self.position_sizer.calculate_size(
            edge=edge,
            confidence=confidence,
            current_price=target_price,
        )

        if suggested_size <= 0:
            return

        # Generate trade signal
        trade_signal = TradeSignal(
            signal_id=str(uuid.uuid4())[:12],
            data_signal=signal,
            market=market,
            platform=market.platform,
            market_id=market.market_id,
            side=side,
            target_price=target_price,
            fair_value=fair_value,
            edge=edge,
            confidence=confidence,
            suggested_size_usd=suggested_size,
            metadata={
                "relevance": relevance,
                "signal_age_ms": signal.age_ms,
                "market_question": market.question[:100],
            },
        )

        if trade_signal.is_actionable:
            self._trades_generated += 1
            logger.info(
                f"TRADE SIGNAL | {side.value} {market.platform.value}:{market.market_id} | "
                f"Edge: {edge:.4f} | Fair: {fair_value:.4f} | "
                f"Price: {target_price:.4f} | Size: ${suggested_size:.2f} | "
                f"Confidence: {confidence:.2f}"
            )
            await self.event_bus.publish(Events.TRADE_SIGNAL, trade_signal)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "signals_processed": self._signals_processed,
            "trades_generated": self._trades_generated,
            "signals_rejected": self._signals_rejected,
            "hit_rate": (
                self._trades_generated / self._signals_processed
                if self._signals_processed > 0
                else 0
            ),
        }
