import type { Bar } from '@perps/core';
import type { Strategy, StrategyAction } from '@perps/backtest';

export interface LiqSweepFadeParams {
  /** how many ATR-multiples of one-bar range qualifies as a "sweep" */
  sweepAtr?: number;
  /** ATR window */
  atrPeriod?: number;
  /** how many bars to hold the fade */
  holdBars?: number;
}

const DEFAULTS: Required<LiqSweepFadeParams> = {
  sweepAtr: 2.5,
  atrPeriod: 30,
  holdBars: 5,
};

/**
 * Mean-reversion fade triggered by an outsized one-bar move (proxy for a
 * liquidation cascade). Without an actual liquidation tape in the
 * backtester, we infer "sweep" from bar range > sweepAtr * ATR. Phase 4
 * upgrades this to consume the persisted `liquidations` table and trigger
 * on real cascades, which is a stronger signal.
 *
 * Long if a strong DOWN bar prints (close < open by a sweep margin).
 * Short if a strong UP bar prints.
 * Exit after holdBars bars regardless.
 */
export function liqSweepFade(params: LiqSweepFadeParams = {}): Strategy {
  const p: Required<LiqSweepFadeParams> = { ...DEFAULTS, ...params };
  let trMA = 0;
  let barsInTrade = 0;

  return {
    name: `liq-sweep-fade(${p.sweepAtr},${p.holdBars})`,
    init() {
      trMA = 0;
      barsInTrade = 0;
    },
    onBar(bar: Bar, ctx): StrategyAction {
      const hist = ctx.history;
      const idx = hist.length - 1;
      if (idx > 0) {
        const prev = hist[idx - 1]!;
        const tr = Math.max(
          bar.h - bar.l,
          Math.abs(bar.h - prev.c),
          Math.abs(bar.l - prev.c),
        );
        if (idx <= p.atrPeriod) {
          trMA = (trMA * (idx - 1) + tr) / idx;
        } else {
          trMA = trMA + (tr - trMA) / p.atrPeriod;
        }
      }

      if (idx < p.atrPeriod) return { type: 'hold' };

      if (ctx.position !== 0) {
        barsInTrade += 1;
        if (barsInTrade >= p.holdBars) {
          barsInTrade = 0;
          return { type: 'flat', reason: 'time_exit' };
        }
        return { type: 'hold' };
      }

      const move = bar.c - bar.o;
      const threshold = p.sweepAtr * trMA;
      if (Math.abs(move) < threshold) return { type: 'hold' };

      barsInTrade = 0;
      if (move < 0) {
        return { type: 'long', reason: 'sweep_down' };
      }
      return { type: 'short', reason: 'sweep_up' };
    },
  };
}
