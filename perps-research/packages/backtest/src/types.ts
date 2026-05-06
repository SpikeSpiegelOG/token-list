import type { Bar, Order, Side } from '@perps/core';

export interface EquityPoint {
  ts: number;
  equity: number;
  position: number;
}

export interface TradeRecord {
  /** open and close timestamps in ms */
  openTs: number;
  closeTs: number;
  side: 'long' | 'short';
  entry: number;
  exit: number;
  size: number;
  /** absolute pnl in quote currency (after fees) */
  pnl: number;
  /** % return on this trade's notional */
  ret: number;
  reason?: string;
}

export interface Metrics {
  finalEquity: number;
  totalReturn: number;
  sharpe: number;
  sortino: number;
  maxDrawdown: number;
  winRate: number;
  expectancy: number;
  trades: number;
  exposure: number;
}

/** Maps an intended order to a fill price + per-side fee. */
export interface SlippageModel {
  fill(opts: {
    side: Side;
    bar: Bar;
    intendedSize: number;
    isMarketEntry: boolean;
  }): { price: number; fee: number };
}

export interface StrategyContext {
  /** read-only history of bars seen so far, including the current one */
  history: readonly Bar[];
  /** open position: positive = long, negative = short, 0 = flat */
  position: number;
  /** average entry price of the open position (0 if flat) */
  avgEntry: number;
  /** current equity (cash + open-position MTM) */
  equity: number;
  /** epoch ms of the bar driving this call */
  ts: number;
}

export type StrategyAction =
  | { type: 'long'; size?: number; reason?: string }
  | { type: 'short'; size?: number; reason?: string }
  | { type: 'flat'; reason?: string }
  | { type: 'hold' };

export interface Strategy {
  readonly name: string;
  /** initialise per-run state; called before the first bar */
  init?(): void;
  onBar(bar: Bar, ctx: StrategyContext): StrategyAction;
}

export interface BacktestConfig {
  bars: readonly Bar[];
  strategy: Strategy;
  initialCash: number;
  /** size in base units when the strategy doesn't specify */
  defaultSize: number;
  /** taker fee as a fraction (e.g. 0.0004 = 4bp) */
  takerFee?: number;
  /** half-spread expressed as fraction of price (e.g. 0.0002 = 2bp) */
  halfSpread?: number;
  /** kept for future per-bar work; unused in v1 */
  slippage?: SlippageModel;
}

export interface BacktestResult {
  equity: EquityPoint[];
  trades: TradeRecord[];
  metrics: Metrics;
  /** the orders the engine actually filled (for debugging) */
  orders: Order[];
  strategy: string;
  startTs: number;
  endTs: number;
}
