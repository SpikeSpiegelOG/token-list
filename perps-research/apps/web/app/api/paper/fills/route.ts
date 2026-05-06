import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const runId = url.searchParams.get('runId') ?? 'default';
  const limit = Math.min(
    Math.max(parseInt(url.searchParams.get('limit') ?? '200', 10), 1),
    1000,
  );
  try {
    const storage = await getStorage();
    const rows = await storage.getPaperFills(runId, limit);
    return NextResponse.json({ fills: rows });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
