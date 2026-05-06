import type { Storage } from '@perps/storage';
import { fetchCryptoNews } from './cryptopanic.js';
import { fetchEconomicCalendar } from './forexfactory.js';

const CALENDAR_INTERVAL_MS = 6 * 60 * 60_000; // 6h
const NEWS_INTERVAL_MS = 5 * 60_000; // 5m

interface SchedulerHandle {
  stop(): void;
}

/**
 * Boots periodic background fetchers for macro events and crypto news.
 *
 * Calendar: ForexFactory weekly XML, no auth, 6h cadence (file rotates
 * once a day so this is comfortably oversampled).
 *
 * News: CryptoPanic public posts, gated by env CRYPTOPANIC_TOKEN. If the
 * token is absent, the fetcher is a no-op so the rest of the system runs.
 */
export function startMacroFetchers(opts: {
  storage: Storage;
  cryptopanicToken?: string;
  /** override fetch intervals (mainly for tests) */
  calendarIntervalMs?: number;
  newsIntervalMs?: number;
}): SchedulerHandle {
  const calMs = opts.calendarIntervalMs ?? CALENDAR_INTERVAL_MS;
  const newsMs = opts.newsIntervalMs ?? NEWS_INTERVAL_MS;
  const token = opts.cryptopanicToken ?? process.env.CRYPTOPANIC_TOKEN;

  const tickCal = async () => {
    try {
      const events = await fetchEconomicCalendar({
        signal: AbortSignal.timeout(15_000),
      });
      await opts.storage.upsertMacroEvents(events);
      console.log(`[macro] calendar refreshed (${events.length} events)`);
    } catch (err) {
      console.error('[macro] calendar fetch failed', (err as Error).message);
    }
  };

  const tickNews = async () => {
    if (!token) return;
    try {
      const news = await fetchCryptoNews({
        token,
        signal: AbortSignal.timeout(15_000),
      });
      await opts.storage.upsertNewsItems(news);
      if (news.length > 0) {
        console.log(`[macro] news refreshed (${news.length} items)`);
      }
    } catch (err) {
      console.error('[macro] news fetch failed', (err as Error).message);
    }
  };

  // Kick off both immediately, then on cadence.
  void tickCal();
  void tickNews();
  const calTimer = setInterval(() => void tickCal(), calMs);
  const newsTimer = setInterval(() => void tickNews(), newsMs);
  if (calTimer.unref) calTimer.unref();
  if (newsTimer.unref) newsTimer.unref();

  return {
    stop() {
      clearInterval(calTimer);
      clearInterval(newsTimer);
    },
  };
}
