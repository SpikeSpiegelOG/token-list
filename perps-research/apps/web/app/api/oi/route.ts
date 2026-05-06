import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  try {
    const storage = await getStorage();
    const rows = await storage.getLatestOpenInterest();
    return NextResponse.json({ openInterest: rows });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 500 },
    );
  }
}
