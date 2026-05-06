import { describe, expect, it } from 'vitest';
import { computeMetrics } from './metrics.js';

describe('computeMetrics', () => {
  it('returns 0s on empty input', () => {
    const m = computeMetrics([], []);
    expect(m.finalEquity).toBe(0);
    expect(m.totalReturn).toBe(0);
    expect(m.sharpe).toBe(0);
    expect(m.maxDrawdown).toBe(0);
  });

  it('totalReturn is final/initial - 1', () => {
    const m = computeMetrics(
      [
        { ts: 0, equity: 1000, position: 0 },
        { ts: 1, equity: 1100, position: 0 },
      ],
      [],
      { initialEquity: 1000 },
    );
    expect(m.totalReturn).toBeCloseTo(0.1, 8);
  });

  it('maxDrawdown captures worst peak-to-trough', () => {
    const m = computeMetrics(
      [
        { ts: 0, equity: 100, position: 0 },
        { ts: 1, equity: 120, position: 0 },
        { ts: 2, equity: 90, position: 0 },
        { ts: 3, equity: 110, position: 0 },
        { ts: 4, equity: 60, position: 0 },
      ],
      [],
    );
    // peak 120 → trough 60 → DD = 50%
    expect(m.maxDrawdown).toBeCloseTo(0.5, 8);
  });

  it('winRate ignores zero-pnl trades correctly', () => {
    const m = computeMetrics(
      [],
      [
        { openTs: 0, closeTs: 1, side: 'long', entry: 1, exit: 1.1, size: 1, pnl: 0.1, ret: 0.1 },
        { openTs: 1, closeTs: 2, side: 'long', entry: 1, exit: 0.9, size: 1, pnl: -0.1, ret: -0.1 },
        { openTs: 2, closeTs: 3, side: 'long', entry: 1, exit: 1.05, size: 1, pnl: 0.05, ret: 0.05 },
      ],
    );
    expect(m.trades).toBe(3);
    expect(m.winRate).toBeCloseTo(2 / 3, 8);
  });

  it('exposure is the fraction of bars with a non-zero position', () => {
    const m = computeMetrics(
      [
        { ts: 0, equity: 100, position: 0 },
        { ts: 1, equity: 100, position: 1 },
        { ts: 2, equity: 100, position: 1 },
        { ts: 3, equity: 100, position: 0 },
      ],
      [],
    );
    expect(m.exposure).toBeCloseTo(0.5, 8);
  });
});
