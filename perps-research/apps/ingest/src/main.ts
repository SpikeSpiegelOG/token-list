import { getTickBus } from '@perps/core';
import { BarRollup, Storage } from '@perps/storage';
import { HyperliquidAdapter } from '@perps/venue-hyperliquid';

async function main() {
  const symbols = (process.env.INGEST_SYMBOLS ?? 'BTC,ETH,SOL')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const dbPath = process.env.DUCKDB_PATH ?? './data/perps.duckdb';

  console.log(`[ingest] symbols=${symbols.join(',')} db=${dbPath}`);

  const storage = new Storage({ path: dbPath });
  await storage.open();

  const bus = getTickBus();
  const rollup = new BarRollup('1m');

  rollup.onClose((bar) => {
    storage.enqueueBar(bar);
  });

  const adapter = new HyperliquidAdapter();
  adapter.onTick((tick) => {
    storage.enqueueTick(tick);
    const { open } = rollup.ingest(tick);
    // Always flush the in-progress bar so the chart sees the latest wick.
    storage.enqueueBar(open);
    bus.publish(tick);
  });

  await adapter.start(symbols);

  // Periodic stats so a running process is observable.
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
    await adapter.stop();
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
