"""Kalshi market connector.

Kalshi is a CFTC-regulated exchange for event contracts. ~90% of volume is sports.
It offers REST and WebSocket APIs for trading.

Hierarchy: Series → Event → Market
- Series: recurring template (e.g., "NFL Games")
- Event: specific game (e.g., "Chiefs vs Eagles")
- Market: specific question (e.g., "Will Chiefs win?", "Over 47.5?", "Chiefs -3.5?")

Market types: Moneyline, Spread, Totals, Player Props, Same-Game Parlays

Auth flow:
1. Login with email/password to get auth token
2. Use token for all subsequent requests
3. Token expires, re-authenticate as needed

IMPORTANT (March 2026): Legacy integer price fields are being removed.
Use _dollars suffix fields (yes_bid_dollars, no_bid_dollars, etc.) instead.

Fees: 0.07 × contracts × price × (1 - price)
"""

from __future__ import annotations

import re
import time
from typing import Any

import aiohttp

from src.core.base import BaseMarketConnector
from src.core.event_bus import EventBus
from src.core.models import (
    MarketSide,
    MarketState,
    MarketType,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Platform,
)

# Known Kalshi sports series tickers for market discovery
KALSHI_SPORTS_SERIES = {
    "nfl": ["KXNFL", "KXNFLGAMES"],
    "nba": ["KXNBA", "KXNBAGAMES"],
    "mlb": ["KXMLB", "KXMLBGAMES"],
    "nhl": ["KXNHL", "KXNHLGAMES"],
    "ncaaf": ["KXNCAAF"],
    "ncaab": ["KXNCAAB"],
    "soccer": ["KXSOCCER"],
    "mma": ["KXUFC"],
}


def calculate_kalshi_fee(contracts: int, price: float) -> float:
    """Calculate Kalshi trading fee: 0.07 × C × P × (1 - P)."""
    return 0.07 * contracts * price * (1.0 - price)


