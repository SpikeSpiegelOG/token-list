import { describe, expect, it } from 'vitest';
import type { Tick } from '@perps/core';
import { BarRollup } from './rollup.js';

const t = (ts: number, price: number, size = 1): Tick => ({
  venue: 'hyperliquid',
  symbol: 'BTC',
  ts,
  price,
  size,
  side: 'buy',
});

describe('BarRollup 1m', () => {
  it('returns the open bar updated by each tick', () => {
    const r = new BarRollup('1m');
    const a = r.ingest(t(60_000, 100));
    expect(a.closed).toBeNull();
    expect(a.open).toMatchObject({ ts: 60_000, o: 100, h: 100, l: 100, c: 100, v: 1 });

    const b = r.ingest(t(60_500, 102, 2));
    expect(b.closed).toBeNull();
    expect(b.open).toMatchObject({ ts: 60_000, o: 100, h: 102, l: 100, c: 102, v: 3 });

    const c = r.ingest(t(60_800, 99));
    expect(c.open).toMatchObject({ o: 100, h: 102, l: 99, c: 99, v: 4 });
  });

  it('closes a bar when ticks cross the bucket boundary', () => {
    const r = new BarRollup('1m');
    const closed: unknown[] = [];
    r.onClose((b) => closed.push(b));

    r.ingest(t(60_000, 100));
    r.ingest(t(60_500, 102, 2));
    const next = r.ingest(t(120_001, 105));
    expect(next.closed).not.toBeNull();
    expect(next.closed).toMatchObject({
      ts: 60_000,
      o: 100,
      h: 102,
      l: 100,
      c: 102,
      v: 3,
      tf: '1m',
    });
    expect(closed).toHaveLength(1);
    expect(next.open).toMatchObject({ ts: 120_000, o: 105, h: 105, l: 105, c: 105 });
  });

  it('keeps separate buckets per (venue,symbol)', () => {
    const r = new BarRollup('1m');
    const eth: Tick = { ...t(60_100, 3000), symbol: 'ETH' };
    r.ingest(t(60_000, 100));
    const e = r.ingest(eth);
    expect(e.closed).toBeNull();
    expect(e.open.symbol).toBe('ETH');
    expect(r.getOpen('hyperliquid', 'BTC')?.c).toBe(100);
    expect(r.getOpen('hyperliquid', 'ETH')?.c).toBe(3000);
  });

  it('flush() finalizes bars older than now', () => {
    const r = new BarRollup('1m');
    r.ingest(t(60_000, 100));
    expect(r.flush(120_001)).toHaveLength(1);
    expect(r.getOpen('hyperliquid', 'BTC')).toBeUndefined();
  });
});
