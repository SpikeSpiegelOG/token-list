import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const runId = url.searchParams.get('runId') ?? 'default';
  const limit = Math.min(
    Math.max(parseInt(url.searchParams.get('limit') ?? '5000', 10), 1),
    50_000,
  );
  try {
    const storage = await getStorage();
    const rows = await storage.getPaperEquity(runId, limit);
    // newest-first → reverse for chart
    return NextResponse.json({ equity: rows.reverse() });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
