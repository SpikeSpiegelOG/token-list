import { NextResponse } from 'next/server';
import type { Bar } from '@perps/core';
import { runBacktest } from '@perps/backtest';
import { buildStrategy, listStrategies } from '@perps/strategies';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  return NextResponse.json({ strategies: listStrategies() });
}

interface BacktestRequest {
  strategy: string;
  params?: Record<string, number>;
  venue?: string;
  symbol?: string;
  /** epoch ms; defaults: last 24h ending now */
  startTs?: number;
  endTs?: number;
  initialCash?: number;
  defaultSize?: number;
  takerFee?: number;
  halfSpread?: number;
}

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as BacktestRequest;
    const venue = body.venue ?? 'hyperliquid';
    const symbol = body.symbol ?? 'BTC';
    const endTs = body.endTs ?? Date.now();
    const startTs = body.startTs ?? endTs - 24 * 60 * 60_000;
    const strategy = buildStrategy(body.strategy, body.params ?? {});

    const storage = await getStorage();
    const candles = await storage.getCandlesInRange(
      venue,
      symbol,
      startTs,
      endTs,
      200_000,
    );
    const bars: Bar[] = candles.map((c) => ({
      venue: venue as Bar['venue'],
      symbol,
      ts: c.ts,
      o: c.o,
      h: c.h,
      l: c.l,
      c: c.c,
      v: c.v,
      tf: '1m',
    }));

    if (bars.length === 0) {
      return NextResponse.json(
        {
          error:
            'No bars in range. Let ingest run for a few minutes to accumulate history, or widen the date range.',
        },
        { status: 400 },
      );
    }

    const result = runBacktest({
      bars,
      strategy,
      initialCash: body.initialCash ?? 10_000,
      defaultSize: body.defaultSize ?? 0.1,
      takerFee: body.takerFee ?? 0.0004,
      halfSpread: body.halfSpread ?? 0.0002,
    });

    return NextResponse.json({ result, barCount: bars.length });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
