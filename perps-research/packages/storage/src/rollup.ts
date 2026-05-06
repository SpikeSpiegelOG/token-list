import type { Bar, Tick, Timeframe, Venue } from '@perps/core';

const TF_MS: Record<Timeframe, number> = {
  '1m': 60_000,
  '5m': 5 * 60_000,
  '15m': 15 * 60_000,
  '1h': 60 * 60_000,
  '4h': 4 * 60 * 60_000,
  '1d': 24 * 60 * 60_000,
};

interface OpenBar {
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type RollupKey = `${Venue}:${string}`;

/**
 * Aggregates ticks into time-bucketed bars in memory. When a tick arrives in
 * a new bucket, the previously-open bar is finalized and handed to `onClose`.
 *
 * Open (in-progress) bars are exposed via `getOpen` so the web app can render
 * a live, updating last candle without waiting for the bucket to close.
 */
export class BarRollup {
  private readonly bucketMs: number;
  private open = new Map<RollupKey, OpenBar>();
  private closeHandlers: Array<(b: Bar) => void> = [];

  constructor(public readonly tf: Timeframe) {
    this.bucketMs = TF_MS[tf];
  }

  onClose(handler: (b: Bar) => void): void {
    this.closeHandlers.push(handler);
  }

  ingest(tick: Tick): { closed: Bar | null; open: Bar } {
    const bucketTs = Math.floor(tick.ts / this.bucketMs) * this.bucketMs;
    const key: RollupKey = `${tick.venue}:${tick.symbol}`;
    let bar = this.open.get(key);
    let closed: Bar | null = null;

    if (!bar || bar.ts !== bucketTs) {
      if (bar) {
        closed = this.finalize(tick.venue, tick.symbol, bar);
      }
      bar = {
        ts: bucketTs,
        o: tick.price,
        h: tick.price,
        l: tick.price,
        c: tick.price,
        v: tick.size,
      };
      this.open.set(key, bar);
    } else {
      if (tick.price > bar.h) bar.h = tick.price;
      if (tick.price < bar.l) bar.l = tick.price;
      bar.c = tick.price;
      bar.v += tick.size;
    }

    return {
      closed,
      open: this.toBar(tick.venue, tick.symbol, bar),
    };
  }

  /** Force-close any open bars older than `nowMs` (used on shutdown). */
  flush(nowMs: number): Bar[] {
    const closed: Bar[] = [];
    for (const [key, bar] of this.open) {
      const [venue, symbol] = key.split(':') as [Venue, string];
      const cutoff = bar.ts + this.bucketMs;
      if (nowMs >= cutoff) {
        closed.push(this.finalize(venue, symbol, bar));
        this.open.delete(key);
      }
    }
    return closed;
  }

  getOpen(venue: Venue, symbol: string): Bar | undefined {
    const bar = this.open.get(`${venue}:${symbol}`);
    return bar ? this.toBar(venue, symbol, bar) : undefined;
  }

  private finalize(venue: Venue, symbol: string, bar: OpenBar): Bar {
    const final = this.toBar(venue, symbol, bar);
    for (const h of this.closeHandlers) {
      try {
        h(final);
      } catch (err) {
        console.error('[BarRollup] close handler threw', err);
      }
    }
    return final;
  }

  private toBar(venue: Venue, symbol: string, bar: OpenBar): Bar {
    return {
      venue,
      symbol,
      ts: bar.ts,
      o: bar.o,
      h: bar.h,
      l: bar.l,
      c: bar.c,
      v: bar.v,
      tf: this.tf,
    };
  }
}
