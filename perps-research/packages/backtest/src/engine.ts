import type { Bar, Order, Side } from '@perps/core';
import { computeMetrics } from './metrics.js';
import { simpleSlippage } from './slippage.js';
import type {
  BacktestConfig,
  BacktestResult,
  EquityPoint,
  StrategyAction,
  TradeRecord,
} from './types.js';

/**
 * Single-symbol event-driven backtester.
 *
 * Conventions:
 *   - position > 0  → long N base units
 *   - position < 0  → short |N| base units
 *   - position == 0 → flat
 *
 * Fills happen at the close of the bar that produced the signal, plus a
 * half-spread in the unfavorable direction, plus taker fee. This matches
 * what a live strategy issuing market orders at bar close would experience.
 *
 * Open positions are marked-to-market at the bar's close on every step.
 * No funding payments are charged in v1; Phase 3.5 will add them when the
 * funding feed is wired into the historical replay.
 */
export function runBacktest(cfg: BacktestConfig): BacktestResult {
  const slippage =
    cfg.slippage ??
    simpleSlippage({ takerFee: cfg.takerFee, halfSpread: cfg.halfSpread });

  const bars = cfg.bars;
  if (bars.length === 0) {
    return {
      equity: [],
      trades: [],
      orders: [],
      metrics: {
        finalEquity: cfg.initialCash,
        totalReturn: 0,
        sharpe: 0,
        sortino: 0,
        maxDrawdown: 0,
        winRate: 0,
        expectancy: 0,
        trades: 0,
        exposure: 0,
      },
      strategy: cfg.strategy.name,
      startTs: 0,
      endTs: 0,
    };
  }

  cfg.strategy.init?.();

  let cash = cfg.initialCash;
  let position = 0; // signed base units
  let avgEntry = 0;
  let openTs = 0;
  let openReason: string | undefined;

  const equity: EquityPoint[] = [];
  const trades: TradeRecord[] = [];
  const orders: Order[] = [];
  const history: Bar[] = [];

  let orderId = 0;
  const nextOrderId = () => `o${++orderId}`;

  const apply = (
    bar: Bar,
    action: StrategyAction,
  ): void => {
    if (action.type === 'hold') return;

    const desiredSize = (() => {
      if (action.type === 'long')
        return action.size ?? cfg.defaultSize;
      if (action.type === 'short')
        return -(action.size ?? cfg.defaultSize);
      return 0;
    })();

    if (desiredSize === position) return;

    // Close-then-open if direction flips, otherwise scale.
    const closing = position !== 0 && Math.sign(desiredSize) !== Math.sign(position);
    const sizeDelta = desiredSize - position;
    if (sizeDelta === 0) return;

    const side: Side = sizeDelta > 0 ? 'buy' : 'sell';
    const fill = slippage.fill({
      side,
      bar,
      intendedSize: Math.abs(sizeDelta),
      isMarketEntry: position === 0 || closing,
    });

    orders.push({
      id: nextOrderId(),
      ts: bar.ts,
      symbol: bar.symbol,
      side,
      type: 'mkt',
      size: Math.abs(sizeDelta),
      price: fill.price,
    });

    // If we cross through flat (e.g. long → short), close the existing
    // position fully, record the trade, then open the new direction at
    // the same fill price minus the appropriate fee share.
    if (closing && position !== 0) {
      const closeSize = Math.min(Math.abs(position), Math.abs(sizeDelta));
      const closeSide: 'long' | 'short' = position > 0 ? 'long' : 'short';
      const grossPnl =
        closeSide === 'long'
          ? (fill.price - avgEntry) * closeSize
          : (avgEntry - fill.price) * closeSize;
      // Allocate fee proportionally to the closing portion.
      const feeShare =
        fill.fee * (closeSize / Math.abs(sizeDelta));
      const pnl = grossPnl - feeShare;
      cash += grossPnl - feeShare;
      trades.push({
        openTs,
        closeTs: bar.ts,
        side: closeSide,
        entry: avgEntry,
        exit: fill.price,
        size: closeSize,
        pnl,
        ret: avgEntry > 0 ? pnl / (avgEntry * closeSize) : 0,
        reason: action.reason ?? openReason,
      });

      const remainder = Math.abs(sizeDelta) - closeSize;
      if (remainder > 0) {
        // Opening a fresh position in the new direction.
        position = Math.sign(sizeDelta) * remainder;
        avgEntry = fill.price;
        openTs = bar.ts;
        openReason = action.reason;
        cash -= fill.fee - feeShare;
      } else {
        position = 0;
        avgEntry = 0;
        openTs = 0;
        openReason = undefined;
        cash -= fill.fee - feeShare;
      }
      return;
    }

    if (position === 0) {
      // Opening a new position.
      position = desiredSize;
      avgEntry = fill.price;
      openTs = bar.ts;
      openReason = action.reason;
      cash -= fill.fee;
      return;
    }

    // Scaling the position in the same direction (no PnL realised here).
    const newAbs = Math.abs(position) + Math.abs(sizeDelta);
    avgEntry =
      (avgEntry * Math.abs(position) + fill.price * Math.abs(sizeDelta)) / newAbs;
    position = desiredSize;
    cash -= fill.fee;
  };

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i]!;
    history.push(bar);

    // Mark equity using the prior position (signal acts on close).
    const equityBefore =
      cash +
      (position !== 0 ? (bar.c - avgEntry) * position : 0);

    const action = cfg.strategy.onBar(bar, {
      history,
      position,
      avgEntry,
      equity: equityBefore,
      ts: bar.ts,
    });

    apply(bar, action);

    // Mark equity after fill.
    const equityAfter =
      cash + (position !== 0 ? (bar.c - avgEntry) * position : 0);

    equity.push({ ts: bar.ts, equity: equityAfter, position });
  }

  // Force-close any open position at the last bar's close.
  if (position !== 0) {
    const lastBar = bars[bars.length - 1]!;
    const closeSide: 'long' | 'short' = position > 0 ? 'long' : 'short';
    const fill = slippage.fill({
      side: position > 0 ? 'sell' : 'buy',
      bar: lastBar,
      intendedSize: Math.abs(position),
      isMarketEntry: false,
    });
    const grossPnl =
      closeSide === 'long'
        ? (fill.price - avgEntry) * Math.abs(position)
        : (avgEntry - fill.price) * Math.abs(position);
    const pnl = grossPnl - fill.fee;
    cash += grossPnl - fill.fee;
    trades.push({
      openTs,
      closeTs: lastBar.ts,
      side: closeSide,
      entry: avgEntry,
      exit: fill.price,
      size: Math.abs(position),
      pnl,
      ret: avgEntry > 0 ? pnl / (avgEntry * Math.abs(position)) : 0,
      reason: 'eod_close',
    });
    const lastIdx = equity.length - 1;
    if (lastIdx >= 0) {
      equity[lastIdx] = { ts: lastBar.ts, equity: cash, position: 0 };
    }
    position = 0;
  }

  const metrics = computeMetrics(equity, trades, {
    initialEquity: cfg.initialCash,
  });

  return {
    equity,
    trades,
    orders,
    metrics,
    strategy: cfg.strategy.name,
    startTs: bars[0]!.ts,
    endTs: bars[bars.length - 1]!.ts,
  };
}
