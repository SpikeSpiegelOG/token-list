import type { Bar, Side } from '@perps/core';
import type { Storage } from '@perps/storage';
import type { PaperConfig, PaperRunStatus } from './types.js';

const DEFAULT_TAKER_FEE = 0.0004;
const DEFAULT_HALF_SPREAD = 0.0002;

/**
 * Paper trader. Subscribes to closed bars from the rollup and runs a
 * strategy through the same StrategyContext shape the backtester uses, so a
 * strategy that worked in backtest needs zero changes to run live.
 *
 * Slippage / fee model is the same simple one as the backtest engine — fills
 * happen at the bar's close ± half-spread with a flat taker fee. No funding
 * payments, no margin model, no real orders.
 *
 * Persistence is best-effort and idempotent on (run_id, ts):
 *   - paper_runs:    one row per (runId, venue, symbol, strategy)
 *   - paper_equity:  one row per closed bar (equity, position)
 *   - paper_fills:   one row per fill
 *
 * State (cash, position, avg_entry) is reconstructed from the equity curve
 * + fills on restart, so a server restart resumes the run.
 */
export class PaperEngine {
  private cash: number;
  private position = 0;
  private avgEntry = 0;
  private history: Bar[] = [];
  private fills = 0;
  private bars = 0;
  private startedAt: number;
  private lastBarTs: number | null = null;
  private readonly cfg: PaperConfig;
  private readonly storage: Storage;
  private readonly takerFee: number;
  private readonly halfSpread: number;

  constructor(opts: { cfg: PaperConfig; storage: Storage }) {
    this.cfg = opts.cfg;
    this.storage = opts.storage;
    this.cash = opts.cfg.initialCash;
    this.startedAt = Date.now();
    this.takerFee = opts.cfg.takerFee ?? DEFAULT_TAKER_FEE;
    this.halfSpread = opts.cfg.halfSpread ?? DEFAULT_HALF_SPREAD;
  }

  async start(): Promise<void> {
    this.cfg.strategy.init?.();
    await this.storage.upsertPaperRun({
      runId: this.cfg.runId,
      venue: this.cfg.venue,
      symbol: this.cfg.symbol,
      strategyId: this.cfg.strategyId,
      strategyParams: JSON.stringify(this.cfg.strategyParams ?? {}),
      initialCash: this.cfg.initialCash,
      startedAt: this.startedAt,
    });

    // Re-hydrate state from history if a previous server run wrote bars
    // for this runId. Cheap because each run accumulates one row per
    // closed bar; even a week of 1m bars = ~10K rows.
    const hist = await this.storage.getPaperEquity(this.cfg.runId, 1);
    if (hist.length > 0) {
      const last = hist[0]!;
      this.cash =
        last.equity -
        (last.position !== 0 ? (last.lastClose - last.avgEntry) * last.position : 0);
      this.position = last.position;
      this.avgEntry = last.avgEntry;
      this.bars = last.barsSeen;
      this.fills = last.fillsSeen;
      console.log(
        `[paper:${this.cfg.runId}] resumed @ equity=${last.equity.toFixed(2)} pos=${last.position}`,
      );
    }
  }

  /**
   * Called by the bar rollup when a 1m bar closes for our (venue, symbol).
   */
  async onClosedBar(bar: Bar): Promise<void> {
    if (bar.venue !== this.cfg.venue || bar.symbol !== this.cfg.symbol) return;
    this.history.push(bar);
    this.bars += 1;
    this.lastBarTs = bar.ts;

    const equityBefore =
      this.cash +
      (this.position !== 0
        ? (bar.c - this.avgEntry) * this.position
        : 0);

    const action = this.cfg.strategy.onBar(bar, {
      history: this.history,
      position: this.position,
      avgEntry: this.avgEntry,
      equity: equityBefore,
      ts: bar.ts,
    });

    let filled: { side: Side; price: number; size: number; fee: number; reason: string } | null = null;

    if (action.type !== 'hold') {
      const desired = (() => {
        if (action.type === 'long') return action.size ?? this.cfg.defaultSize;
        if (action.type === 'short') return -(action.size ?? this.cfg.defaultSize);
        return 0;
      })();
      if (desired !== this.position) {
        filled = this.applyFill(bar, desired, action.reason);
      }
    }

    const equityAfter =
      this.cash +
      (this.position !== 0
        ? (bar.c - this.avgEntry) * this.position
        : 0);

    if (filled) {
      await this.storage.insertPaperFill({
        runId: this.cfg.runId,
        ts: bar.ts,
        side: filled.side,
        price: filled.price,
        size: filled.size,
        fee: filled.fee,
        reason: filled.reason,
      });
      this.fills += 1;
    }

    await this.storage.insertPaperEquity({
      runId: this.cfg.runId,
      ts: bar.ts,
      equity: equityAfter,
      position: this.position,
      avgEntry: this.avgEntry,
      lastClose: bar.c,
      barsSeen: this.bars,
      fillsSeen: this.fills,
    });
  }

  status(): PaperRunStatus {
    const lastBar = this.history[this.history.length - 1];
    const equity =
      this.cash +
      (this.position !== 0 && lastBar
        ? (lastBar.c - this.avgEntry) * this.position
        : 0);
    return {
      runId: this.cfg.runId,
      venue: this.cfg.venue,
      symbol: this.cfg.symbol,
      strategy: this.cfg.strategy.name,
      strategyId: this.cfg.strategyId,
      startedAt: this.startedAt,
      lastBarTs: this.lastBarTs,
      equity,
      initialCash: this.cfg.initialCash,
      position: this.position,
      avgEntry: this.avgEntry,
      bars: this.bars,
      fills: this.fills,
    };
  }

  private applyFill(
    bar: Bar,
    desired: number,
    reason?: string,
  ): { side: Side; price: number; size: number; fee: number; reason: string } {
    const sizeDelta = desired - this.position;
    const side: Side = sizeDelta > 0 ? 'buy' : 'sell';
    const fillPrice =
      side === 'buy'
        ? bar.c * (1 + this.halfSpread)
        : bar.c * (1 - this.halfSpread);
    const tradedAbs = Math.abs(sizeDelta);
    const fee = tradedAbs * fillPrice * this.takerFee;

    const closing =
      this.position !== 0 && Math.sign(desired) !== Math.sign(this.position);
    if (closing) {
      const closeSize = Math.min(Math.abs(this.position), tradedAbs);
      const grossPnl =
        this.position > 0
          ? (fillPrice - this.avgEntry) * closeSize
          : (this.avgEntry - fillPrice) * closeSize;
      this.cash += grossPnl - fee;

      const remainder = tradedAbs - closeSize;
      if (remainder > 0) {
        this.position = Math.sign(sizeDelta) * remainder;
        this.avgEntry = fillPrice;
      } else {
        this.position = 0;
        this.avgEntry = 0;
      }
    } else if (this.position === 0) {
      this.position = desired;
      this.avgEntry = fillPrice;
      this.cash -= fee;
    } else {
      // scaling same direction
      const newAbs = Math.abs(this.position) + tradedAbs;
      this.avgEntry =
        (this.avgEntry * Math.abs(this.position) + fillPrice * tradedAbs) /
        newAbs;
      this.position = desired;
      this.cash -= fee;
    }

    return {
      side,
      price: fillPrice,
      size: tradedAbs,
      fee,
      reason: reason ?? 'signal',
    };
  }
}
