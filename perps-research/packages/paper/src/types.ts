import type { Strategy } from '@perps/backtest';

export interface PaperConfig {
  /** stable identifier for this run; reused across server restarts */
  runId: string;
  venue: string;
  symbol: string;
  strategyId: string;
  strategyParams?: Record<string, number>;
  /** strategy instance built via @perps/strategies registry */
  strategy: Strategy;
  initialCash: number;
  defaultSize: number;
  takerFee?: number;
  halfSpread?: number;
}

export interface PaperRunStatus {
  runId: string;
  venue: string;
  symbol: string;
  strategy: string;
  strategyId: string;
  startedAt: number;
  /** epoch ms of last bar seen by the engine */
  lastBarTs: number | null;
  /** equity right now (cash + open-position MTM at last seen close) */
  equity: number;
  initialCash: number;
  position: number;
  avgEntry: number;
  bars: number;
  fills: number;
}

export interface PaperFillRow {
  ts: number;
  side: 'buy' | 'sell';
  price: number;
  size: number;
  fee: number;
  reason: string;
}
