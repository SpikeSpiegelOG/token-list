import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import {
  DuckDBInstance,
  type DuckDBConnection,
  type DuckDBValue,
} from '@duckdb/node-api';
import type { Bar, Funding, Liquidation, OpenInterest, Tick, Timeframe } from '@perps/core';

export interface CandleRow {
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface FundingRow {
  venue: string;
  symbol: string;
  ts: number;
  rate: number;
  nextTs: number;
}

export interface OpenInterestRow {
  venue: string;
  symbol: string;
  ts: number;
  oi: number;
}

export interface LiquidationRow {
  venue: string;
  symbol: string;
  ts: number;
  side: 'long' | 'short';
  size: number;
  price: number;
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

CREATE TABLE IF NOT EXISTS funding (
  venue    VARCHAR NOT NULL,
  symbol   VARCHAR NOT NULL,
  ts       BIGINT  NOT NULL,
  rate     DOUBLE  NOT NULL,
  next_ts  BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_funding_vst ON funding(venue, symbol, ts);

CREATE TABLE IF NOT EXISTS open_interest (
  venue    VARCHAR NOT NULL,
  symbol   VARCHAR NOT NULL,
  ts       BIGINT  NOT NULL,
  oi       DOUBLE  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oi_vst ON open_interest(venue, symbol, ts);

CREATE TABLE IF NOT EXISTS liquidations (
  venue    VARCHAR NOT NULL,
  symbol   VARCHAR NOT NULL,
  ts       BIGINT  NOT NULL,
  side     VARCHAR NOT NULL,
  size     DOUBLE  NOT NULL,
  price    DOUBLE  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_liq_vst ON liquidations(venue, symbol, ts);

CREATE TABLE IF NOT EXISTS macro_events (
  id          VARCHAR PRIMARY KEY,
  title       VARCHAR NOT NULL,
  country     VARCHAR NOT NULL,
  ts          BIGINT,
  impact      VARCHAR NOT NULL,
  forecast    VARCHAR,
  previous    VARCHAR,
  actual      VARCHAR,
  url         VARCHAR,
  fetched_at  BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_macro_ts ON macro_events(ts);
CREATE INDEX IF NOT EXISTS idx_macro_title ON macro_events(title);

CREATE TABLE IF NOT EXISTS news_items (
  id          VARCHAR PRIMARY KEY,
  source      VARCHAR NOT NULL,
  ts          BIGINT  NOT NULL,
  title       VARCHAR NOT NULL,
  url         VARCHAR NOT NULL,
  domain      VARCHAR,
  sentiment   VARCHAR,
  votes_pos   INTEGER NOT NULL DEFAULT 0,
  votes_neg   INTEGER NOT NULL DEFAULT 0,
  fetched_at  BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news_items(ts);
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
  private fundingBuf: Funding[] = [];
  private oiBuf: OpenInterest[] = [];
  private liqBuf: Liquidation[] = [];
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

  enqueueFunding(f: Funding): void {
    this.fundingBuf.push(f);
  }

  enqueueOpenInterest(oi: OpenInterest): void {
    this.oiBuf.push(oi);
  }

  enqueueLiquidation(l: Liquidation): void {
    this.liqBuf.push(l);
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

  /**
   * Bars within a closed time range, oldest first. Used by the backtester
   * to replay history without paginating.
   */
  async getCandlesInRange(
    venue: string,
    symbol: string,
    startMs: number,
    endMs: number,
    limit = 100_000,
  ): Promise<CandleRow[]> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT ts, o, h, l, c, v
       FROM bars_1m
       WHERE venue = ? AND symbol = ? AND ts >= ? AND ts <= ?
       ORDER BY ts ASC
       LIMIT ?`,
      [venue, symbol, BigInt(startMs), BigInt(endMs), limit],
    );
    const rows = reader.getRowObjects() as Array<Record<string, unknown>>;
    return rows.map((r) => ({
      ts: Number(r.ts),
      o: Number(r.o),
      h: Number(r.h),
      l: Number(r.l),
      c: Number(r.c),
      v: Number(r.v),
    }));
  }

  async tickCount(): Promise<number> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll('SELECT count(*) AS n FROM ticks');
    const rows = reader.getRowObjects() as Array<{ n: bigint | number }>;
    return Number(rows[0]?.n ?? 0);
  }

  /**
   * Latest funding rate per (venue, symbol). One row per pair, the most
   * recently observed rate. Used by /funding heatmap.
   */
  async getLatestFunding(): Promise<FundingRow[]> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT venue, symbol, ts, rate, next_ts
       FROM funding
       QUALIFY row_number() OVER (PARTITION BY venue, symbol ORDER BY ts DESC) = 1
       ORDER BY rate DESC`,
    );
    return (reader.getRowObjects() as Array<Record<string, unknown>>).map((r) => ({
      venue: String(r.venue),
      symbol: String(r.symbol),
      ts: Number(r.ts),
      rate: Number(r.rate),
      nextTs: Number(r.next_ts),
    }));
  }

  /**
   * Latest open interest per (venue, symbol).
   */
  async getLatestOpenInterest(): Promise<OpenInterestRow[]> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT venue, symbol, ts, oi
       FROM open_interest
       QUALIFY row_number() OVER (PARTITION BY venue, symbol ORDER BY ts DESC) = 1
       ORDER BY oi DESC`,
    );
    return (reader.getRowObjects() as Array<Record<string, unknown>>).map((r) => ({
      venue: String(r.venue),
      symbol: String(r.symbol),
      ts: Number(r.ts),
      oi: Number(r.oi),
    }));
  }

  /**
   * Upsert a batch of macro events. ID is stable from (title, country, ts)
   * so re-fetching the same week is idempotent.
   */
  async upsertMacroEvents(
    rows: Array<{
      id: string;
      title: string;
      country: string;
      ts: number | null;
      impact: string;
      forecast: string | null;
      previous: string | null;
      actual: string | null;
      url: string | null;
      fetchedAt: number;
    }>,
  ): Promise<void> {
    if (rows.length === 0) return;
    const conn = this.requireConn();
    const placeholders = rows.map(() => '(?,?,?,?,?,?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const r of rows) {
      params.push(
        r.id,
        r.title,
        r.country,
        r.ts === null ? null : BigInt(r.ts),
        r.impact,
        r.forecast,
        r.previous,
        r.actual,
        r.url,
        BigInt(r.fetchedAt),
      );
    }
    await conn.run(
      `INSERT INTO macro_events
       (id, title, country, ts, impact, forecast, previous, actual, url, fetched_at)
       VALUES ${placeholders}
       ON CONFLICT (id) DO UPDATE SET
         forecast   = COALESCE(excluded.forecast, macro_events.forecast),
         previous   = COALESCE(excluded.previous, macro_events.previous),
         actual     = COALESCE(excluded.actual,   macro_events.actual),
         fetched_at = excluded.fetched_at`,
      params,
    );
  }

  async getMacroEvents(opts: {
    fromTs: number;
    toTs: number;
    impacts?: string[];
    limit?: number;
  }): Promise<
    Array<{
      id: string;
      title: string;
      country: string;
      ts: number | null;
      impact: string;
      forecast: string | null;
      previous: string | null;
      actual: string | null;
      url: string | null;
    }>
  > {
    const conn = this.requireConn();
    const limit = opts.limit ?? 500;
    const params: DuckDBValue[] = [BigInt(opts.fromTs), BigInt(opts.toTs)];
    let where = 'ts IS NOT NULL AND ts >= ? AND ts <= ?';
    if (opts.impacts && opts.impacts.length > 0) {
      where += ` AND impact IN (${opts.impacts.map(() => '?').join(',')})`;
      for (const i of opts.impacts) params.push(i);
    }
    params.push(limit);
    const reader = await conn.runAndReadAll(
      `SELECT id, title, country, ts, impact, forecast, previous, actual, url
       FROM macro_events
       WHERE ${where}
       ORDER BY ts ASC
       LIMIT ?`,
      params,
    );
    return (reader.getRowObjects() as Array<Record<string, unknown>>).map((r) => ({
      id: String(r.id),
      title: String(r.title),
      country: String(r.country),
      ts: r.ts === null || r.ts === undefined ? null : Number(r.ts),
      impact: String(r.impact),
      forecast: r.forecast == null ? null : String(r.forecast),
      previous: r.previous == null ? null : String(r.previous),
      actual: r.actual == null ? null : String(r.actual),
      url: r.url == null ? null : String(r.url),
    }));
  }

  async findMacroEventsByTitle(
    titleLike: string,
    fromTs: number,
    toTs: number,
    impacts: string[] = ['High', 'Medium'],
  ): Promise<Array<{ ts: number | null }>> {
    const conn = this.requireConn();
    const params: DuckDBValue[] = [
      `%${titleLike}%`,
      BigInt(fromTs),
      BigInt(toTs),
    ];
    let where = 'ts IS NOT NULL AND title ILIKE ? AND ts >= ? AND ts <= ?';
    if (impacts.length > 0) {
      where += ` AND impact IN (${impacts.map(() => '?').join(',')})`;
      for (const i of impacts) params.push(i);
    }
    const reader = await conn.runAndReadAll(
      `SELECT ts FROM macro_events WHERE ${where} ORDER BY ts ASC`,
      params,
    );
    return (reader.getRowObjects() as Array<{ ts: bigint | number | null }>)
      .map((r) => ({
        ts: r.ts === null || r.ts === undefined ? null : Number(r.ts),
      }));
  }

  async upsertNewsItems(
    rows: Array<{
      id: string;
      source: string;
      ts: number;
      title: string;
      url: string;
      domain: string | null;
      sentiment: string | null;
      votesPos: number;
      votesNeg: number;
      fetchedAt: number;
    }>,
  ): Promise<void> {
    if (rows.length === 0) return;
    const conn = this.requireConn();
    const placeholders = rows.map(() => '(?,?,?,?,?,?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const r of rows) {
      params.push(
        r.id,
        r.source,
        BigInt(r.ts),
        r.title,
        r.url,
        r.domain,
        r.sentiment,
        r.votesPos,
        r.votesNeg,
        BigInt(r.fetchedAt),
      );
    }
    await conn.run(
      `INSERT INTO news_items
       (id, source, ts, title, url, domain, sentiment, votes_pos, votes_neg, fetched_at)
       VALUES ${placeholders}
       ON CONFLICT (id) DO UPDATE SET
         votes_pos  = excluded.votes_pos,
         votes_neg  = excluded.votes_neg,
         sentiment  = COALESCE(excluded.sentiment, news_items.sentiment),
         fetched_at = excluded.fetched_at`,
      params,
    );
  }

  async getRecentNews(limit = 50): Promise<
    Array<{
      id: string;
      source: string;
      ts: number;
      title: string;
      url: string;
      domain: string | null;
      sentiment: string | null;
      votesPos: number;
      votesNeg: number;
    }>
  > {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT id, source, ts, title, url, domain, sentiment, votes_pos, votes_neg
       FROM news_items
       ORDER BY ts DESC
       LIMIT ?`,
      [limit],
    );
    return (reader.getRowObjects() as Array<Record<string, unknown>>).map((r) => ({
      id: String(r.id),
      source: String(r.source),
      ts: Number(r.ts),
      title: String(r.title),
      url: String(r.url),
      domain: r.domain == null ? null : String(r.domain),
      sentiment: r.sentiment == null ? null : String(r.sentiment),
      votesPos: Number(r.votes_pos ?? 0),
      votesNeg: Number(r.votes_neg ?? 0),
    }));
  }

  /**
   * Recent liquidations (cross-venue tape). Newest first, capped at `limit`.
   */
  async getRecentLiquidations(limit = 200): Promise<LiquidationRow[]> {
    const conn = this.requireConn();
    const reader = await conn.runAndReadAll(
      `SELECT venue, symbol, ts, side, size, price
       FROM liquidations
       ORDER BY ts DESC
       LIMIT ?`,
      [limit],
    );
    return (reader.getRowObjects() as Array<Record<string, unknown>>).map((r) => ({
      venue: String(r.venue),
      symbol: String(r.symbol),
      ts: Number(r.ts),
      side: r.side === 'long' ? 'long' : 'short',
      size: Number(r.size),
      price: Number(r.price),
    }));
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
    const total =
      this.tickBuf.length +
      this.barBuf.length +
      this.fundingBuf.length +
      this.oiBuf.length +
      this.liqBuf.length;
    if (total === 0) return;

    const ticks = this.tickBuf;
    const bars = this.barBuf;
    const funding = this.fundingBuf;
    const oi = this.oiBuf;
    const liqs = this.liqBuf;
    this.tickBuf = [];
    this.barBuf = [];
    this.fundingBuf = [];
    this.oiBuf = [];
    this.liqBuf = [];

    if (ticks.length > 0) await this.insertTicks(ticks);
    if (bars.length > 0) await this.upsertBars(bars);
    if (funding.length > 0) await this.insertFunding(funding);
    if (oi.length > 0) await this.insertOI(oi);
    if (liqs.length > 0) await this.insertLiquidations(liqs);
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

  private async insertFunding(rows: Funding[]): Promise<void> {
    const conn = this.requireConn();
    // Dedupe: only insert when (venue, symbol, ts) hasn't been seen.
    // Phase 2: we accept some duplication if upstream republishes; drop with
    // a window in queries instead of an EXISTS check per row.
    const placeholders = rows.map(() => '(?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const r of rows) {
      params.push(r.venue, r.symbol, BigInt(r.ts), r.rate, BigInt(r.nextTs));
    }
    await conn.run(
      `INSERT INTO funding (venue, symbol, ts, rate, next_ts) VALUES ${placeholders}`,
      params,
    );
  }

  private async insertOI(rows: OpenInterest[]): Promise<void> {
    const conn = this.requireConn();
    const placeholders = rows.map(() => '(?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const r of rows) {
      params.push(r.venue, r.symbol, BigInt(r.ts), r.oi);
    }
    await conn.run(
      `INSERT INTO open_interest (venue, symbol, ts, oi) VALUES ${placeholders}`,
      params,
    );
  }

  private async insertLiquidations(rows: Liquidation[]): Promise<void> {
    const conn = this.requireConn();
    const placeholders = rows.map(() => '(?,?,?,?,?,?)').join(',');
    const params: DuckDBValue[] = [];
    for (const r of rows) {
      params.push(r.venue, r.symbol, BigInt(r.ts), r.side, r.size, r.price);
    }
    await conn.run(
      `INSERT INTO liquidations (venue, symbol, ts, side, size, price) VALUES ${placeholders}`,
      params,
    );
  }

  private requireConn(): DuckDBConnection {
    if (!this.conn) throw new Error('Storage not open');
    return this.conn;
  }
}
