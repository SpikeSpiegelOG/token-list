export { runBacktest } from './engine.js';
export { computeMetrics } from './metrics.js';
export { simpleSlippage } from './slippage.js';
export type {
  BacktestConfig,
  BacktestResult,
  EquityPoint,
  Strategy,
  StrategyAction,
  StrategyContext,
  TradeRecord,
  Metrics,
  SlippageModel,
} from './types.js';
