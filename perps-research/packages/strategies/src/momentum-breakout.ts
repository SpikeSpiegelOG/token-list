import type { Bar } from '@perps/core';
import type { Strategy, StrategyAction } from '@perps/backtest';

export interface MomentumBreakoutParams {
  /** lookback window for the breakout high/low (in bars) */
  lookback?: number;
  /** ATR window used to gate entries; 0 disables the filter */
  atrPeriod?: number;
  /** require ATR > minVolPct of close to enter (regime filter) */
  minVolPct?: number;
  /** exit when close pulls back through this many ATRs against the trade */
  stopAtr?: number;
}

const DEFAULTS: Required<MomentumBreakoutParams> = {
  lookback: 30,
  atrPeriod: 14,
  minVolPct: 0.0008,
  stopAtr: 1.5,
};

/**
 * N-bar high/low breakout with an ATR-based regime filter and trailing stop.
 *
 * Long  if close > max(high) over lookback AND ATR/close > minVolPct.
 * Short if close < min(low)  over lookback AND ATR/close > minVolPct.
 * Exit when close pulls back stopAtr*ATR against the open position.
 *
 * The vol-gate is the difference between "this works in trending tape" and
 * "this is a coin-flip with fees on top". Tune lookback/stopAtr per market.
 */
export function momentumBreakout(params: MomentumBreakoutParams = {}): Strategy {
  const p: Required<MomentumBreakoutParams> = { ...DEFAULTS, ...params };
  let trMA = 0; // simple moving average ATR (Wilder isn't necessary for v1)
  let entryPrice = 0;
  let stopPrice = 0;
  let stopSide: 'long' | 'short' | null = null;

  const reset = () => {
    trMA = 0;
    entryPrice = 0;
    stopPrice = 0;
    stopSide = null;
  };

  return {
    name: `momentum-breakout(${p.lookback},${p.atrPeriod})`,
    init: reset,
    onBar(bar: Bar, ctx): StrategyAction {
      const hist = ctx.history;
      const idx = hist.length - 1;

      // Update simple ATR estimate (true range MA over atrPeriod).
      if (p.atrPeriod > 0 && idx > 0) {
        const prev = hist[idx - 1]!;
        const tr = Math.max(
          bar.h - bar.l,
          Math.abs(bar.h - prev.c),
          Math.abs(bar.l - prev.c),
        );
        if (idx <= p.atrPeriod) {
          // Cumulative seed
          trMA = (trMA * (idx - 1) + tr) / idx;
        } else {
          trMA = trMA + (tr - trMA) / p.atrPeriod;
        }
      }

      // Need at least lookback bars of history for a breakout signal.
      if (idx < p.lookback) return { type: 'hold' };

      // Stop-loss check first — exits override new entries.
      if (ctx.position !== 0 && stopSide && stopPrice > 0) {
        if (
          (stopSide === 'long' && bar.c <= stopPrice) ||
          (stopSide === 'short' && bar.c >= stopPrice)
        ) {
          reset();
          return { type: 'flat', reason: 'stop' };
        }
      }

      const window = hist.slice(idx - p.lookback, idx); // exclude current bar
      let hi = -Infinity;
      let lo = Infinity;
      for (const w of window) {
        if (w.h > hi) hi = w.h;
        if (w.l < lo) lo = w.l;
      }

      const atrPct = bar.c > 0 ? trMA / bar.c : 0;
      const volOk = p.minVolPct === 0 || atrPct >= p.minVolPct;

      if (ctx.position === 0 && volOk) {
        if (bar.c > hi) {
          entryPrice = bar.c;
          stopPrice = bar.c - p.stopAtr * trMA;
          stopSide = 'long';
          return { type: 'long', reason: 'breakout_high' };
        }
        if (bar.c < lo) {
          entryPrice = bar.c;
          stopPrice = bar.c + p.stopAtr * trMA;
          stopSide = 'short';
          return { type: 'short', reason: 'breakout_low' };
        }
      }

      // Trailing stop: ratchet in the trade's favor.
      if (ctx.position > 0 && stopSide === 'long') {
        const newStop = bar.c - p.stopAtr * trMA;
        if (newStop > stopPrice) stopPrice = newStop;
      } else if (ctx.position < 0 && stopSide === 'short') {
        const newStop = bar.c + p.stopAtr * trMA;
        if (newStop < stopPrice || stopPrice === 0) stopPrice = newStop;
      }

      return { type: 'hold' };
    },
  };
}
