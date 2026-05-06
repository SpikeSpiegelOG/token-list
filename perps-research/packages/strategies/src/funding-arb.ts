import type { Bar } from '@perps/core';
import type { Strategy, StrategyAction } from '@perps/backtest';

export interface FundingArbParams {
  /** absolute funding rate above which to enter a counter-position */
  threshold?: number;
  /** how many bars to hold (or until rate decays through 0) */
  holdBars?: number;
}

const DEFAULTS: Required<FundingArbParams> = {
  threshold: 0.0001, // 1 bp per funding interval
  holdBars: 60,
};

/**
 * Single-leg funding placeholder for the backtester.
 *
 * The actual funding-arb edge requires:
 *   1) a basis trade (long the cheaper-funded venue, short the dearer),
 *   2) a feed of historical funding rates (planned: replay the persisted
 *      `funding` table aligned to each bar), and
 *   3) careful capacity / margin / rebalancing modeling.
 *
 * Until those land, this is a *signal-only* version: when funding > +threshold
 * (longs paying shorts), short the perp; when funding < -threshold, long it.
 * It expects funding context to be threaded in via Strategy state — for now
 * we proxy with a simple price-momentum sign (close vs N-bar EMA): when
 * price has run hard, persistent positive funding is a strong prior.
 *
 * This strategy will be replaced wholesale in Phase 3.5 when the engine
 * accepts a Funding stream alongside Bars.
 */
export function fundingArb(params: FundingArbParams = {}): Strategy {
  const p: Required<FundingArbParams> = { ...DEFAULTS, ...params };
  const period = 96; // ~96m EMA, matches the 1m bar default
  const k = 2 / (period + 1);
  let ema = 0;
  let primed = false;
  let barsInTrade = 0;

  return {
    name: `funding-arb-proxy(thr=${p.threshold})`,
    init() {
      ema = 0;
      primed = false;
      barsInTrade = 0;
    },
    onBar(bar: Bar, ctx): StrategyAction {
      if (!primed) {
        ema = bar.c;
        primed = true;
        return { type: 'hold' };
      }
      ema = bar.c * k + ema * (1 - k);

      // Proxy "funding-like" sign: how far price has run vs. its trailing EMA
      // relative to the current price level. Positive → market is overheated
      // → expect positive funding → short bias. Symmetric the other way.
      const stretch = (bar.c - ema) / bar.c;

      if (ctx.position !== 0) {
        barsInTrade += 1;
        // Exit when stretch returns through zero or hold expires.
        if (
          barsInTrade >= p.holdBars ||
          Math.sign(stretch) !== Math.sign(ctx.position) * -1
        ) {
          barsInTrade = 0;
          return { type: 'flat', reason: 'mean_reversion' };
        }
        return { type: 'hold' };
      }

      if (stretch > p.threshold) {
        barsInTrade = 0;
        return { type: 'short', reason: 'overstretched_up' };
      }
      if (stretch < -p.threshold) {
        barsInTrade = 0;
        return { type: 'long', reason: 'overstretched_down' };
      }
      return { type: 'hold' };
    },
  };
}
