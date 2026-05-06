import type { Storage } from '@perps/storage';
import type { EventImpactResult, EventImpactRow } from './types.js';

const DEFAULT_OFFSETS = [-15, -5, -1, 0, 1, 5, 15, 60, 240, 360];

/**
 * For every macro event whose title matches `titleLike` (substring,
 * case-insensitive), compute the % return of `(venue, symbol)` from the
 * event's bar to event+offset for each offset in `offsetsMin`. Aggregate
 * mean / median / std across events.
 *
 * Bars are pulled from the existing 1m table — no new table required.
 *
 * The "median" here uses simple sort + middle index; with N events
 * usually 5-50, that's fine. Empty-bar offsets are skipped (e.g. before
 * we had data for that symbol).
 */
export async function computeEventImpact(opts: {
  storage: Storage;
  venue: string;
  symbol: string;
  titleLike: string;
  /** restrict to events at or after this ts (inclusive); default -90 days */
  fromTs?: number;
  /** restrict to events at or before this ts; default Date.now() */
  toTs?: number;
  /** restrict to these impact tiers; default ['High','Medium'] */
  impacts?: Array<'Holiday' | 'Low' | 'Medium' | 'High'>;
  offsetsMin?: number[];
}): Promise<EventImpactResult> {
  const offsets = opts.offsetsMin ?? DEFAULT_OFFSETS;
  const toTs = opts.toTs ?? Date.now();
  const fromTs = opts.fromTs ?? toTs - 90 * 24 * 60 * 60_000;
  const impacts = opts.impacts ?? ['High', 'Medium'];

  // Query the macro_events table for matching events. We query through the
  // storage layer so the caller doesn't need raw SQL access.
  const events = await opts.storage.findMacroEventsByTitle(
    opts.titleLike,
    fromTs,
    toTs,
    impacts,
  );

  if (events.length === 0) {
    return {
      title: opts.titleLike,
      venue: opts.venue,
      symbol: opts.symbol,
      events: 0,
      rows: offsets.map((o) => ({
        offsetMin: o,
        n: 0,
        meanRet: 0,
        medianRet: 0,
        stdRet: 0,
      })),
    };
  }

  // For each event, find the bar at event time and compare to offset bars.
  const minOff = Math.min(...offsets);
  const maxOff = Math.max(...offsets);
  const buckets = new Map<number, number[]>();
  for (const o of offsets) buckets.set(o, []);

  for (const ev of events) {
    if (ev.ts === null) continue;
    const startTs = ev.ts + minOff * 60_000 - 60_000;
    const endTs = ev.ts + maxOff * 60_000 + 60_000;
    const bars = await opts.storage.getCandlesInRange(
      opts.venue,
      opts.symbol,
      startTs,
      endTs,
      10_000,
    );
    if (bars.length === 0) continue;
    // Find the bar containing the event time.
    const eventBucket = Math.floor(ev.ts / 60_000) * 60_000;
    const baseBar = bars.find((b) => b.ts === eventBucket);
    if (!baseBar || baseBar.c <= 0) continue;
    const base = baseBar.c;
    for (const o of offsets) {
      const targetTs = eventBucket + o * 60_000;
      const tgt = bars.find((b) => b.ts === targetTs);
      if (!tgt) continue;
      const ret = tgt.c / base - 1;
      buckets.get(o)!.push(ret);
    }
  }

  const rows: EventImpactRow[] = offsets.map((o) => {
    const arr = buckets.get(o)!;
    if (arr.length === 0) {
      return { offsetMin: o, n: 0, meanRet: 0, medianRet: 0, stdRet: 0 };
    }
    const mean = arr.reduce((s, x) => s + x, 0) / arr.length;
    const variance =
      arr.length > 1
        ? arr.reduce((s, x) => s + (x - mean) ** 2, 0) / (arr.length - 1)
        : 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median =
      sorted.length % 2 === 0
        ? (sorted[mid - 1]! + sorted[mid]!) / 2
        : sorted[mid]!;
    return {
      offsetMin: o,
      n: arr.length,
      meanRet: mean,
      medianRet: median,
      stdRet: Math.sqrt(variance),
    };
  });

  return {
    title: opts.titleLike,
    venue: opts.venue,
    symbol: opts.symbol,
    events: events.length,
    rows,
  };
}
