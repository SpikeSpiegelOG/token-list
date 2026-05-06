import type { SlippageModel } from './types.js';

/**
 * Naive slippage: fill at the bar close + half-spread in the unfavorable
 * direction, charge taker fee on notional. Doesn't model size impact (a
 * trade larger than the bar's volume effectively eats book depth) — that
 * is Phase 4 work when the backtester sees order-book snapshots.
 */
export function simpleSlippage({
  takerFee = 0.0004,
  halfSpread = 0.0002,
}: { takerFee?: number; halfSpread?: number } = {}): SlippageModel {
  return {
    fill({ side, bar, intendedSize }) {
      const slip = bar.c * halfSpread;
      const price = side === 'buy' ? bar.c + slip : bar.c - slip;
      const fee = Math.abs(intendedSize) * price * takerFee;
      return { price, fee };
    },
  };
}
