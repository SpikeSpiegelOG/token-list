import type { Strategy } from '@perps/backtest';
import { fundingArb } from './funding-arb.js';
import { liqSweepFade } from './liq-sweep-fade.js';
import { momentumBreakout } from './momentum-breakout.js';

export type StrategyParams = Record<string, number>;

export interface StrategyParamSpec {
  name: string;
  default: number;
  min?: number;
  max?: number;
}

export interface StrategyMeta {
  id: string;
  label: string;
  params: StrategyParamSpec[];
}

interface Entry extends StrategyMeta {
  build(params: StrategyParams): Strategy;
}

const REGISTRY: Entry[] = [
  {
    id: 'momentum-breakout',
    label: 'Momentum Breakout (N-bar high/low + ATR gate)',
    params: [
      { name: 'lookback', default: 30, min: 5, max: 500 },
      { name: 'atrPeriod', default: 14, min: 1, max: 200 },
      { name: 'minVolPct', default: 0.0008, min: 0, max: 0.05 },
      { name: 'stopAtr', default: 1.5, min: 0.1, max: 10 },
    ],
    build(p) {
      return momentumBreakout(p);
    },
  },
  {
    id: 'liq-sweep-fade',
    label: 'Liq-Sweep Fade (range-based proxy)',
    params: [
      { name: 'sweepAtr', default: 2.5, min: 0.5, max: 10 },
      { name: 'atrPeriod', default: 30, min: 1, max: 500 },
      { name: 'holdBars', default: 5, min: 1, max: 200 },
    ],
    build(p) {
      return liqSweepFade(p);
    },
  },
  {
    id: 'funding-arb',
    label: 'Funding-Arb Proxy (price stretch vs EMA)',
    params: [
      { name: 'threshold', default: 0.0008, min: 0, max: 0.05 },
      { name: 'holdBars', default: 60, min: 1, max: 1000 },
    ],
    build(p) {
      return fundingArb(p);
    },
  },
];

export function listStrategies(): StrategyMeta[] {
  return REGISTRY.map(({ build: _build, ...rest }) => rest);
}

export function buildStrategy(id: string, params: StrategyParams = {}): Strategy {
  const entry = REGISTRY.find((e) => e.id === id);
  if (!entry) throw new Error(`Unknown strategy: ${id}`);
  return entry.build(params);
}
