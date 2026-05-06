import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { Storage } from '@perps/storage';

declare global {
  // eslint-disable-next-line no-var
  var __perpsStorage: Storage | undefined;
}

/**
 * The instrumentation hook (instrumentation.ts) opens the writable Storage
 * and assigns it to globalThis.__perpsStorage at server boot. API routes
 * call this to get the same instance.
 *
 * If instrumentation didn't run (e.g. PERPS_DISABLE_INGEST=1 in tests), we
 * lazily open a writable Storage here so the candles route still works.
 */
export async function getStorage(): Promise<Storage> {
  if (!globalThis.__perpsStorage) {
    const path = resolve(process.env.DUCKDB_PATH ?? './data/perps.duckdb');
    if (!existsSync(path)) {
      const seed = new Storage({ path });
      await seed.open();
      await seed.close();
    }
    const s = new Storage({ path });
    await s.open();
    globalThis.__perpsStorage = s;
  }
  return globalThis.__perpsStorage;
}
