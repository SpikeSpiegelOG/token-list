"""Position sizing using Kelly Criterion.

Kelly Criterion calculates the optimal bet size to maximize long-term growth.
We use fractional Kelly (quarter-Kelly by default) for safety.

Full Kelly: f* = (bp - q) / b
Where:
    b = odds received (profit/loss ratio)
    p = probability of winning
    q = 1 - p = probability of losing
    f* = fraction of bankroll to bet

Quarter Kelly: f = f* / 4

Platform fee awareness:
- Polymarket: 0% maker/taker fees
- Kalshi: 0.07 × contracts × price × (1-price)
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import Platform

logger = logging.getLogger(__name__)


def estimate_kalshi_fee_rate(price: float) -> float:
    """Estimate Kalshi fee as a fraction of contract value.

    Fee formula: 0.07 × contracts × price × (1-price)
    As a rate per contract at given price: 0.07 × price × (1-price)
    Maximum fee rate is at price=0.50: 0.07 × 0.25 = 0.0175 (1.75%)
    """
    return 0.07 * price * (1.0 - price)


class PositionSizer:
    """Calculates position sizes using Kelly Criterion with risk limits."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.kelly_fraction = config.get("kelly_fraction", 0.25)  # Quarter Kelly
        self.max_bet_usd = config.get("max_bet_size_usd", 50.0)
        self.min_bet_usd = config.get("min_bet_size_usd", 5.0)
        self.max_daily_loss = config.get("max_daily_loss_usd", 200.0)
        self.max_open_positions = config.get("max_open_positions", 10)
        self.bankroll = config.get("initial_bankroll_usd", 1000.0)

        # Track daily P&L
        self._daily_loss = 0.0
        self._open_position_count = 0

    def calculate_size(
        self,
        edge: float,
        confidence: float,
        current_price: float,
        platform: Platform = Platform.POLYMARKET,
    ) -> float:
        """Calculate optimal position size in USD.

        Args:
            edge: Our estimated edge (fair_value - market_price)
            confidence: Signal confidence (0-1)
            current_price: Current market price we'd be buying at
            platform: Trading platform (affects fee calculation)

        Returns:
            Suggested position size in USD, or 0 if no trade.
        """
        # Risk checks first
        if self._daily_loss >= self.max_daily_loss:
            logger.warning("Daily loss limit reached — no new positions")
            return 0.0

        if self._open_position_count >= self.max_open_positions:
            logger.warning("Max open positions reached — no new positions")
            return 0.0

        if current_price <= 0 or current_price >= 1:
            return 0.0

        # Subtract platform fees from expected profit
        fee_rate = 0.0
        if platform == Platform.KALSHI:
            fee_rate = estimate_kalshi_fee_rate(current_price)
        # Polymarket: 0% fees

        # Adjust edge for fees — if edge doesn't exceed fee, no trade
        effective_edge = edge - fee_rate
        if effective_edge <= 0:
            logger.debug(
                f"Edge {edge:.4f} doesn't exceed fee rate {fee_rate:.4f} on {platform.value}, skipping"
            )
            return 0.0

        # Kelly Criterion for binary outcomes
        win_prob = min(current_price + effective_edge, 0.99)
        loss_prob = 1.0 - win_prob

        # Profit if we win: (1 - current_price - fee) per dollar of contracts
        # Loss if we lose: (current_price + fee) per dollar of contracts
        net_win = (1.0 - current_price) - fee_rate
        net_loss = current_price + fee_rate

        if net_win <= 0:
            return 0.0

        b = net_win / net_loss  # Fee-adjusted odds ratio

        # Full Kelly
        kelly_full = (b * win_prob - loss_prob) / b

        if kelly_full <= 0:
            return 0.0  # Negative Kelly means don't bet

        # Fractional Kelly adjusted by confidence
        kelly_adjusted = kelly_full * self.kelly_fraction * confidence

        # Convert to USD
        size_usd = self.bankroll * kelly_adjusted

        # Apply limits
        size_usd = max(self.min_bet_usd, min(size_usd, self.max_bet_usd))

        # Don't bet more than remaining daily budget
        remaining_budget = self.max_daily_loss - self._daily_loss
        size_usd = min(size_usd, remaining_budget)

        logger.debug(
            f"Position size: ${size_usd:.2f} | "
            f"Kelly full: {kelly_full:.4f} | "
            f"Kelly adj: {kelly_adjusted:.4f} | "
            f"Edge: {edge:.4f} (eff: {effective_edge:.4f}) | "
            f"Fee rate: {fee_rate:.4f} | "
            f"Platform: {platform.value} | "
            f"Confidence: {confidence:.2f}"
        )

        return round(size_usd, 2)

    def record_trade_result(self, pnl: float) -> None:
        """Record a trade result for daily tracking."""
        if pnl < 0:
            self._daily_loss += abs(pnl)

    def open_position(self) -> None:
        self._open_position_count += 1

    def close_position(self) -> None:
        self._open_position_count = max(0, self._open_position_count - 1)

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of each trading day)."""
        self._daily_loss = 0.0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "daily_loss": self._daily_loss,
            "remaining_daily_budget": self.max_daily_loss - self._daily_loss,
            "open_positions": self._open_position_count,
            "max_positions": self.max_open_positions,
            "kelly_fraction": self.kelly_fraction,
        }
