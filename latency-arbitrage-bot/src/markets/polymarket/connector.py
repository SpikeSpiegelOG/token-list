"""Polymarket CLOB connector.

Polymarket uses a Central Limit Order Book (CLOB) on Polygon. The CLOB is an
off-chain order book with on-chain settlement. Orders are signed with your
wallet private key and submitted to the CLOB API.

Key components:
- CLOB API: Order placement, cancellation, market data
- Gamma API: Market discovery, metadata
- WebSocket: Real-time order book updates

Auth flow:
1. Generate API credentials from your private key via /auth/api-key
2. Use API key + secret + passphrase for all subsequent requests
3. Orders are signed with your private key (EIP-712 typed data)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import base64
from typing import Any
from urllib.parse import urlencode

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


class PolymarketConnector(BaseMarketConnector):
    """Full Polymarket CLOB connector with order management."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("polymarket", event_bus, config)
        self.clob_url = config.get("clob_url", "https://clob.polymarket.com")
        self.gamma_url = config.get("gamma_url", "https://gamma-api.polymarket.com")
        self.ws_url = config.get("ws_url", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.api_passphrase = config.get("api_passphrase", "")
        self.private_key = config.get("private_key", "")
        self.funder = config.get("funder", "")
        self.chain_id = config.get("chain_id", 137)
        self._session: aiohttp.ClientSession | None = None
        self._market_cache: dict[str, MarketState] = {}

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        self._session = aiohttp.ClientSession(timeout=timeout)

        if not self.api_key:
            self.logger.warning("Polymarket API key not configured — read-only mode")
        else:
            # Verify connection
            try:
                balance = await self.get_balance()
                self.logger.info(f"Polymarket connected. Balance: ${balance:.2f}")
            except Exception:
                self.logger.exception("Failed to verify Polymarket connection")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    def _build_hmac_signature(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Build HMAC signature for authenticated requests."""
        message = f"{timestamp}{method}{path}{body}"
        secret_bytes = base64.b64decode(self.api_secret)
        signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256)
        return base64.b64encode(signature.digest()).decode()

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Generate authentication headers for CLOB API requests."""
        timestamp = str(int(time.time()))
        signature = self._build_hmac_signature(timestamp, method, path, body)
        return {
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json",
        }

    async def _clob_request(self, method: str, path: str, data: dict | None = None) -> dict[str, Any]:
        """Make an authenticated request to the CLOB API."""
        if not self._session:
            raise RuntimeError("Not connected")

        body = json.dumps(data) if data else ""
        headers = self._auth_headers(method.upper(), path, body)
        url = f"{self.clob_url}{path}"

        if method.upper() == "GET":
            async with self._session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method.upper() == "POST":
            async with self._session.post(url, headers=headers, data=body) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method.upper() == "DELETE":
            async with self._session.delete(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
        else:
            raise ValueError(f"Unsupported method: {method}")

    async def _gamma_request(self, path: str, params: dict | None = None) -> dict[str, Any] | list:
        """Make a request to the Gamma API (public, no auth needed)."""
        if not self._session:
            raise RuntimeError("Not connected")

        url = f"{self.gamma_url}{path}"
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ---- Market Data ----

    async def get_market(self, market_id: str) -> MarketState | None:
        """Get market data from CLOB. market_id is the condition_id or token_id."""
        try:
            data = await self._clob_request("GET", f"/markets/{market_id}")
            return self._parse_market(data)
        except Exception:
            self.logger.exception(f"Error fetching market {market_id}")
            return None

    async def get_order_book(self, market_id: str) -> OrderBook | None:
        """Get the order book for a market's token."""
        try:
            data = await self._clob_request("GET", f"/book?token_id={market_id}")
            return self._parse_order_book(data)
        except Exception:
            self.logger.exception(f"Error fetching order book for {market_id}")
            return None

    async def search_markets(self, query: str) -> list[MarketState]:
        """Search for markets using the Gamma API."""
        try:
            results = await self._gamma_request("/markets", params={
                "closed": "false",
                "limit": 20,
                # Gamma API search
            })
            markets = []
            if isinstance(results, list):
                for item in results:
                    q = (item.get("question", "") or "").lower()
                    if query.lower() in q:
                        market = self._parse_gamma_market(item)
                        if market:
                            markets.append(market)
            return markets
        except Exception:
            self.logger.exception(f"Error searching markets for '{query}'")
            return []

    async def get_active_markets(self, limit: int = 50) -> list[MarketState]:
        """Get currently active (open) markets."""
        try:
            results = await self._gamma_request("/markets", params={
                "closed": "false",
                "limit": limit,
                "order": "volume24hr",
                "ascending": "false",
            })
            markets = []
            if isinstance(results, list):
                for item in results:
                    market = self._parse_gamma_market(item)
                    if market:
                        markets.append(market)
            return markets
        except Exception:
            self.logger.exception("Error fetching active markets")
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
        """Place an order on Polymarket CLOB."""
        self._order_count += 1
        order_id = f"poly_{int(time.time() * 1000)}_{self._order_count}"

        order = Order(
            order_id=order_id,
            trade_signal=None,  # type: ignore
            platform=Platform.POLYMARKET,
            market_id=market_id,
            side=side,
            order_type=order_type,
            price=price,
            size=size,
        )

        try:
            # Build order payload for CLOB
            clob_side = "BUY" if side in (MarketSide.YES, MarketSide.BUY) else "SELL"

            order_payload = {
                "tokenID": market_id,
                "price": str(price),
                "size": str(size),
                "side": clob_side,
                "feeRateBps": "0",
                "nonce": str(int(time.time() * 1000)),
                "expiration": "0",  # GTC
            }

            # In live mode, sign and submit
            if self.api_key:
                result = await self._clob_request("POST", "/order", order_payload)
                order.platform_order_id = result.get("orderID", result.get("id", ""))
                order.status = OrderStatus.SUBMITTED
                order.submitted_at_ms = int(time.time() * 1000)
                self.logger.info(f"Order submitted: {order.platform_order_id} | {clob_side} {size}@{price}")
            else:
                # Paper trading mode
                order.status = OrderStatus.FILLED
                order.fill_price = price
                order.fill_size = size
                order.filled_at_ms = int(time.time() * 1000)
                self.logger.info(f"[PAPER] Order filled: {clob_side} {size}@{price}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            self.logger.exception(f"Order rejected: {e}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            await self._clob_request("DELETE", f"/order/{order_id}")
            self.logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception:
            self.logger.exception(f"Failed to cancel order {order_id}")
            return False

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all open positions."""
        try:
            return await self._clob_request("GET", "/positions")
        except Exception:
            self.logger.exception("Error fetching positions")
            return []

    async def get_balance(self) -> float:
        """Get available USDC balance."""
        try:
            result = await self._clob_request("GET", "/balance")
            return float(result.get("balance", 0))
        except Exception:
            self.logger.exception("Error fetching balance")
            return 0.0

    # ---- Helpers ----

    def _parse_market(self, data: dict[str, Any]) -> MarketState:
        tokens = data.get("tokens", [])
        yes_price = 0.5
        no_price = 0.5
        for token in tokens:
            if token.get("outcome") == "Yes":
                yes_price = float(token.get("price", 0.5))
            elif token.get("outcome") == "No":
                no_price = float(token.get("price", 0.5))

        return MarketState(
            platform=Platform.POLYMARKET,
            market_id=data.get("condition_id", data.get("id", "")),
            question=data.get("question", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=float(data.get("volume24hr", 0)),
            liquidity=float(data.get("liquidity", 0)),
            metadata={
                "condition_id": data.get("condition_id", ""),
                "tokens": tokens,
                "end_date": data.get("end_date_iso", ""),
                "category": data.get("category", ""),
            },
        )

    def _parse_gamma_market(self, data: dict[str, Any]) -> MarketState | None:
        try:
            outcomes = data.get("outcomes", [])
            prices = data.get("outcomePrices", [])

            yes_price = 0.5
            no_price = 0.5
            if len(outcomes) >= 2 and len(prices) >= 2:
                for i, outcome in enumerate(outcomes):
                    p = float(prices[i]) if isinstance(prices[i], (str, int, float)) else 0.5
                    if outcome.lower() == "yes":
                        yes_price = p
                    elif outcome.lower() == "no":
                        no_price = p

            return MarketState(
                platform=Platform.POLYMARKET,
                market_id=data.get("conditionId", data.get("id", "")),
                question=data.get("question", ""),
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(data.get("volume24hr", 0)),
                liquidity=float(data.get("liquidityNum", 0)),
                metadata={
                    "slug": data.get("slug", ""),
                    "end_date": data.get("endDate", ""),
                    "category": data.get("category", ""),
                    "clob_token_ids": data.get("clobTokenIds", []),
                },
            )
        except Exception:
            return None

    def _parse_order_book(self, data: dict[str, Any]) -> OrderBook:
        bids = [
            OrderBookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0)))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0)))
            for a in data.get("asks", [])
        ]
        return OrderBook(bids=bids, asks=asks)
