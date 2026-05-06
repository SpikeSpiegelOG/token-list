import { describe, expect, it } from 'vitest';
import { ema, emaSeries } from './ema.js';

describe('emaSeries', () => {
  it('returns input when length is 0', () => {
    expect(emaSeries([], 10)).toEqual([]);
  });

  it('seeds with the first value', () => {
    const out = emaSeries([100, 100, 100], 10);
    expect(out).toEqual([100, 100, 100]);
  });

  it('matches the recurrence ema = price*k + prev*(1-k)', () => {
    const period = 5;
    const k = 2 / (period + 1);
    const prices = [10, 12, 11, 13, 14, 13, 12];
    const expected: number[] = [prices[0]!];
    for (let i = 1; i < prices.length; i++) {
      expected.push(prices[i]! * k + expected[i - 1]! * (1 - k));
    }
    const out = emaSeries(prices, period);
    expect(out).toHaveLength(prices.length);
    for (let i = 0; i < prices.length; i++) {
      expect(out[i]).toBeCloseTo(expected[i]!, 10);
    }
  });

  it('rejects invalid periods', () => {
    expect(() => emaSeries([1, 2, 3], 0)).toThrow();
    expect(() => emaSeries([1, 2, 3], -1)).toThrow();
  });
});

describe('ema (streaming)', () => {
  it('matches the batched series', () => {
    const prices = [10, 12, 11, 13, 14, 13, 12];
    const period = 5;
    const expected = emaSeries(prices, period);
    const e = new ema(period);
    const got = prices.map((p) => e.update(p));
    for (let i = 0; i < prices.length; i++) {
      expect(got[i]).toBeCloseTo(expected[i]!, 10);
    }
  });

  it('reset() clears state', () => {
    const e = new ema(5);
    e.update(100);
    expect(e.get()).toBe(100);
    e.reset();
    expect(e.get()).toBeNull();
    expect(e.update(50)).toBe(50);
  });
});
