"""Trade execution engine.

Receives trade signals from the arbitrage engine and executes them on
the appropriate prediction market platform. Handles:
- Order placement (limit or market)
- Order tracking and status updates
- Position management
- Paper trading simulation
- Risk pre-checks before execution
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.base import BaseMarketConnector
from src.core.event_bus import EventBus, Events
from src.core.models import (
    BotMode,
    MarketSide,
    Order,
    OrderStatus,
    OrderType,
    Platform,
    Position,
    TradeSignal,
)

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Executes trade signals on prediction market platforms."""

    def __init__(
        self,
        event_bus: EventBus,
        connectors: dict[Platform, BaseMarketConnector],
        config: dict[str, Any],
    ) -> None:
        self.event_bus = event_bus
        self.connectors = connectors
        self.config = config
        self.mode = BotMode(config.get("mode", "paper"))

        # Active orders and positions
        self._active_orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}

        # Stats
        self._total_orders = 0
        self._total_fills = 0
        self._total_rejects = 0
        self._total_pnl = 0.0

    async def start(self) -> None:
        """Subscribe to trade signals and start execution."""
        self.event_bus.subscribe(Events.TRADE_SIGNAL, self._on_trade_signal, priority=0)
        logger.info(f"Execution engine started in {self.mode.value} mode")

    async def stop(self) -> None:
        """Cancel all open orders and stop."""
        # Cancel remaining open orders
        for order_id, order in list(self._active_orders.items()):
            if order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                connector = self.connectors.get(order.platform)
                if connector and order.platform_order_id:
                    await connector.cancel_order(order.platform_order_id)

        self.event_bus.unsubscribe(Events.TRADE_SIGNAL, self._on_trade_signal)
        logger.info(
            f"Execution engine stopped | "
            f"Orders: {self._total_orders} | Fills: {self._total_fills} | "
            f"Rejects: {self._total_rejects} | PnL: ${self._total_pnl:.2f}"
        )

    async def _on_trade_signal(self, signal: TradeSignal) -> None:
        """Process an incoming trade signal."""
        # Pre-execution risk checks
        if not self._pre_check(signal):
            return

        connector = self.connectors.get(signal.platform)
        if not connector:
            logger.error(f"No connector for platform: {signal.platform.value}")
            return

        if not connector.is_connected:
            logger.warning(f"Connector {signal.platform.value} not connected")
            return

        # Determine order type
        order_type_str = self.config.get("default_order_type", "limit")
        order_type = OrderType.LIMIT if order_type_str == "limit" else OrderType.MARKET

        # Execute
        try:
            logger.info(
                f"EXECUTING | {signal.side.value} on {signal.platform.value} | "
                f"Market: {signal.market_id} | "
                f"Price: {signal.target_price:.4f} | "
                f"Size: ${signal.suggested_size_usd:.2f} | "
                f"Edge: {signal.edge:.4f}"
            )

            order = await connector.place_order(
                market_id=signal.market_id,
                side=signal.side,
                order_type=order_type,
                price=signal.target_price,
                size=signal.suggested_size_usd,
            )

            order.trade_signal = signal
            self._active_orders[order.order_id] = order
            self._total_orders += 1

            # Handle immediate result
            if order.status == OrderStatus.FILLED:
                await self._handle_fill(order)
            elif order.status == OrderStatus.REJECTED:
                self._total_rejects += 1
                logger.warning(f"Order rejected: {order.error_message}")
                await self.event_bus.publish(Events.ORDER_REJECTED, order)
            else:
                await self.event_bus.publish(Events.ORDER_SUBMITTED, order)

        except Exception:
            self._total_rejects += 1
            logger.exception(f"Error executing trade on {signal.platform.value}")

    async def _handle_fill(self, order: Order) -> None:
        """Handle a filled order — update positions and stats."""
        self._total_fills += 1

        # Update or create position
        pos_key = f"{order.platform.value}:{order.market_id}:{order.side.value}"
        if pos_key in self._positions:
            pos = self._positions[pos_key]
            # Average in
            total_size = pos.size + (order.fill_size or order.size)
            pos.avg_entry_price = (
                (pos.avg_entry_price * pos.size + (order.fill_price or order.price) * (order.fill_size or order.size))
                / total_size
            )
            pos.size = total_size
            pos.orders.append(order)
        else:
            self._positions[pos_key] = Position(
                platform=order.platform,
                market_id=order.market_id,
                side=order.side,
                size=order.fill_size or order.size,
                avg_entry_price=order.fill_price or order.price,
                orders=[order],
            )

        fill_latency = ""
        if order.trade_signal and order.filled_at_ms:
            total_latency = order.filled_at_ms - order.trade_signal.data_signal.timestamp_ms
            fill_latency = f" | Signal->Fill: {total_latency}ms"

        logger.info(
            f"FILLED | {order.side.value} {order.platform.value}:{order.market_id} | "
            f"Price: {order.fill_price or order.price:.4f} | "
            f"Size: {order.fill_size or order.size:.2f}"
            f"{fill_latency}"
        )

        await self.event_bus.publish(Events.ORDER_FILLED, order)

    def _pre_check(self, signal: TradeSignal) -> bool:
        """Pre-execution risk checks."""
        # Check signal staleness
        if signal.data_signal.is_stale:
            logger.debug(f"Signal stale ({signal.data_signal.age_ms}ms), skipping")
            return False

        # Check if we already have a position in this market on this side
        pos_key = f"{signal.platform.value}:{signal.market_id}:{signal.side.value}"
        if pos_key in self._positions:
            existing = self._positions[pos_key]
            max_pos = self.config.get("max_position_size_usd", 100)
            if existing.size >= max_pos:
                logger.debug(f"Max position reached for {pos_key}")
                return False

        # Check total open positions
        max_open = self.config.get("max_open_positions", 10)
        if len(self._positions) >= max_open:
            logger.debug("Max open positions reached")
            return False

        return True

    def get_positions(self) -> list[Position]:
        """Get all current positions."""
        return list(self._positions.values())

    def get_active_orders(self) -> list[Order]:
        """Get all active (non-terminal) orders."""
        return [
            o for o in self._active_orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
        ]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "total_rejects": self._total_rejects,
            "total_pnl": self._total_pnl,
            "active_orders": len(self.get_active_orders()),
            "open_positions": len(self._positions),
        }
