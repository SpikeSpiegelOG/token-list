"""Crypto data source adapters using WebSocket feeds.

Crypto price feeds via WebSocket are extremely fast — sub-100ms latency.
These are useful for prediction markets that reference crypto prices
(e.g., "Will BTC be above $X on date Y?").

Strategy: Subscribe to real-time price feeds via WebSocket. Detect large
price movements instantly and trade related prediction markets.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp

from src.core.base import BaseDataSource
from src.core.event_bus import EventBus
from src.core.models import DataSignal, SignalType


class BinanceWebSocketSource(BaseDataSource):
    """Binance WebSocket feed for real-time crypto prices."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("binance_ws", event_bus, config)
        self.ws_url = config.get("ws_url", "wss://stream.binance.com:9443/ws")
        self.tracked_pairs = [p.lower() for p in config.get("tracked_pairs", ["btcusdt", "ethusdt"])]
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._last_prices: dict[str, float] = {}
        self._ws_task: asyncio.Task | None = None

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        # Build multi-stream URL
        streams = "/".join(f"{pair}@trade" for pair in self.tracked_pairs)
        ws_url = f"{self.ws_url}/{streams}"
        try:
            self._ws = await self._session.ws_connect(ws_url, heartbeat=20)
            self._ws_task = asyncio.create_task(self._ws_listener())
            self.logger.info(f"Binance WS connected, tracking: {self.tracked_pairs}")
        except Exception:
            self.logger.exception("Failed to connect Binance WebSocket")

    async def disconnect(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def _ws_listener(self) -> None:
        """Listen to WebSocket messages and publish signals."""
        while self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive(timeout=30)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    signals = self._process_trade(data)
                    for signal in signals:
                        from src.core.event_bus import Events
                        await self.event_bus.publish(Events.DATA_SIGNAL, signal)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    self.logger.warning("Binance WS disconnected, reconnecting...")
                    await asyncio.sleep(1)
                    await self.connect()
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("Error in Binance WS listener")

    def _process_trade(self, data: dict[str, Any]) -> list[DataSignal]:
        """Process a trade message, detect significant price moves."""
        signals: list[DataSignal] = []
        symbol = data.get("s", "").lower()
        price = float(data.get("p", 0))

        if not symbol or price == 0:
            return signals

        last_price = self._last_prices.get(symbol)
        if last_price and last_price > 0:
            pct_change = (price - last_price) / last_price
            # Signal on 0.5%+ moves (significant for crypto)
            if abs(pct_change) >= 0.005:
                signals.append(DataSignal(
                    source="binance",
                    signal_type=SignalType.CRYPTO_PRICE,
                    event_id=f"crypto_{symbol}_{int(time.time())}",
                    data={
                        "symbol": symbol.upper(),
                        "price": price,
                        "previous_price": last_price,
                        "pct_change": round(pct_change * 100, 4),
                        "direction": "up" if pct_change > 0 else "down",
                        "trade_time": data.get("T"),
                        "quantity": float(data.get("q", 0)),
                    },
                    confidence=0.99,
                ))

        self._last_prices[symbol] = price
        return signals

    async def poll(self) -> list[DataSignal]:
        """WebSocket sources don't poll — they push. This is a no-op."""
        return []


class CoinbaseWebSocketSource(BaseDataSource):
    """Coinbase WebSocket feed for redundant crypto price data."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("coinbase_ws", event_bus, config)
        self.ws_url = config.get("ws_url", "wss://ws-feed.exchange.coinbase.com")
        self.tracked_pairs = config.get("tracked_pairs", ["BTC-USD", "ETH-USD"])
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._last_prices: dict[str, float] = {}
        self._ws_task: asyncio.Task | None = None

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(self.ws_url, heartbeat=20)
            # Subscribe to ticker channel
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": self.tracked_pairs,
                "channels": ["ticker"],
            }
            await self._ws.send_json(subscribe_msg)
            self._ws_task = asyncio.create_task(self._ws_listener())
            self.logger.info(f"Coinbase WS connected, tracking: {self.tracked_pairs}")
        except Exception:
            self.logger.exception("Failed to connect Coinbase WebSocket")

    async def disconnect(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def _ws_listener(self) -> None:
        """Listen to Coinbase WS and publish signals on price moves."""
        while self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive(timeout=30)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "ticker":
                        signals = self._process_ticker(data)
                        for signal in signals:
                            from src.core.event_bus import Events
                            await self.event_bus.publish(Events.DATA_SIGNAL, signal)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    self.logger.warning("Coinbase WS disconnected, reconnecting...")
                    await asyncio.sleep(1)
                    await self.connect()
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("Error in Coinbase WS listener")

    def _process_ticker(self, data: dict[str, Any]) -> list[DataSignal]:
        signals: list[DataSignal] = []
        product_id = data.get("product_id", "")
        price = float(data.get("price", 0))

        if not product_id or price == 0:
            return signals

        last_price = self._last_prices.get(product_id)
        if last_price and last_price > 0:
            pct_change = (price - last_price) / last_price
            if abs(pct_change) >= 0.005:
                signals.append(DataSignal(
                    source="coinbase",
                    signal_type=SignalType.CRYPTO_PRICE,
                    event_id=f"crypto_{product_id}_{int(time.time())}",
                    data={
                        "symbol": product_id,
                        "price": price,
                        "previous_price": last_price,
                        "pct_change": round(pct_change * 100, 4),
                        "direction": "up" if pct_change > 0 else "down",
                        "volume_24h": float(data.get("volume_24h", 0)),
                        "best_bid": float(data.get("best_bid", 0)),
                        "best_ask": float(data.get("best_ask", 0)),
                    },
                    confidence=0.99,
                ))

        self._last_prices[product_id] = price
        return signals

    async def poll(self) -> list[DataSignal]:
        return []
