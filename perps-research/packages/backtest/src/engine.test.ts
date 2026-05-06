import { describe, expect, it } from 'vitest';
import type { Bar } from '@perps/core';
import { runBacktest } from './engine.js';
import type { Strategy } from './types.js';

function makeBars(prices: number[], startTs = 60_000, stepMs = 60_000): Bar[] {
  return prices.map((p, i) => ({
    venue: 'hyperliquid',
    symbol: 'BTC',
    ts: startTs + i * stepMs,
    o: p,
    h: p,
    l: p,
    c: p,
    v: 1,
    tf: '1m',
  }));
}

const HOLD: Strategy = {
  name: 'hold',
  onBar: () => ({ type: 'hold' }),
};

describe('runBacktest', () => {
  it('produces equity points for every bar even on hold', () => {
    const r = runBacktest({
      bars: makeBars([100, 101, 102]),
      strategy: HOLD,
      initialCash: 1000,
      defaultSize: 1,
      takerFee: 0,
      halfSpread: 0,
    });
    expect(r.equity).toHaveLength(3);
    expect(r.equity.every((p) => p.position === 0)).toBe(true);
    expect(r.metrics.totalReturn).toBeCloseTo(0, 8);
    expect(r.trades).toHaveLength(0);
  });

  it('books a winning long with zero fees/slippage', () => {
    let phase = 0;
    const strat: Strategy = {
      name: 'long-once',
      onBar(_, ctx) {
        phase++;
        if (phase === 1) return { type: 'long', size: 1, reason: 'open' };
        if (phase === 3) return { type: 'flat', reason: 'close' };
        return { type: 'hold' };
      },
    };
    const r = runBacktest({
      bars: makeBars([100, 105, 110]),
      strategy: strat,
      initialCash: 1000,
      defaultSize: 1,
      takerFee: 0,
      halfSpread: 0,
    });
    expect(r.trades).toHaveLength(1);
    const t = r.trades[0]!;
    expect(t.side).toBe('long');
    expect(t.entry).toBeCloseTo(100, 8);
    expect(t.exit).toBeCloseTo(110, 8);
    expect(t.pnl).toBeCloseTo(10, 8);
    expect(r.metrics.finalEquity).toBeCloseTo(1010, 8);
  });

  it('charges taker fee + half-spread on each fill', () => {
    let phase = 0;
    const strat: Strategy = {
      name: 'long-once',
      onBar() {
        phase++;
        if (phase === 1) return { type: 'long', size: 1 };
        if (phase === 3) return { type: 'flat' };
        return { type: 'hold' };
      },
    };
    const r = runBacktest({
      bars: makeBars([100, 100, 100]),
      strategy: strat,
      initialCash: 1000,
      defaultSize: 1,
      takerFee: 0.0004,
      halfSpread: 0.0002,
    });
    // entry: buy at 100*(1+0.0002)=100.02, fee = 1*100.02*0.0004 = 0.040008
    // exit:  sell at 100*(1-0.0002)=99.98,  fee = 1*99.98*0.0004 = 0.039992
    // pnl   = (99.98 - 100.02) - fees ≈ -0.04 - 0.08 = -0.12
    expect(r.trades).toHaveLength(1);
    expect(r.trades[0]!.pnl).toBeLessThan(0);
    expect(r.metrics.finalEquity).toBeLessThan(1000);
    expect(r.metrics.finalEquity).toBeGreaterThan(999.7);
  });

  it('flips long → short with one signal', () => {
    let phase = 0;
    const strat: Strategy = {
      name: 'flip',
      onBar() {
        phase++;
        if (phase === 1) return { type: 'long', size: 1 };
        if (phase === 2) return { type: 'short', size: 1 };
        return { type: 'hold' };
      },
    };
    const r = runBacktest({
      bars: makeBars([100, 110, 100]),
      strategy: strat,
      initialCash: 1000,
      defaultSize: 1,
      takerFee: 0,
      halfSpread: 0,
    });
    // long opened at 100, closed at 110 (+$10), short opened at 110,
    // then forced-flat at 100 (+$10). Two trades total.
    expect(r.trades).toHaveLength(2);
    expect(r.trades[0]!.pnl).toBeCloseTo(10, 6);
    expect(r.trades[1]!.pnl).toBeCloseTo(10, 6);
    expect(r.metrics.finalEquity).toBeCloseTo(1020, 6);
  });

  it('force-closes any open position at end of run', () => {
    const strat: Strategy = {
      name: 'open-and-leave',
      onBar(_, ctx) {
        return ctx.position === 0 ? { type: 'long', size: 1 } : { type: 'hold' };
      },
    };
    const r = runBacktest({
      bars: makeBars([100, 101, 102]),
      strategy: strat,
      initialCash: 1000,
      defaultSize: 1,
      takerFee: 0,
      halfSpread: 0,
    });
    expect(r.trades).toHaveLength(1);
    expect(r.trades[0]!.reason).toBe('eod_close');
    expect(r.equity[r.equity.length - 1]!.position).toBe(0);
  });
});
