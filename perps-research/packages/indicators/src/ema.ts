/**
 * Exponential moving average. Seeded with the first value rather than a
 * simple moving average over the first `period` samples — this matches
 * TradingView's `ema()` behavior on Lightweight Charts overlays.
 */
export function emaSeries(values: readonly number[], period: number): number[] {
  if (period <= 0 || !Number.isFinite(period)) {
    throw new Error(`emaSeries: invalid period ${period}`);
  }
  const out: number[] = new Array(values.length);
  if (values.length === 0) return out;
  const k = 2 / (period + 1);
  let prev = values[0]!;
  out[0] = prev;
  for (let i = 1; i < values.length; i++) {
    const v = values[i]!;
    const next = v * k + prev * (1 - k);
    out[i] = next;
    prev = next;
  }
  return out;
}

/**
 * Streaming variant — call `update(price)` for each new value, get the
 * current EMA back. Mirrors the indicator state used by strategies in the
 * backtest engine, so the same code path runs in live + replay.
 */
export class ema {
  private readonly k: number;
  private current: number | null = null;

  constructor(public readonly period: number) {
    if (period <= 0 || !Number.isFinite(period)) {
      throw new Error(`ema: invalid period ${period}`);
    }
    this.k = 2 / (period + 1);
  }

  update(value: number): number {
    if (this.current === null) {
      this.current = value;
    } else {
      this.current = value * this.k + this.current * (1 - this.k);
    }
    return this.current;
  }

  get(): number | null {
    return this.current;
  }

  reset(): void {
    this.current = null;
  }
}
