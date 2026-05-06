import type { Tick } from './types.js';

/**
 * In-memory pub/sub for ticks. The ingest process publishes; the web app
 * subscribes for SSE fan-out when running in the same Node process.
 *
 * For multi-process deployment (Phase 2+), swap this for a Redis pub/sub or
 * a fly.io machine-to-machine WS. The interface stays the same.
 */
export class TickBus {
  private handlers = new Set<(t: Tick) => void>();

  publish(tick: Tick): void {
    for (const h of this.handlers) {
      try {
        h(tick);
      } catch (err) {
        // a misbehaving subscriber must not break the bus
        console.error('[TickBus] subscriber threw', err);
      }
    }
  }

  subscribe(handler: (t: Tick) => void): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  size(): number {
    return this.handlers.size;
  }
}

/** Process-wide singleton so ingest and web (when colocated) share one bus. */
declare global {
  // eslint-disable-next-line no-var
  var __perpsTickBus: TickBus | undefined;
}

export function getTickBus(): TickBus {
  if (!globalThis.__perpsTickBus) {
    globalThis.__perpsTickBus = new TickBus();
  }
  return globalThis.__perpsTickBus;
}
