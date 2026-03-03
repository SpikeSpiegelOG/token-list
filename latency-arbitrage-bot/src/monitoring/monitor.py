"""Real-time monitoring and dashboard for the arbitrage bot.

Provides:
- Console dashboard with live stats (Rich-based)
- Trade history logging to SQLite
- Performance metrics tracking
- Alert system for significant events
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiosqlite

from src.core.event_bus import EventBus, Events
from src.core.models import Order, TradeSignal

logger = logging.getLogger(__name__)


class BotMonitor:
    """Monitors bot activity and maintains trade history."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        self.event_bus = event_bus
        self.config = config
        self.db_path = config.get("trade_history_db", "data/trades.db")
        self._db: aiosqlite.Connection | None = None

        # Live metrics
        self.metrics = {
            "start_time": time.time(),
            "signals_received": 0,
            "trades_executed": 0,
            "fills": 0,
            "rejects": 0,
            "total_pnl": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "avg_fill_latency_ms": 0.0,
            "active_data_sources": 0,
            "active_markets": 0,
        }
        self._fill_latencies: list[float] = []

    async def start(self) -> None:
        """Initialize DB and subscribe to events."""
        await self._init_db()

        self.event_bus.subscribe(Events.TRADE_SIGNAL, self._on_trade_signal)
        self.event_bus.subscribe(Events.ORDER_FILLED, self._on_order_filled)
        self.event_bus.subscribe(Events.ORDER_REJECTED, self._on_order_rejected)
        self.event_bus.subscribe(Events.ORDER_SUBMITTED, self._on_order_submitted)
        self.event_bus.subscribe(Events.DATA_SIGNAL, self._on_data_signal)

        logger.info(f"Monitor started, trade history: {self.db_path}")

    async def stop(self) -> None:
        """Close DB and cleanup."""
        if self._db:
            await self._db.close()
        logger.info("Monitor stopped")

    async def _init_db(self) -> None:
        """Initialize SQLite database for trade history."""
        import os
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                signal_id TEXT,
                platform TEXT,
                market_id TEXT,
                side TEXT,
                order_type TEXT,
                price REAL,
                size REAL,
                fill_price REAL,
                fill_size REAL,
                status TEXT,
                edge REAL,
                confidence REAL,
                signal_source TEXT,
                signal_type TEXT,
                signal_age_ms INTEGER,
                fill_latency_ms INTEGER,
                pnl REAL DEFAULT 0,
                notes TEXT
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                source TEXT,
                signal_type TEXT,
                event_id TEXT,
                data TEXT,
                confidence REAL,
                matched_markets INTEGER DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS latency_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                source TEXT,
                platform TEXT,
                latency_ms REAL,
                signal_type TEXT
            )
        """)
        await self._db.commit()

    async def _on_data_signal(self, signal: Any) -> None:
        self.metrics["signals_received"] += 1

    async def _on_trade_signal(self, signal: TradeSignal) -> None:
        self.metrics["trades_executed"] += 1
        if self.config.get("log_all_signals", True):
            logger.info(
                f"[MONITOR] Trade Signal | {signal.side.value} {signal.platform.value}:{signal.market_id} | "
                f"Edge: {signal.edge:.4f} | Conf: {signal.confidence:.2f} | "
                f"Size: ${signal.suggested_size_usd:.2f}"
            )

    async def _on_order_submitted(self, order: Order) -> None:
        logger.info(f"[MONITOR] Order submitted: {order.order_id} -> {order.platform.value}")

    async def _on_order_filled(self, order: Order) -> None:
        self.metrics["fills"] += 1

        # Calculate fill latency
        latency_ms = None
        if order.trade_signal and order.filled_at_ms:
            latency_ms = order.filled_at_ms - order.trade_signal.data_signal.timestamp_ms
            self._fill_latencies.append(latency_ms)
            if self._fill_latencies:
                self.metrics["avg_fill_latency_ms"] = sum(self._fill_latencies) / len(self._fill_latencies)

        # Log to DB
        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO trades
                       (signal_id, platform, market_id, side, order_type, price, size,
                        fill_price, fill_size, status, edge, confidence,
                        signal_source, signal_type, signal_age_ms, fill_latency_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order.trade_signal.signal_id if order.trade_signal else "",
                        order.platform.value,
                        order.market_id,
                        order.side.value,
                        order.order_type.value,
                        order.price,
                        order.size,
                        order.fill_price,
                        order.fill_size,
                        order.status.value,
                        order.trade_signal.edge if order.trade_signal else 0,
                        order.trade_signal.confidence if order.trade_signal else 0,
                        order.trade_signal.data_signal.source if order.trade_signal else "",
                        order.trade_signal.data_signal.signal_type.value if order.trade_signal else "",
                        order.trade_signal.data_signal.age_ms if order.trade_signal else 0,
                        latency_ms,
                    ),
                )
                await self._db.commit()
            except Exception:
                logger.exception("Error logging trade to DB")

        logger.info(
            f"[MONITOR] FILL #{self.metrics['fills']} | "
            f"{order.side.value} {order.platform.value}:{order.market_id} @ "
            f"{order.fill_price or order.price:.4f} | "
            f"Latency: {latency_ms}ms"
        )

    async def _on_order_rejected(self, order: Order) -> None:
        self.metrics["rejects"] += 1
        logger.warning(f"[MONITOR] Order REJECTED: {order.error_message}")

    def get_dashboard_data(self) -> dict[str, Any]:
        """Get data for console dashboard display."""
        uptime = time.time() - self.metrics["start_time"]
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)

        return {
            "uptime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "signals_received": self.metrics["signals_received"],
            "trades_executed": self.metrics["trades_executed"],
            "fills": self.metrics["fills"],
            "rejects": self.metrics["rejects"],
            "fill_rate": (
                f"{self.metrics['fills'] / self.metrics['trades_executed'] * 100:.1f}%"
                if self.metrics["trades_executed"] > 0
                else "N/A"
            ),
            "avg_latency": f"{self.metrics['avg_fill_latency_ms']:.0f}ms",
            "total_pnl": f"${self.metrics['total_pnl']:.2f}",
        }


class ConsoleDashboard:
    """Rich-based console dashboard for live monitoring."""

    def __init__(self, monitor: BotMonitor, refresh_interval: float = 2.0) -> None:
        self.monitor = monitor
        self.refresh_interval = refresh_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._render_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _render_loop(self) -> None:
        """Periodically print dashboard stats to console."""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.live import Live

            console = Console()

            with Live(self._build_table(), refresh_per_second=1, console=console) as live:
                while True:
                    await asyncio.sleep(self.refresh_interval)
                    live.update(self._build_table())

        except ImportError:
            # Fallback if Rich not available
            while True:
                data = self.monitor.get_dashboard_data()
                print(
                    f"\r[{data['uptime']}] "
                    f"Signals: {data['signals_received']} | "
                    f"Trades: {data['trades_executed']} | "
                    f"Fills: {data['fills']} | "
                    f"Latency: {data['avg_latency']} | "
                    f"PnL: {data['total_pnl']}",
                    end="",
                    flush=True,
                )
                await asyncio.sleep(self.refresh_interval)
        except asyncio.CancelledError:
            pass

    def _build_table(self) -> "Table":
        from rich.table import Table

        data = self.monitor.get_dashboard_data()

        table = Table(title="SPIKE ARB BOT - Live Dashboard", show_header=True)
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value", style="green", width=15)

        table.add_row("Uptime", data["uptime"])
        table.add_row("Signals Received", str(data["signals_received"]))
        table.add_row("Trades Executed", str(data["trades_executed"]))
        table.add_row("Fills", str(data["fills"]))
        table.add_row("Rejects", str(data["rejects"]))
        table.add_row("Fill Rate", data["fill_rate"])
        table.add_row("Avg Latency", data["avg_latency"])
        table.add_row("Total PnL", data["total_pnl"])

        return table
