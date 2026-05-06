import type { Funding, OpenInterest, Tick, VenueAdapter } from '@perps/core';

// Dynamic import keeps `ws` (and its optional native deps) opaque to
// bundlers. Next.js's webpack mangles a static `import 'ws'` even when the
// package is listed in `serverExternalPackages`.
type WsModule = typeof import('ws');
type WsInstance = InstanceType<WsModule['WebSocket']>;
const wsPromise: Promise<WsModule> = (
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  new Function('return import("ws")') as () => Promise<WsModule>
)();

interface HlTrade {
  coin: string;
  side: 'A' | 'B'; // A=ask=sell-aggressor, B=bid=buy-aggressor
  px: string;
  sz: string;
  time: number;
  hash?: string;
  tid?: number;
}

interface HlActiveAssetCtx {
  coin: string;
  ctx: {
    markPx?: number | string;
    midPx?: number | string;
    oraclePx?: number | string;
    funding?: number | string;
    openInterest?: number | string;
    dayNtlVlm?: number | string;
    prevDayPx?: number | string;
  };
}

interface HlEnvelope {
  channel: string;
  data: unknown;
}

const DEFAULT_URL = 'wss://api.hyperliquid.xyz/ws';
const PING_INTERVAL_MS = 30_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

/** HL funding is hourly; ts = ceiling of now to the next whole hour. */
function nextFundingTs(now: number): number {
  const HOUR = 3_600_000;
  return Math.ceil(now / HOUR) * HOUR;
}

export class HyperliquidAdapter implements VenueAdapter {
  readonly venue = 'hyperliquid' as const;

  private ws: WsInstance | null = null;
  private symbols: readonly string[] = [];
  private tickHandlers: Array<(t: Tick) => void> = [];
  private fundingHandlers: Array<(f: Funding) => void> = [];
  private oiHandlers: Array<(o: OpenInterest) => void> = [];
  private pingTimer: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private stopped = false;
  private readonly url: string;

  constructor(opts: { url?: string } = {}) {
    this.url = opts.url ?? DEFAULT_URL;
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

  async start(symbols: readonly string[]): Promise<void> {
    this.symbols = symbols;
    this.stopped = false;
    await this.connect();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
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
    const ws = new WsCtor(this.url);
    this.ws = ws;

    ws.on('open', () => {
      this.reconnectAttempts = 0;
      console.log(`[hyperliquid] connected ${this.url}`);
      for (const coin of this.symbols) {
        ws.send(
          JSON.stringify({
            method: 'subscribe',
            subscription: { type: 'trades', coin },
          }),
        );
        ws.send(
          JSON.stringify({
            method: 'subscribe',
            subscription: { type: 'activeAssetCtx', coin },
          }),
        );
        console.log(`[hyperliquid] subscribed trades+ctx:${coin}`);
      }
      // keepalive ping (1 = OPEN per WS spec)
      this.pingTimer = setInterval(() => {
        if (ws.readyState === 1) {
          ws.send(JSON.stringify({ method: 'ping' }));
        }
      }, PING_INTERVAL_MS);
    });

    ws.on('message', (raw) => {
      try {
        const env = JSON.parse(raw.toString()) as HlEnvelope;
        if (env.channel === 'trades' && Array.isArray(env.data)) {
          for (const t of env.data as HlTrade[]) {
            this.emitTrade(t);
          }
        } else if (env.channel === 'activeAssetCtx' && env.data) {
          this.emitCtx(env.data as HlActiveAssetCtx);
        }
        // 'subscriptionResponse' and 'pong' channels are noise; ignore.
      } catch (err) {
        console.error('[hyperliquid] bad message', err);
      }
    });

    ws.on('close', (code, reason) => {
      console.warn(
        `[hyperliquid] closed code=${code} reason=${reason.toString() || '(none)'}`,
      );
      this.cleanupConnection();
      this.scheduleReconnect();
    });

    ws.on('error', (err) => {
      console.error('[hyperliquid] ws error', err.message);
      // 'close' will follow; reconnect happens there.
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
    console.log(`[hyperliquid] reconnecting in ${delay}ms (attempt ${attempt})`);
    setTimeout(() => {
      void this.connect();
    }, delay);
  }

  private emitTrade(t: HlTrade): void {
    const price = Number(t.px);
    const size = Number(t.sz);
    if (!Number.isFinite(price) || !Number.isFinite(size)) return;
    const tick: Tick = {
      venue: 'hyperliquid',
      symbol: t.coin,
      ts: t.time,
      price,
      size,
      side: t.side === 'B' ? 'buy' : 'sell',
    };
    for (const h of this.tickHandlers) {
      try {
        h(tick);
      } catch (err) {
        console.error('[hyperliquid] tick handler threw', err);
      }
    }
  }

  private emitCtx(d: HlActiveAssetCtx): void {
    const now = Date.now();
    const symbol = d.coin;
    const fund = Number(d.ctx?.funding);
    if (Number.isFinite(fund)) {
      const f: Funding = {
        venue: 'hyperliquid',
        symbol,
        ts: now,
        rate: fund,
        nextTs: nextFundingTs(now),
      };
      for (const h of this.fundingHandlers) {
        try {
          h(f);
        } catch (err) {
          console.error('[hyperliquid] funding handler threw', err);
        }
      }
    }
    const oi = Number(d.ctx?.openInterest);
    if (Number.isFinite(oi)) {
      const o: OpenInterest = {
        venue: 'hyperliquid',
        symbol,
        ts: now,
        oi,
      };
      for (const h of this.oiHandlers) {
        try {
          h(o);
        } catch (err) {
          console.error('[hyperliquid] oi handler threw', err);
        }
      }
    }
  }
}
