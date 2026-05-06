import Link from 'next/link';
import { LiquidationTape } from '@/components/LiquidationTape';

export const dynamic = 'force-dynamic';

export default function LiquidationsPage() {
  return (
    <main style={{ padding: 16, maxWidth: 1080, margin: '0 auto' }}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>Liquidation tape</h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>
          live · 2s refresh · binance forceOrder
        </span>
      </header>
      <LiquidationTape />
      <p style={{ color: '#8a93a6', fontSize: 12, marginTop: 16 }}>
        Liq-sweep-fade hypothesis: cascading liquidations of one side often
        overshoot price, creating a short-window mean-reversion edge. Needs
        size filtering (notional &gt; threshold), time clustering, and a
        regime filter — the unfiltered tape will lose to fees.
      </p>
    </main>
  );
}
