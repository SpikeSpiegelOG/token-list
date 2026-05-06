import type {
  Funding,
  Liquidation,
  OpenInterest,
  Tick,
  VenueAdapter,
} from '@perps/core';
import { binanceCoinToSymbol, binanceSymbolToCoin } from './symbols.js';

// Dynamic import keeps `ws` opaque to bundlers (see Hyperliquid adapter).
type WsModule = typeof import('ws');
type WsInstance = InstanceType<WsModule['WebSocket']>;
const wsPromise: Promise<WsModule> = (
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  new Function('return import("ws")') as () => Promise<WsModule>
)();

const DEFAULT_WS_BASE = 'wss://fstream.binance.com';
const DEFAULT_REST_BASE = 'https://fapi.binance.com';
const PING_INTERVAL_MS = 30_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const OI_POLL_INTERVAL_MS = 60_000;

interface BinAggTrade {
  e: 'aggTrade';
  E: number;
  s: string;
  p: string;
  q: string;
  T: number;
  m: boolean; // true = buyer is market maker → SELL aggressor
}

interface BinMarkPrice {
  e: 'markPriceUpdate';
  E: number;
  s: string;
  p: string; // mark price
  i: string; // index price
  P: string; // estimated settle
  r: string; // funding rate
  T: number; // next funding time (epoch ms)
}

interface BinForceOrder {
  e: 'forceOrder';
  E: number;
  o: {
    s: string;
    S: 'BUY' | 'SELL';
    q: string; // quantity
    p: string; // price
    ap: string; // average price
    T: number;
  };
}

type BinStreamPayload<T> = { stream: string; data: T };

/**
 * Binance USDⓈ-M Futures adapter.
 *
 * Subscribes per symbol to: aggTrade, markPrice@1s, forceOrder.
 * Polls REST `/fapi/v1/openInterest` once a minute for OI (no WS stream).
 *
 * Symbols passed in are canonical ("BTC"); the adapter maps to "BTCUSDT".
 * Emitted Tick/Funding/Liquidation/OpenInterest objects use the canonical
 * coin symbol so they line up with other venues.
 */
export class BinanceFuturesAdapter implements VenueAdapter {
  readonly venue = 'binance' as const;

  private ws: WsInstance | null = null;
  private symbols: readonly string[] = [];
  private tickHandlers: Array<(t: Tick) => void> = [];
  private fundingHandlers: Array<(f: Funding) => void> = [];
  private oiHandlers: Array<(o: OpenInterest) => void> = [];
  private liqHandlers: Array<(l: Liquidation) => void> = [];
  private pingTimer: NodeJS.Timeout | null = null;
  private oiTimer: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private stopped = false;
  private readonly wsBase: string;
  private readonly restBase: string;

  constructor(opts: { wsBase?: string; restBase?: string } = {}) {
    this.wsBase = opts.wsBase ?? DEFAULT_WS_BASE;
    this.restBase = opts.restBase ?? DEFAULT_REST_BASE;
  }

  onTick(handler: (t: Tick) => void): void {
    this.tickHandlers.push(handler);
  }

  onFunding(handler: (f: Funding) => void): void {
    this.fundingHandlers.push(handler);
  }

  onOpenInterest(handler: (o: OpenInterest) => void): void {
    this.oiHandlers.push(handler);
  }

  onLiquidation(handler: (l: Liquidation) => void): void {
    this.liqHandlers.push(handler);
  }

  async start(symbols: readonly string[]): Promise<void> {
    this.symbols = symbols;
    this.stopped = false;
    await this.connect();
    this.oiTimer = setInterval(() => {
      void this.pollOpenInterest().catch((err) =>
        console.error('[binance] oi poll failed', err),
      );
    }, OI_POLL_INTERVAL_MS);
    if (this.oiTimer.unref) this.oiTimer.unref();
    // Kick a first poll right away so the dashboard isn't empty for 60s.
    void this.pollOpenInterest().catch(() => {
      /* swallow first-attempt errors; next poll will retry */
    });
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.oiTimer) clearInterval(this.oiTimer);
    this.pingTimer = null;
    this.oiTimer = null;
    if (this.ws) {
      this.ws.removeAllListeners();
      this.ws.close();
      this.ws = null;
    }
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    const { WebSocket: WsCtor } = await wsPromise;
    if (this.stopped) return;

    // Build a combined-streams URL so a single connection covers all subs.
    // Format: <base>/stream?streams=<s1>/<s2>/...
    const streams: string[] = [];
    for (const coin of this.symbols) {
      const sym = binanceCoinToSymbol(coin).toLowerCase();
      streams.push(`${sym}@aggTrade`);
      streams.push(`${sym}@markPrice@1s`);
      streams.push(`${sym}@forceOrder`);
    }
    const url = `${this.wsBase}/stream?streams=${streams.join('/')}`;