class KalshiConnector(BaseMarketConnector):
    """Full Kalshi API connector with order management and sports discovery."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("kalshi", event_bus, config)
        # Updated base URL — api.elections.kalshi.com covers ALL markets
        self.base_url = config.get("base_url", "https://api.elections.kalshi.com/trade-api/v2")
        self.ws_url = config.get("ws_url", "wss://api.elections.kalshi.com/trade-api/ws/v2")
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

    # ---- Sports Discovery (Series → Event → Market) ----

    async def get_sports_series(self, sport: str | None = None) -> list[dict[str, Any]]:
        """Discover sports series tickers.

        If sport is given (e.g., 'nfl'), returns known series for that sport.
        Otherwise queries Kalshi for all series.
        """
        if sport and sport.lower() in KALSHI_SPORTS_SERIES:
            tickers = KALSHI_SPORTS_SERIES[sport.lower()]
            results = []
            for ticker in tickers:
                try:
                    data = await self._request("GET", "/series", params={"series_ticker": ticker})
                    series_list = data.get("series", [])
                    results.extend(series_list)
                except Exception:
                    self.logger.debug(f"Series {ticker} not found or error")
            return results
        # Fallback: query events to discover series
        try:
            data = await self._request("GET", "/events", params={"status": "open", "limit": 100})
            seen = set()
            series = []
            for event in data.get("events", []):
                st = event.get("series_ticker", "")
                if st and st not in seen:
                    seen.add(st)
                    series.append({"series_ticker": st, "title": event.get("title", "")})
            return series
        except Exception:
            self.logger.exception("Error discovering sports series")
            return []

    async def get_events_by_series(self, series_ticker: str, status: str = "open") -> list[dict[str, Any]]:
        """Get events (games) within a series.

        For sports: each event is typically one game with multiple markets
        (moneyline, spread, total, player props).
        """
        try:
            data = await self._request("GET", "/events", params={
                "series_ticker": series_ticker,
                "status": status,
                "limit": 100,
            })
            return data.get("events", [])
        except Exception:
            self.logger.exception(f"Error fetching events for series {series_ticker}")
            return []

    async def get_markets_for_event(self, event_ticker: str) -> list[MarketState]:
        """Get all markets for a specific event (game).

        Returns moneyline, spread, total, and player prop markets.
        """
        try:
            data = await self._request("GET", "/markets", params={
                "event_ticker": event_ticker,
                "status": "open",
                "limit": 100,
            })
            markets = []
            for item in data.get("markets", []):
                market = self._parse_market(item)
                if market:
                    markets.append(market)
            return markets
        except Exception:
            self.logger.exception(f"Error fetching markets for event {event_ticker}")
            return []

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
            params: dict[str, Any] = {}
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

        # Calculate expected fee
        fee = calculate_kalshi_fee(int(size), price)
        order.fees = fee

        try:
            kalshi_side = "yes" if side in (MarketSide.YES, MarketSide.BUY) else "no"
            kalshi_action = "buy"

            order_payload: dict[str, Any] = {
                "ticker": market_id,
                "action": kalshi_action,
                "side": kalshi_side,
                "type": order_type.value,
                "count": int(size),
            }

            if order_type == OrderType.LIMIT:
                # Use dollar-based pricing (not legacy cents)
                if kalshi_side == "yes":
                    order_payload["yes_price"] = price
                else:
                    order_payload["no_price"] = price

            if self._auth_token:
                result = await self._request("POST", "/portfolio/orders", data=order_payload)
                order_data = result.get("order", result)
                order.platform_order_id = order_data.get("order_id", "")
                order.status = OrderStatus.SUBMITTED
                order.submitted_at_ms = int(time.time() * 1000)

                if order_data.get("status") == "filled":
                    order.status = OrderStatus.FILLED
                    order.fill_price = price
                    order.fill_size = size
                    order.filled_at_ms = int(time.time() * 1000)

                self.logger.info(
                    f"Order submitted: {order.platform_order_id} | "
                    f"{kalshi_action} {kalshi_side} {size}@{price} | fee: ${fee:.4f}"
                )
            else:
                # Paper trading
                order.status = OrderStatus.FILLED
                order.fill_price = price
                order.fill_size = size
                order.filled_at_ms = int(time.time() * 1000)
                self.logger.info(f"[PAPER] Order filled: {kalshi_side} {size}@{price} | fee: ${fee:.4f}")

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
        """Get available balance in dollars."""
        try:
            data = await self._request("GET", "/portfolio/balance")
            # Prefer _dollars field; fall back to legacy cents field
            if "balance_dollars" in data:
                return float(data["balance_dollars"])
            return float(data.get("balance", 0)) / 100.0
        except Exception:
            self.logger.exception("Error fetching balance")
            return 0.0

    # ---- Helpers ----

    def _parse_market(self, data: dict[str, Any]) -> MarketState:
        """Parse a Kalshi market response into MarketState.

        Uses _dollars price fields (legacy integer cents removed March 12, 2026).
        """
        # Prefer dollar fields, fall back to cents-based
        if "yes_bid_dollars" in data:
            yes_price = float(data.get("yes_bid_dollars", data.get("last_price_dollars", 0.5)))
        else:
            yes_price = float(data.get("yes_bid", data.get("last_price", 50))) / 100.0
        no_price = 1.0 - yes_price

        title = data.get("title", data.get("subtitle", ""))
        market_type, spread_line, total_line = self._detect_market_type(title)

        return MarketState(
            platform=Platform.KALSHI,
            market_id=data.get("ticker", data.get("id", "")),
            question=title,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=float(data.get("volume_24h", data.get("volume", 0))),
            liquidity=float(data.get("open_interest", 0)),
            market_type=market_type,
            spread_line=spread_line,
            total_line=total_line,
            metadata={
                "ticker": data.get("ticker", ""),
                "series_ticker": data.get("series_ticker", ""),
                "event_ticker": data.get("event_ticker", ""),
                "category": data.get("category", ""),
                "close_time": data.get("close_time", ""),
                "expiration_time": data.get("expiration_time", ""),
                "settlement_value": data.get("settlement_value"),
                "result": data.get("result", ""),
                "estimated_fee_rate": 0.07,
            },
        )

    @staticmethod
    def _detect_market_type(title: str) -> tuple[MarketType, float | None, float | None]:
        """Detect market type from Kalshi market title."""
        t = title.lower()

        # Spread: "Will X win by more than N?" or "X -N.5"
        spread_match = re.search(
            r'(?:win by (?:more than|over)|(?:spread|margin).*?)([\d]+\.?\d*)', t
        )
        if spread_match or "win by" in t or "spread" in t or "margin" in t:
            line = float(spread_match.group(1)) if spread_match else None
            return MarketType.SPREAD, line, None

        # Total: "over N" or "total" or "combined"
        total_match = re.search(
            r'(?:over|under|total|combined).*?([\d]+\.?\d*)', t
        )
        if "total" in t or ("over" in t and any(c.isdigit() for c in t)):
            line = float(total_match.group(1)) if total_match else None
            return MarketType.TOTAL, None, line

        # Player props
        prop_keywords = [
            "touchdown", "passing yards", "rushing yards", "receiving yards",
            "points scored", "rebounds", "assists", "goals", "strikeouts",
            "home runs", "tackles", "sacks", "interceptions",
        ]
        if any(kw in t for kw in prop_keywords):
            return MarketType.PLAYER_PROP, None, None

        # Moneyline: "Will X win?"
        if any(kw in t for kw in ["win", "beat", "defeat"]):
            return MarketType.MONEYLINE, None, None

        # Futures
        if any(kw in t for kw in ["championship", "mvp", "super bowl", "world series"]):
            return MarketType.FUTURES, None, None

        return MarketType.BINARY, None, None

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
