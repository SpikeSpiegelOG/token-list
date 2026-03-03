"""Main bot orchestrator - ties everything together.

This is the central coordinator that:
1. Loads configuration
2. Initializes all components
3. Starts data sources, market connectors, and the arbitrage engine
4. Manages the lifecycle of the entire system
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from src.core.config import AppConfig, load_config
from src.core.event_bus import EventBus, Events
from src.core.latency_tracker import LatencyTracker
from src.core.models import Platform
from src.data_sources.crypto.crypto_source import BinanceWebSocketSource
from src.data_sources.news.news_source import GDELTSource, NewsAPISource
from src.data_sources.sports.espn import ESPNDataSource
from src.data_sources.weather.weather_source import NWSWeatherSource, OpenWeatherSource
from src.execution.executor import ExecutionEngine
from src.markets.common.market_mapper import MarketMapper
from src.markets.kalshi.connector import KalshiConnector
from src.markets.polymarket.connector import PolymarketConnector
from src.monitoring.monitor import BotMonitor, ConsoleDashboard
from src.strategies.arbitrage_engine import ArbitrageEngine
from src.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


class SpikeArbBot:
    """Main bot class - the brain that coordinates everything."""

    def __init__(self, config: AppConfig | None = None, config_path: str | None = None) -> None:
        self.config = config or load_config(config_path)
        self._running = False

        # Core components
        self.event_bus = EventBus()
        self.latency_tracker = LatencyTracker(
            window_size=self.config.strategy.latency_window_size
        )
        self.market_mapper = MarketMapper()

        # Data sources
        self.data_sources: list[Any] = []

        # Market connectors
        self.connectors: dict[Platform, Any] = {}

        # Engine components
        self.arb_engine: ArbitrageEngine | None = None
        self.exec_engine: ExecutionEngine | None = None
        self.monitor: BotMonitor | None = None
        self.dashboard: ConsoleDashboard | None = None

    async def start(self) -> None:
        """Initialize and start all components."""
        setup_logging(
            level=self.config.bot.log_level,
            log_file="logs/arb_bot.log",
        )

        logger.info("=" * 60)
        logger.info(f"  SPIKE ARB BOT v0.1.0 - {self.config.bot.name}")
        logger.info(f"  Mode: {self.config.bot.mode}")
        logger.info("=" * 60)

        # Start event bus
        await self.event_bus.start()

        # Initialize market connectors
        await self._init_connectors()

        # Initialize data sources
        await self._init_data_sources()

        # Initialize arbitrage engine
        self.arb_engine = ArbitrageEngine(
            event_bus=self.event_bus,
            market_mapper=self.market_mapper,
            latency_tracker=self.latency_tracker,
            config=self.config.strategy.model_dump(),
        )
        await self.arb_engine.start()

        # Initialize execution engine
        self.exec_engine = ExecutionEngine(
            event_bus=self.event_bus,
            connectors=self.connectors,
            config={
                "mode": self.config.bot.mode,
                "default_order_type": "limit",
                "max_position_size_usd": 100,
                "max_open_positions": self.config.strategy.max_open_positions,
            },
        )
        await self.exec_engine.start()

        # Initialize monitoring
        if self.config.monitoring.enabled:
            self.monitor = BotMonitor(
                event_bus=self.event_bus,
                config=self.config.monitoring.model_dump(),
            )
            await self.monitor.start()

            self.dashboard = ConsoleDashboard(self.monitor)
            await self.dashboard.start()

        # Auto-discover and map markets
        await self._discover_markets()

        # Start all data sources
        for source in self.data_sources:
            await source.start()

        self._running = True

        # Publish bot started event
        await self.event_bus.publish(Events.BOT_STARTED, {
            "name": self.config.bot.name,
            "mode": self.config.bot.mode,
            "data_sources": len(self.data_sources),
            "connectors": len(self.connectors),
        })

        logger.info(
            f"Bot fully started | "
            f"Data sources: {len(self.data_sources)} | "
            f"Connectors: {len(self.connectors)} | "
            f"Mapped markets: {self.market_mapper.registered_count}"
        )

    async def stop(self) -> None:
        """Gracefully stop all components."""
        logger.info("Shutting down bot...")
        self._running = False

        # Stop in reverse order
        if self.dashboard:
            await self.dashboard.stop()
        if self.monitor:
            await self.monitor.stop()

        for source in self.data_sources:
            await source.stop()

        if self.exec_engine:
            await self.exec_engine.stop()
        if self.arb_engine:
            await self.arb_engine.stop()

        for connector in self.connectors.values():
            await connector.stop()

        await self.event_bus.stop()

        await self.event_bus.publish(Events.BOT_STOPPED, {})
        logger.info("Bot stopped cleanly")

    async def run_forever(self) -> None:
        """Run the bot until interrupted."""
        await self.start()

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Keep running
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if self._running:
                await self.stop()

    # ---- Initialization helpers ----

    async def _init_connectors(self) -> None:
        """Initialize prediction market connectors."""
        # Polymarket
        if self.config.markets.polymarket.enabled:
            poly = PolymarketConnector(
                event_bus=self.event_bus,
                config=self.config.markets.polymarket.model_dump(),
            )
            await poly.start()
            self.connectors[Platform.POLYMARKET] = poly
            logger.info("Polymarket connector initialized")

        # Kalshi
        if self.config.markets.kalshi.enabled:
            kalshi = KalshiConnector(
                event_bus=self.event_bus,
                config=self.config.markets.kalshi.model_dump(),
            )
            await kalshi.start()
            self.connectors[Platform.KALSHI] = kalshi
            logger.info("Kalshi connector initialized")

    async def _init_data_sources(self) -> None:
        """Initialize data source adapters."""
        ds_config = self.config.data_sources

        # ESPN
        if ds_config.espn.enabled:
            espn = ESPNDataSource(
                event_bus=self.event_bus,
                config=ds_config.espn.model_dump(),
            )
            self.data_sources.append(espn)

        # Weather - NWS
        if ds_config.weather.enabled:
            nws_config = ds_config.weather.providers.get("nws")
            if nws_config:
                nws = NWSWeatherSource(
                    event_bus=self.event_bus,
                    config={
                        **nws_config.model_dump(),
                        "tracked_locations": [loc.model_dump() for loc in ds_config.weather.tracked_locations],
                    },
                )
                self.data_sources.append(nws)

            # Weather - OpenWeather
            ow_config = ds_config.weather.providers.get("openweather")
            if ow_config and ow_config.api_key:
                ow = OpenWeatherSource(
                    event_bus=self.event_bus,
                    config={
                        **ow_config.model_dump(),
                        "tracked_locations": [loc.model_dump() for loc in ds_config.weather.tracked_locations],
                    },
                )
                self.data_sources.append(ow)

        # News
        if ds_config.news.enabled:
            for provider_name, provider_config in ds_config.news.providers.items():
                if provider_name == "newsapi" and provider_config.api_key:
                    newsapi = NewsAPISource(
                        event_bus=self.event_bus,
                        config={
                            **provider_config.model_dump(),
                            "tracked_keywords": ds_config.news.tracked_keywords,
                        },
                    )
                    self.data_sources.append(newsapi)
                elif provider_name == "gdelt":
                    gdelt = GDELTSource(
                        event_bus=self.event_bus,
                        config={
                            **provider_config.model_dump(),
                            "tracked_keywords": ds_config.news.tracked_keywords,
                        },
                    )
                    self.data_sources.append(gdelt)

        # Crypto
        if ds_config.crypto.enabled:
            binance_config = ds_config.crypto.providers.get("binance")
            if binance_config:
                binance = BinanceWebSocketSource(
                    event_bus=self.event_bus,
                    config={
                        **binance_config.model_dump(),
                        "tracked_pairs": ds_config.crypto.tracked_pairs,
                    },
                )
                self.data_sources.append(binance)

        logger.info(f"Initialized {len(self.data_sources)} data sources")

    async def _discover_markets(self) -> None:
        """Auto-discover active markets and register them with the mapper."""
        for platform, connector in self.connectors.items():
            try:
                if hasattr(connector, "get_active_markets"):
                    markets = await connector.get_active_markets(limit=50)
                    for market in markets:
                        self.market_mapper.auto_map_from_question(market)
                    logger.info(f"Discovered {len(markets)} markets on {platform.value}")
            except Exception:
                logger.exception(f"Error discovering markets on {platform.value}")
