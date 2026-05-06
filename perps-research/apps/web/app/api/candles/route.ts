import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbol = url.searchParams.get('symbol') ?? 'BTC';
  const venue = url.searchParams.get('venue') ?? 'hyperliquid';
  const limit = Math.min(
    Math.max(parseInt(url.searchParams.get('limit') ?? '500', 10), 1),
    5000,
  );

  try {
    const storage = await getStorage();
    const rows = await storage.getCandles(venue, symbol, limit);
    return NextResponse.json({ venue, symbol, candles: rows });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
