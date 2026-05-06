import { getTickBus } from '@perps/core';
import { BarRollup, Storage } from '@perps/storage';
import { BinanceFuturesAdapter } from '@perps/venue-binance';
import { HyperliquidAdapter } from '@perps/venue-hyperliquid';

async function main() {
  const symbols = (process.env.INGEST_SYMBOLS ?? 'BTC,ETH,SOL')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const venuesEnv = (process.env.INGEST_VENUES ?? 'hyperliquid,binance')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const dbPath = process.env.DUCKDB_PATH ?? './data/perps.duckdb';

  console.log(
    `[ingest] venues=${venuesEnv.join(',')} symbols=${symbols.join(',')} db=${dbPath}`,
  );

  const storage = new Storage({ path: dbPath });
  await storage.open();

  const bus = getTickBus();
  const rollup = new BarRollup('1m');
  rollup.onClose((bar) => storage.enqueueBar(bar));

  const lastFunding = new Map<string, { rate: number; ts: number }>();
  const lastOi = new Map<string, { oi: number; ts: number }>();
  const FUNDING_DROP_MS = 60_000;
  const FUNDING_RATE_EPS = 1e-9;
  const OI_DROP_MS = 60_000;
  const OI_REL_EPS = 0.001;

  type Adapter = {
    venue: string;
    onTick: (h: (t: any) => void) => void;
    onFunding?: (h: (f: any) => void) => void;
    onOpenInterest?: (h: (o: any) => void) => void;
    onLiquidation?: (h: (l: any) => void) => void;
    start: (s: readonly string[]) => Promise<void>;
    stop: () => Promise<void>;
  };
  const adapters: Adapter[] = [];
  if (venuesEnv.includes('hyperliquid')) adapters.push(new HyperliquidAdapter());
  if (venuesEnv.includes('binance')) adapters.push(new BinanceFuturesAdapter());

  for (const adapter of adapters) {
    adapter.onTick((tick) => {
      storage.enqueueTick(tick);
      const { open } = rollup.ingest(tick);
      storage.enqueueBar(open);
      bus.publish(tick);
    });
    adapter.onFunding?.((f) => {
      const key = `${f.venue}:${f.symbol}`;
      const prev = lastFunding.get(key);
      const changed =
        !prev ||
        Math.abs(prev.rate - f.rate) > FUNDING_RATE_EPS ||
        f.ts - prev.ts > FUNDING_DROP_MS;
      if (changed) {
        lastFunding.set(key, { rate: f.rate, ts: f.ts });
        storage.enqueueFunding(f);
      }
    });
    adapter.onOpenInterest?.((o) => {
      const key = `${o.venue}:${o.symbol}`;
      const prev = lastOi.get(key);
      const changed =
        !prev ||
        Math.abs(o.oi - prev.oi) / Math.max(prev.oi, 1) > OI_REL_EPS ||
        o.ts - prev.ts > OI_DROP_MS;
      if (changed) {
        lastOi.set(key, { oi: o.oi, ts: o.ts });
        storage.enqueueOpenInterest(o);
      }
    });
    adapter.onLiquidation?.((l) => storage.enqueueLiquidation(l));
  }

  for (const a of adapters) {
    await a.start(symbols);
  }

  const statsTimer = setInterval(async () => {
    try {
      const n = await storage.tickCount();
      console.log(`[ingest] ticks_persisted=${n} bus_subscribers=${bus.size()}`);
    } catch (err) {
      console.error('[ingest] stats failed', err);
    }
  }, 30_000);
  if (statsTimer.unref) statsTimer.unref();

  const shutdown = async (signal: string) => {
    console.log(`[ingest] ${signal} — shutting down`);
    clearInterval(statsTimer);
    for (const a of adapters) {
      await a.stop();
    }
    await storage.close();
    process.exit(0);
  };
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
}

main().catch((err) => {
  console.error('[ingest] fatal', err);
  process.exit(1);
});
