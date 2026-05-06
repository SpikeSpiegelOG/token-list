/**
 * Next.js instrumentation hook. Runs once at server start. We use it to boot
 * the WS adapters inside the same process as the web app, so the SSE route
 * can subscribe to the in-memory TickBus and the API routes can read from
 * the same DuckDB connection. (DuckDB takes an exclusive file lock, so
 * colocating ingest+web is the cleanest single-machine setup.)
 *
 * For production / multi-machine deploys (Phase 2.5+), run apps/ingest as a
 * separate worker against a shared database (Postgres/TimescaleDB) instead.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  // Disable inside `next build` static generation.
  if (process.env.NEXT_PHASE === 'phase-production-build') return;
  // Allow opt-out (e.g. CI smoke tests).
  if (process.env.PERPS_DISABLE_INGEST === '1') return;

  const { getTickBus } = await import('@perps/core');
  const { Storage, BarRollup } = await import('@perps/storage');
  const { HyperliquidAdapter } = await import('@perps/venue-hyperliquid');
  const { BinanceFuturesAdapter } = await import('@perps/venue-binance');
  const { startMacroFetchers } = await import('@perps/macro');

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
    `[instrumentation] starting ingest venues=${venuesEnv.join(',')} symbols=${symbols.join(',')} db=${dbPath}`,
  );

  const storage = new Storage({ path: dbPath });
  await storage.open();

  const bus = getTickBus();
  // One rollup per venue keeps cross-venue 1m bars from contaminating each
  // other. The rollup keys by venue+symbol internally so a single instance
  // works too; keeping it simple here.
  const rollup = new BarRollup('1m');
  rollup.onClose((bar) => storage.enqueueBar(bar));

  // Throttling: funding rate and OI are republished frequently with the
  // same value. Persist only when the value changes meaningfully OR every
  // 60s, whichever comes first.
  const lastFunding = new Map<string, { rate: number; ts: number }>();
  const lastOi = new Map<string, { oi: number; ts: number }>();
  const FUNDING_DROP_MS = 60_000;
  const FUNDING_RATE_EPS = 1e-9;
  const OI_DROP_MS = 60_000;
  const OI_REL_EPS = 0.001; // 0.1% change

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

  globalThis.__perpsStorage = storage;

  // Phase 4: macro/news fetchers. Calendar runs without keys; CryptoPanic
  // is gated by CRYPTOPANIC_TOKEN — both fail soft.
  const macroEnabled = process.env.PERPS_DISABLE_MACRO !== '1';
  const macroHandle = macroEnabled
    ? startMacroFetchers({ storage })
    : null;

  const shutdown = async (signal: string) => {
    console.log(`[instrumentation] ${signal} — shutting down`);
    macroHandle?.stop();
    for (const a of adapters) {
      await a.stop();
    }
    await storage.close();
  };
  process.once('SIGINT', () => void shutdown('SIGINT'));
  process.once('SIGTERM', () => void shutdown('SIGTERM'));
}
