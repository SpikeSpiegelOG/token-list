"""Async event bus for decoupled communication between components.

The event bus is the nervous system of the bot. Data sources publish signals,
the arbitrage engine subscribes to them, and the execution engine acts on trade signals.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type alias for async event handlers
EventHandler = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """Lightweight async pub/sub event bus with priority support."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[int, EventHandler]]] = defaultdict(list)
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    def subscribe(self, event_type: str, handler: EventHandler, priority: int = 0) -> None:
        """Subscribe a handler to an event type. Lower priority = called first."""
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: x[0])
        logger.debug(f"Subscribed {handler.__name__} to {event_type} (priority={priority})")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        self._handlers[event_type] = [
            (p, h) for p, h in self._handlers[event_type] if h != handler
        ]

    async def publish(self, event_type: str, data: Any = None) -> None:
        """Publish an event to all subscribers. Non-blocking - puts on queue."""
        await self._queue.put((event_type, data))

    def publish_nowait(self, event_type: str, data: Any = None) -> None:
        """Publish without awaiting - fire and forget."""
        try:
            self._queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            logger.warning(f"Event queue full, dropping event: {event_type}")

    async def _process_events(self) -> None:
        """Main event processing loop."""
        while self._running:
            try:
                event_type, data = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            handlers = self._handlers.get(event_type, [])
            if not handlers:
                continue

            # Fire all handlers concurrently for speed
            tasks = []
            for _, handler in handlers:
                tasks.append(asyncio.create_task(self._safe_call(handler, event_type, data)))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, handler: EventHandler, event_type: str, data: Any) -> None:
        """Safely call a handler, catching exceptions."""
        try:
            await handler(data)
        except Exception:
            logger.exception(f"Error in handler {handler.__name__} for event {event_type}")

    async def start(self) -> None:
        """Start the event processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._process_events())
        logger.info("Event bus started")

    async def stop(self) -> None:
        """Stop the event processing loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Event bus stopped")

    @property
    def pending_events(self) -> int:
        return self._queue.qsize()


# Event type constants
class Events:
    # Data source events
    DATA_SIGNAL = "data.signal"
    DATA_SOURCE_ERROR = "data.source.error"
    DATA_SOURCE_CONNECTED = "data.source.connected"
    DATA_SOURCE_DISCONNECTED = "data.source.disconnected"

    # Market events
    MARKET_UPDATE = "market.update"
    MARKET_ORDER_BOOK = "market.order_book"
    MARKET_CONNECTED = "market.connected"
    MARKET_DISCONNECTED = "market.disconnected"

    # Strategy events
    TRADE_SIGNAL = "strategy.trade_signal"
    SIGNAL_EXPIRED = "strategy.signal_expired"

    # Execution events
    ORDER_SUBMITTED = "execution.order_submitted"
    ORDER_FILLED = "execution.order_filled"
    ORDER_CANCELLED = "execution.order_cancelled"
    ORDER_REJECTED = "execution.order_rejected"

    # Risk events
    RISK_LIMIT_HIT = "risk.limit_hit"
    POSITION_UPDATE = "risk.position_update"
    DAILY_LOSS_LIMIT = "risk.daily_loss_limit"

    # System events
    BOT_STARTED = "system.bot_started"
    BOT_STOPPED = "system.bot_stopped"
    LATENCY_MEASUREMENT = "system.latency_measurement"
    HEARTBEAT = "system.heartbeat"
