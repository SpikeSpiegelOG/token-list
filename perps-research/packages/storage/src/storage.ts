import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import {
  DuckDBInstance,
  type DuckDBConnection,
  type DuckDBValue,
} from '@duckdb/node-api';
import type { Bar, Tick, Timeframe } from '@perps/core';

export interface CandleRow {
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS ticks (
  venue   VARCHAR NOT NULL,
  symbol  VARCHAR NOT NULL,
  ts      BIGINT  NOT NULL,
  price   DOUBLE  NOT NULL,
  size    DOUBLE  NOT NULL,
  side    VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_vst ON ticks(venue, symbol, ts);

CREATE TABLE IF NOT EXISTS bars_1m (
  venue   VARCHAR NOT NULL,
  symbol  VARCHAR NOT NULL,
  ts      BIGINT  NOT NULL,
  o       DOUBLE  NOT NULL,
  h       DOUBLE  NOT NULL,
  l       DOUBLE  NOT NULL,
  c       DOUBLE  NOT NULL,
  v       DOUBLE  NOT NULL,
  PRIMARY KEY (venue, symbol, ts)
);
`;

/**
 * Thin DuckDB wrapper. Owns one connection. Buffers tick writes so a busy
 * stream doesn't pay round-trip cost per row, and so the WS event loop never
 * blocks on disk I/O.
 */
export class Storage {
  private instance: DuckDBInstance | null = null;
  private conn: DuckDBConnection | null = null;
  private tickBuf: Tick[] = [];
  private barBuf: Bar[] = [];
  private flushTimer: NodeJS.Timeout | null = null;
  private readonly path: string;
  private readonly flushIntervalMs: number;
  private readonly readOnly: boolean;

  constructor(opts: { path: string; flushIntervalMs?: number; readOnly?: boolean }) {
    this.path = resolve(opts.path);
    this.flushIntervalMs = opts.flushIntervalMs ?? 2_000;
    this.readOnly = opts.readOnly ?? false;
  }

  async open(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    // DuckDB allows one writer process + many read-only processes against
    // the same file. The web app passes readOnly:true; ingest is the writer.
    const config = this.readOnly ? { access_mode: 'READ_ONLY' } : undefined;
    this.instance = await DuckDBInstance.create(this.path, config);
    this.conn = await this.instance.connect();
    if (!this.readOnly) {
      await this.conn.run(SCHEMA_SQL);
    }
    if (!this.readOnly) {
      this.flushTimer = setInterval(() => {
        void this.flush().catch((err) =>
          console.error('[storage] flush failed', err),
        );
      }, this.flushIntervalMs);
      if (this.flushTimer.unref) this.flushTimer.unref();
    }
  }

  async close(): Promise<void> {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();
    this.conn?.disconnectSync();
    this.conn = null;
    this.instance = null;
  }

  enqueueTick(tick: Tick): void {
    this.tickBuf.push(tick);
  }

  enqueueBar(bar: Bar): void {
    this.barBuf.push(bar);
  }

  /** Read closed 1m bars for a (venue, symbol). Most-recent `limit` rows. */
  async getCandles(
    venue: string,
    symbol: string,
    limit = 500,
  ): Promise<CandleRow[]> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT ts, o, h, l, c, v
       FROM bars_1m
       WHERE venue = ? AND symbol = ?
       ORDER BY ts DESC
       LIMIT ?`,
      [venue, symbol, limit],
    );
    const rows = reader.getRowObjects() as Array<Record<string, unknown>>;
    // newest-first → reverse for chart
    return rows
      .map((r) => ({
        ts: Number(r.ts),
        o: Number(r.o),
        h: Number(r.h),
        l: Number(r.l),
        c: Number(r.c),
        v: Number(r.v),
      }))
      .reverse();
  }

  async tickCount(): Promise<number> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll('SELECT count(*) AS n FROM ticks');
    const rows = reader.getRowObjects() as Array<{ n: bigint | number }>;
    return Number(rows[0]?.n ?? 0);
  }

  /**
   * Open an additional connection for streaming reads (SSE poller). DuckDB
   * supports many concurrent reader connections against a single writer.
   */
  async openReadConnection(): Promise<DuckDBConnection> {
    if (!this.instance) throw new Error('Storage not open');
    return this.instance.connect();
  }

  private async flush(): Promise<void> {
    if (!this.conn) return;
    if (this.tickBuf.length === 0 && this.barBuf.length === 0) return;

    const ticks = this.tickBuf;
    const bars = this.barBuf;
    this.tickBuf = [];
    this.barBuf = [];

    if (ticks.length > 0) {
      await this.insertTicks(ticks);
    }
    if (bars.length > 0) {
      await this.upsertBars(bars);
    }
  }

  private async insertTicks(ticks: Tick[]): Promise<void> {
    const conn = this.requireConn();
    // Single multi-row INSERT — fast enough for Phase 1 throughput.
    // Note: pass `ts` as bigint; DuckDB binds JS numbers as INT32, which
    // would truncate millisecond timestamps.
    const placeholders = ticks.map(() => '(?,?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const t of ticks) {
      params.push(t.venue, t.symbol, BigInt(t.ts), t.price, t.size, t.side);
    }
    await conn.run(
      `INSERT INTO ticks (venue, symbol, ts, price, size, side) VALUES ${placeholders}`,
      params,
    );
  }

  private async upsertBars(bars: Bar[]): Promise<void> {
    const conn = this.requireConn();
    // Use ON CONFLICT to handle the "open bar republished as it grows" case.
    // We only persist 1m bars in Phase 1; other timeframes are derived on read.
    const oneMin = bars.filter((b): b is Bar & { tf: Timeframe } => b.tf === '1m');
    if (oneMin.length === 0) return;
    const placeholders = oneMin.map(() => '(?,?,?,?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const b of oneMin) {
      params.push(b.venue, b.symbol, BigInt(b.ts), b.o, b.h, b.l, b.c, b.v);
    }
    await conn.run(
      `INSERT INTO bars_1m (venue, symbol, ts, o, h, l, c, v) VALUES ${placeholders}
       ON CONFLICT (venue, symbol, ts) DO UPDATE SET
         h = GREATEST(bars_1m.h, excluded.h),
         l = LEAST(bars_1m.l, excluded.l),
         c = excluded.c,
         v = excluded.v`,
      params,
    );
  }

  private requireConn(): DuckDBConnection {
    if (!this.conn) throw new Error('Storage not open');
    return this.conn;
  }
}
