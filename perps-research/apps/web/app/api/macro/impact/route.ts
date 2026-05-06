import { NextResponse } from 'next/server';
import { computeEventImpact } from '@perps/macro';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const titleLike = url.searchParams.get('title') ?? 'CPI';
  const venue = url.searchParams.get('venue') ?? 'hyperliquid';
  const symbol = url.searchParams.get('symbol') ?? 'BTC';
  const days = Math.min(
    Math.max(parseInt(url.searchParams.get('days') ?? '90', 10), 1),
    365,
  );
  const now = Date.now();
  try {
    const storage = await getStorage();
    const result = await computeEventImpact({
      storage,
      venue,
      symbol,
      titleLike,
      fromTs: now - days * 24 * 60 * 60_000,
      toTs: now,
    });
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
