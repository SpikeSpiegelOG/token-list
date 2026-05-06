import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const days = Math.min(
    Math.max(parseInt(url.searchParams.get('days') ?? '7', 10), 1),
    30,
  );
  const impactsParam = url.searchParams.get('impacts');
  const impacts = impactsParam
    ? impactsParam.split(',').map((s) => s.trim()).filter(Boolean)
    : ['High', 'Medium'];
  const now = Date.now();
  try {
    const storage = await getStorage();
    const events = await storage.getMacroEvents({
      fromTs: now - 24 * 60 * 60_000, // include yesterday
      toTs: now + days * 24 * 60 * 60_000,
      impacts,
      limit: 500,
    });
    return NextResponse.json({ events });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
