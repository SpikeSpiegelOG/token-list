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
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
    ) -> float:
        """Calculate optimal position size in USD.

        Args:
            edge: Our estimated edge (fair_value - market_price)
            confidence: Signal confidence (0-1)
            current_price: Current market price we'd be buying at

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

        # Kelly Criterion for binary outcomes
        # In prediction markets: buy at price p, win (1-p) profit, lose p
        win_prob = min(current_price + edge, 0.99)  # Our estimated true probability
        loss_prob = 1.0 - win_prob

        if current_price <= 0 or current_price >= 1:
            return 0.0

        # Profit if we win: (1 - current_price) per dollar of contracts
        # Loss if we lose: current_price per dollar of contracts
        b = (1.0 - current_price) / current_price  # Odds ratio

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
            f"Edge: {edge:.4f} | "
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
