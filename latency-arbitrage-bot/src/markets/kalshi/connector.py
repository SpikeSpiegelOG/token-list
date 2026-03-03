"""Kalshi market connector.

Kalshi is a CFTC-regulated exchange for event contracts. It offers REST and
WebSocket APIs for trading. Key markets: weather, economics, politics.

Auth flow:
1. Login with email/password to get auth token
2. Use token for all subsequent requests
3. Token expires, re-authenticate as needed

Key endpoints:
- /login: Authenticate
- /markets: Browse/search markets
- /portfolio/orders: Place and manage orders
- /portfolio/positions: View positions
"""

from __future__ import annotations

import time
from typing import Any

import aiohttp

from src.core.base import BaseMarketConnector
from src.core.event_bus import EventBus
from src.core.models import (
    MarketSide,
    MarketState,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Platform,
)


class KalshiConnector(BaseMarketConnector):
    """Full Kalshi API connector with order management."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("kalshi", event_bus, config)
        self.base_url = config.get("base_url", "https://trading-api.kalshi.com/trade-api/v2")
        self.ws_url = config.get("ws_url", "wss://trading-api.kalshi.com/trade-api/ws/v2")
        self.email = config.get("email", "")
        self.password = config.get("password", "")
        self.api_key = config.get("api_key", "")
        self._session: aiohttp.ClientSession | None = None
        self._auth_token: str | None = None
        self._member_id: str | None = None
        self._token_expiry: float = 0

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        self._session = aiohttp.ClientSession(timeout=timeout)

        if self.email and self.password:
            await self._authenticate()
        elif self.api_key:
            self._auth_token = self.api_key
            self.logger.info("Kalshi connected with API key")
        else:
            self.logger.warning("Kalshi credentials not configured — read-only mode")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self._auth_token = None

    async def _authenticate(self) -> None:
        """Authenticate with Kalshi API."""
        if not self._session:
            raise RuntimeError("Not connected")

        url = f"{self.base_url}/login"
        payload = {"email": self.email, "password": self.password}

        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Kalshi auth failed ({resp.status}): {error_text}")
            data = await resp.json()
            self._auth_token = data.get("token", "")
            self._member_id = data.get("member_id", "")
            # Token typically valid for 24 hours
            self._token_expiry = time.time() + 86400
            self.logger.info(f"Kalshi authenticated as member {self._member_id}")

    async def _ensure_auth(self) -> None:
        """Re-authenticate if token is expired."""
        if self._auth_token and time.time() < self._token_expiry:
            return
        if self.email and self.password:
            await self._authenticate()

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    async def _request(self, method: str, path: str, data: dict | None = None, params: dict | None = None) -> dict[str, Any]:
        """Make an authenticated request to Kalshi API."""
        if not self._session:
            raise RuntimeError("Not connected")

        await self._ensure_auth()
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        if method.upper() == "GET":
            async with self._session.get(url, headers=headers, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method.upper() == "POST":
            async with self._session.post(url, headers=headers, json=data) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method.upper() == "DELETE":
            async with self._session.delete(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
        else:
            raise ValueError(f"Unsupported method: {method}")

    # ---- Market Data ----

    async def get_market(self, market_id: str) -> MarketState | None:
        """Get a single market by ticker."""
        try:
            data = await self._request("GET", f"/markets/{market_id}")
            market_data = data.get("market", data)
            return self._parse_market(market_data)
        except Exception:
            self.logger.exception(f"Error fetching market {market_id}")
            return None

    async def get_order_book(self, market_id: str) -> OrderBook | None:
        """Get order book for a market."""
        try:
            data = await self._request("GET", f"/markets/{market_id}/orderbook")
            return self._parse_order_book(data.get("orderbook", data))
        except Exception:
            self.logger.exception(f"Error fetching order book for {market_id}")
            return None

    async def search_markets(self, query: str) -> list[MarketState]:
        """Search for markets."""
        try:
            data = await self._request("GET", "/markets", params={
                "status": "open",
                "limit": 50,
            })
            markets = []
            for item in data.get("markets", []):
                title = (item.get("title", "") or "").lower()
                subtitle = (item.get("subtitle", "") or "").lower()
                if query.lower() in title or query.lower() in subtitle:
                    market = self._parse_market(item)
                    if market:
                        markets.append(market)
            return markets
        except Exception:
            self.logger.exception(f"Error searching markets for '{query}'")
            return []

    async def get_active_markets(self, limit: int = 50, series_ticker: str | None = None) -> list[MarketState]:
        """Get active markets, optionally filtered by series."""
        try:
            params: dict[str, Any] = {"status": "open", "limit": limit}
            if series_ticker:
                params["series_ticker"] = series_ticker
            data = await self._request("GET", "/markets", params=params)
            return [self._parse_market(m) for m in data.get("markets", []) if m]
        except Exception:
            self.logger.exception("Error fetching active markets")
            return []

    async def get_events(self, series_ticker: str | None = None) -> list[dict[str, Any]]:
        """Get events (groups of related markets)."""
        try:
            params = {}
            if series_ticker:
                params["series_ticker"] = series_ticker
            data = await self._request("GET", "/events", params=params)
            return data.get("events", [])
        except Exception:
            self.logger.exception("Error fetching events")
            return []

    # ---- Order Management ----

    async def place_order(
        self,
        market_id: str,
        side: MarketSide,
        order_type: OrderType,
        price: float,
        size: float,
    ) -> Order:
        """Place an order on Kalshi."""
        self._order_count += 1
        order_id = f"kalshi_{int(time.time() * 1000)}_{self._order_count}"

        order = Order(
            order_id=order_id,
            trade_signal=None,  # type: ignore
            platform=Platform.KALSHI,
            market_id=market_id,
            side=side,
            order_type=order_type,
            price=price,
            size=int(size),  # Kalshi uses integer contract counts
        )

        try:
            kalshi_side = "yes" if side in (MarketSide.YES, MarketSide.BUY) else "no"
            kalshi_action = "buy"  # We always buy yes or no contracts

            # Price in cents (Kalshi uses cents, 1-99)
            price_cents = int(price * 100)

            order_payload = {
                "ticker": market_id,
                "action": kalshi_action,
                "side": kalshi_side,
                "type": order_type.value,
                "count": int(size),
            }

            if order_type == OrderType.LIMIT:
                order_payload["yes_price"] = price_cents if kalshi_side == "yes" else None
                order_payload["no_price"] = price_cents if kalshi_side == "no" else None

            if self._auth_token:
                result = await self._request("POST", "/portfolio/orders", data=order_payload)
                order_data = result.get("order", result)
                order.platform_order_id = order_data.get("order_id", "")
                order.status = OrderStatus.SUBMITTED
                order.submitted_at_ms = int(time.time() * 1000)

                # Check if immediately filled
                if order_data.get("status") == "filled":
                    order.status = OrderStatus.FILLED
                    order.fill_price = price
                    order.fill_size = size
                    order.filled_at_ms = int(time.time() * 1000)

                self.logger.info(f"Order submitted: {order.platform_order_id} | {kalshi_action} {kalshi_side} {size}@{price}")
            else:
                # Paper trading
                order.status = OrderStatus.FILLED
                order.fill_price = price
                order.fill_size = size
                order.filled_at_ms = int(time.time() * 1000)
                self.logger.info(f"[PAPER] Order filled: {kalshi_side} {size}@{price}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            self.logger.exception(f"Order rejected: {e}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            await self._request("DELETE", f"/portfolio/orders/{order_id}")
            self.logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception:
            self.logger.exception(f"Failed to cancel order {order_id}")
            return False

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all positions."""
        try:
            data = await self._request("GET", "/portfolio/positions")
            return data.get("market_positions", [])
        except Exception:
            self.logger.exception("Error fetching positions")
            return []

    async def get_balance(self) -> float:
        """Get available balance."""
        try:
            data = await self._request("GET", "/portfolio/balance")
            # Kalshi returns balance in cents
            return float(data.get("balance", 0)) / 100.0
        except Exception:
            self.logger.exception("Error fetching balance")
            return 0.0

    # ---- Helpers ----

    def _parse_market(self, data: dict[str, Any]) -> MarketState:
        yes_price = float(data.get("yes_bid", data.get("last_price", 50))) / 100.0
        no_price = 1.0 - yes_price

        return MarketState(
            platform=Platform.KALSHI,
            market_id=data.get("ticker", data.get("id", "")),
            question=data.get("title", data.get("subtitle", "")),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=float(data.get("volume_24h", data.get("volume", 0))),
            liquidity=float(data.get("open_interest", 0)),
            metadata={
                "ticker": data.get("ticker", ""),
                "series_ticker": data.get("series_ticker", ""),
                "category": data.get("category", ""),
                "close_time": data.get("close_time", ""),
                "expiration_time": data.get("expiration_time", ""),
                "settlement_value": data.get("settlement_value"),
                "result": data.get("result", ""),
            },
        )

    def _parse_order_book(self, data: dict[str, Any]) -> OrderBook:
        bids = []
        asks = []
        for price_str, size in (data.get("yes", {}) or {}).items():
            bids.append(OrderBookLevel(price=float(price_str) / 100.0, size=float(size)))
        for price_str, size in (data.get("no", {}) or {}).items():
            asks.append(OrderBookLevel(price=float(price_str) / 100.0, size=float(size)))
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return OrderBook(bids=bids, asks=asks)