    const ws = new WsCtor(url);
    this.ws = ws;

    ws.on('open', () => {
      this.reconnectAttempts = 0;
      console.log(
        `[binance] connected ${this.wsBase} streams=${streams.length}`,
      );
      // Binance sends ws-protocol pings; we still send an app-level ping to
      // keep intermediaries happy.
      this.pingTimer = setInterval(() => {
        if (ws.readyState === 1) ws.ping();
      }, PING_INTERVAL_MS);
    });

    ws.on('message', (raw) => {
      try {
        const msg = JSON.parse(raw.toString()) as BinStreamPayload<unknown>;
        if (!msg || typeof msg !== 'object' || !('data' in msg)) return;
        const data = msg.data as { e?: string };
        switch (data.e) {
          case 'aggTrade':
            this.emitTrade(data as BinAggTrade);
            break;
          case 'markPriceUpdate':
            this.emitFunding(data as BinMarkPrice);
            break;
          case 'forceOrder':
            this.emitLiq(data as BinForceOrder);
            break;
        }
      } catch (err) {
        console.error('[binance] bad message', err);
      }
    });

    ws.on('close', (code, reason) => {
      console.warn(
        `[binance] closed code=${code} reason=${reason.toString() || '(none)'}`,
      );
      this.cleanupConnection();
      this.scheduleReconnect();
    });

    ws.on('error', (err) => {
      console.error('[binance] ws error', err.message);
    });
  }

  private cleanupConnection(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    this.ws = null;
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const attempt = ++this.reconnectAttempts;
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** Math.min(attempt - 1, 5),
      RECONNECT_MAX_MS,
    );
    console.log(`[binance] reconnecting in ${delay}ms (attempt ${attempt})`);
    setTimeout(() => {
      void this.connect();
    }, delay);
  }

  private emitTrade(d: BinAggTrade): void {
    const price = Number(d.p);
    const size = Number(d.q);
    if (!Number.isFinite(price) || !Number.isFinite(size)) return;
    const tick: Tick = {
      venue: 'binance',
      symbol: binanceSymbolToCoin(d.s),
      ts: d.T,
      price,
      size,
      // m = buyer is market maker → trade was a SELL aggressor
      side: d.m ? 'sell' : 'buy',
    };
    for (const h of this.tickHandlers) {
      try {
        h(tick);
      } catch (err) {
        console.error('[binance] tick handler threw', err);
      }
    }
  }

  private emitFunding(d: BinMarkPrice): void {
    const rate = Number(d.r);
    if (!Number.isFinite(rate)) return;
    const f: Funding = {
      venue: 'binance',
      symbol: binanceSymbolToCoin(d.s),
      ts: d.E,
      rate,
      nextTs: d.T,
    };
    for (const h of this.fundingHandlers) {
      try {
        h(f);
      } catch (err) {
        console.error('[binance] funding handler threw', err);
      }
    }
  }

  private emitLiq(d: BinForceOrder): void {
    const price = Number(d.o.ap || d.o.p);
    const size = Number(d.o.q);
    if (!Number.isFinite(price) || !Number.isFinite(size)) return;
    // Binance sends the side of the LIQUIDATING order. A SELL liquidation
    // means a long was force-closed; BUY means a short was force-closed.
    const side: 'long' | 'short' = d.o.S === 'SELL' ? 'long' : 'short';
    const l: Liquidation = {
      venue: 'binance',
      symbol: binanceSymbolToCoin(d.o.s),
      ts: d.o.T,
      side,
      size,
      price,
    };
    for (const h of this.liqHandlers) {
      try {
        h(l);
      } catch (err) {
        console.error('[binance] liq handler threw', err);
      }
    }
  }

  private async pollOpenInterest(): Promise<void> {
    if (this.stopped) return;
    const ts = Date.now();
    await Promise.all(
      this.symbols.map(async (coin) => {
        const sym = binanceCoinToSymbol(coin);
        const url = `${this.restBase}/fapi/v1/openInterest?symbol=${sym}`;
        try {
          const res = await fetch(url, { signal: AbortSignal.timeout(8_000) });
          if (!res.ok) return;
          const json = (await res.json()) as { openInterest?: string };
          const oi = Number(json.openInterest);
          if (!Number.isFinite(oi)) return;
          const o: OpenInterest = {
            venue: 'binance',
            symbol: coin.toUpperCase(),
            ts,
            oi,
          };
          for (const h of this.oiHandlers) {
            try {
              h(o);
            } catch (err) {
              console.error('[binance] oi handler threw', err);
            }
          }
        } catch (err) {
          if (err instanceof Error && err.name !== 'AbortError') {
            console.error(`[binance] oi fetch ${sym} failed`, err.message);
          }
        }
      }),
    );
  }
}
