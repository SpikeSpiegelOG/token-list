/**
 * Next.js instrumentation hook. Runs once at server start. We use it to boot
 * the Hyperliquid WS adapter inside the same process as the web app, so the
 * SSE route can subscribe to the in-memory TickBus and the API routes can
 * read from the same DuckDB connection. (DuckDB takes an exclusive file
 * lock, so colocating ingest+web is the cleanest single-machine setup.)
 *
 * For production / multi-machine deploys (Phase 2), run apps/ingest as a
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

  const symbols = (process.env.INGEST_SYMBOLS ?? 'BTC,ETH,SOL')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const dbPath = process.env.DUCKDB_PATH ?? './data/perps.duckdb';

  console.log(`[instrumentation] starting ingest symbols=${symbols.join(',')} db=${dbPath}`);

  const storage = new Storage({ path: dbPath });
  await storage.open();

  const bus = getTickBus();
  const rollup = new BarRollup('1m');
  rollup.onClose((bar) => storage.enqueueBar(bar));

  const adapter = new HyperliquidAdapter();
  adapter.onTick((tick) => {
    storage.enqueueTick(tick);
    const { open } = rollup.ingest(tick);
    storage.enqueueBar(open);
    bus.publish(tick);
  });

  await adapter.start(symbols);

  // Cache for API routes; same process so getStorage() reuses this instance.
  globalThis.__perpsStorage = storage;

  const shutdown = async (signal: string) => {
    console.log(`[instrumentation] ${signal} — shutting down`);
    await adapter.stop();
    await storage.close();
  };
  process.once('SIGINT', () => void shutdown('SIGINT'));
  process.once('SIGTERM', () => void shutdown('SIGTERM'));
}
