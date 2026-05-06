import { getTickBus, type Tick } from '@perps/core';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * SSE stream of live ticks for a (venue, symbol). Subscribes to the
 * in-process TickBus that instrumentation.ts populates from the WS adapter.
 */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ symbol: string }> },
) {
  const { symbol } = await ctx.params;
  const url = new URL(req.url);
  const venue = url.searchParams.get('venue') ?? 'hyperliquid';

  const bus = getTickBus();
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    start(controller) {
      const send = (event: string, data: unknown) => {
        try {
          controller.enqueue(
            encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
          );
        } catch {
          // Client disconnected while we were enqueueing.
        }
      };
      send('hello', { venue, symbol });

      const onTick = (t: Tick) => {
        if (t.venue !== venue || t.symbol !== symbol) return;
        send('tick', { ts: t.ts, price: t.price, size: t.size, side: t.side });
      };
      const unsub = bus.subscribe(onTick);

      // Heartbeat every 15s so proxies don't kill the connection.
      const heartbeat = setInterval(() => send('ping', { ts: Date.now() }), 15_000);

      const abort = () => {
        unsub();
        clearInterval(heartbeat);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      };
      req.signal.addEventListener('abort', abort);
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
