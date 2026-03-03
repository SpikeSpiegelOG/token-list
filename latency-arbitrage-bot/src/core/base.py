"""Base classes for data sources and market connectors."""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import Any

from src.core.event_bus import EventBus
from src.core.models import DataSignal, MarketSide, MarketState, Order, OrderBook, OrderType


class BaseDataSource(abc.ABC):
    """Base class for all data source adapters (ESPN, Weather, News, etc.)."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any]) -> None:
        self.name = name
        self.event_bus = event_bus
        self.config = config
        self.logger = logging.getLogger(f"datasource.{name}")
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_poll_ms: int = 0
        self._poll_count: int = 0
        self._error_count: int = 0

    @abc.abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the data source."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Clean up connection."""

    @abc.abstractmethod
    async def poll(self) -> list[DataSignal]:
        """Poll the data source for new signals. Override this."""

    @property
    def poll_interval_ms(self) -> int:
        return self.config.get("poll_interval_ms", 1000)

    async def start(self) -> None:
        """Start the polling loop."""
        await self.connect()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        self.logger.info(f"Data source '{self.name}' started (poll_interval={self.poll_interval_ms}ms)")

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.disconnect()
        self.logger.info(f"Data source '{self.name}' stopped (polls={self._poll_count}, errors={self._error_count})")

    async def _poll_loop(self) -> None:
        """Main polling loop with timing."""
        while self._running:
            try:
                start_ms = int(time.time() * 1000)
                signals = await self.poll()
                self._poll_count += 1
                self._last_poll_ms = int(time.time() * 1000) - start_ms

                for signal in signals:
                    from src.core.event_bus import Events
                    await self.event_bus.publish(Events.DATA_SIGNAL, signal)

            except asyncio.CancelledError:
                break
            except Exception:
                self._error_count += 1
                self.logger.exception(f"Error polling {self.name}")

            # Sleep for the poll interval
            await asyncio.sleep(self.poll_interval_ms / 1000.0)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "running": self._running,
            "poll_count": self._poll_count,
            "error_count": self._error_count,
            "last_poll_ms": self._last_poll_ms,
        }


class BaseMarketConnector(abc.ABC):
    """Base class for prediction market connectors (Polymarket, Kalshi)."""

    def __init__(self, name: str, event_bus: EventBus, config: dict[str, Any]) -> None:
        self.name = name
        self.event_bus = event_bus
        self.config = config
        self.logger = logging.getLogger(f"market.{name}")
        self._connected = False
        self._order_count: int = 0
        self._fill_count: int = 0

    @abc.abstractmethod
    async def connect(self) -> None:
        """Connect and authenticate with the market."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the market."""

    @abc.abstractmethod
    async def get_market(self, market_id: str) -> MarketState | None:
        """Get current market state."""

    @abc.abstractmethod
    async def get_order_book(self, market_id: str) -> OrderBook | None:
        """Get current order book for a market."""

    @abc.abstractmethod
    async def place_order(
        self,
        market_id: str,
        side: MarketSide,
        order_type: OrderType,
        price: float,
        size: float,
    ) -> Order:
        """Place an order on the market."""

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""

    @abc.abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all open positions."""

    @abc.abstractmethod
    async def get_balance(self) -> float:
        """Get available balance in USD."""

    @abc.abstractmethod
    async def search_markets(self, query: str) -> list[MarketState]:
        """Search for markets matching a query."""

    async def start(self) -> None:
        """Start the market connector."""
        await self.connect()
        self._connected = True
        self.logger.info(f"Market connector '{self.name}' connected")

    async def stop(self) -> None:
        """Stop the market connector."""
        await self.disconnect()
        self._connected = False
        self.logger.info(f"Market connector '{self.name}' disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connected": self._connected,
            "order_count": self._order_count,
            "fill_count": self._fill_count,
        }
