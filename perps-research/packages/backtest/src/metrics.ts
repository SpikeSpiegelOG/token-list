import type { EquityPoint, Metrics, TradeRecord } from './types.js';

const EPS = 1e-12;

/**
 * Pure metrics over an equity curve + trade list. Annualisation assumes
 * 1m bars (525_600 per year); pass bar-period count via opts for other
 * timeframes if needed.
 */
export function computeMetrics(
  equity: readonly EquityPoint[],
  trades: readonly TradeRecord[],
  opts: { barsPerYear?: number; initialEquity?: number } = {},
): Metrics {
  const barsPerYear = opts.barsPerYear ?? 525_600;
  const initial = opts.initialEquity ?? equity[0]?.equity ?? 0;
  const final = equity[equity.length - 1]?.equity ?? initial;
  const totalReturn = initial > 0 ? final / initial - 1 : 0;

  // Per-bar simple returns
  const rets: number[] = [];
  for (let i = 1; i < equity.length; i++) {
    const a = equity[i - 1]!.equity;
    const b = equity[i]!.equity;
    if (a > 0) rets.push(b / a - 1);
  }

  const mean = rets.length ? rets.reduce((s, x) => s + x, 0) / rets.length : 0;
  const variance =
    rets.length > 1
      ? rets.reduce((s, x) => s + (x - mean) ** 2, 0) / (rets.length - 1)
      : 0;
  const std = Math.sqrt(variance);

  const sharpe =
    std > EPS ? (mean / std) * Math.sqrt(barsPerYear) : 0;

  const negs = rets.filter((r) => r < 0);
  const downStd = negs.length
    ? Math.sqrt(negs.reduce((s, x) => s + x * x, 0) / negs.length)
    : 0;
  const sortino = downStd > EPS ? (mean / downStd) * Math.sqrt(barsPerYear) : 0;

  // Max drawdown on equity
  let peak = -Infinity;
  let maxDD = 0;
  for (const p of equity) {
    if (p.equity > peak) peak = p.equity;
    if (peak > 0) {
      const dd = (peak - p.equity) / peak;
      if (dd > maxDD) maxDD = dd;
    }
  }

  const wins = trades.filter((t) => t.pnl > 0);
  const winRate = trades.length ? wins.length / trades.length : 0;
  const expectancy = trades.length
    ? trades.reduce((s, t) => s + t.pnl, 0) / trades.length
    : 0;

  // Exposure: fraction of bars where position != 0
  const exposed = equity.filter((p) => p.position !== 0).length;
  const exposure = equity.length ? exposed / equity.length : 0;

  return {
    finalEquity: final,
    totalReturn,
    sharpe,
    sortino,
    maxDrawdown: maxDD,
    winRate,
    expectancy,
    trades: trades.length,
    exposure,
  };
}
