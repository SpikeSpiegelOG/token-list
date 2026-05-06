import Link from 'next/link';
import { PriceChart } from '@/components/PriceChart';

export const dynamic = 'force-dynamic';

export default async function ChartPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  const venue = 'hyperliquid';

  return (
    <main style={{ padding: 16 }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 16,
          marginBottom: 12,
        }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>
          {venue} · {symbol}
        </h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>1m candles · EMA(20)</span>
      </header>
      <PriceChart venue={venue} symbol={symbol} />
    </main>
  );
}
