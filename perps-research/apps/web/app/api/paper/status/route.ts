import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const engine = globalThis.__perpsPaperEngine;
  if (!engine) {
    return NextResponse.json(
      {
        running: false,
        hint: 'Set PERPS_PAPER_STRATEGY (and optionally PERPS_PAPER_SYMBOL / PARAMS / etc.) and restart the server.',
      },
      { status: 200 },
    );
  }
  return NextResponse.json({ running: true, status: engine.status() });
}
