import Link from 'next/link';
import { FundingTable } from '@/components/FundingTable';

export const dynamic = 'force-dynamic';

export default function FundingPage() {
  return (
    <main style={{ padding: 16, maxWidth: 1080, margin: '0 auto' }}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>Funding & Open Interest</h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>
          live · 5s refresh · cross-venue
        </span>
      </header>
      <FundingTable />
      <p style={{ color: '#8a93a6', fontSize: 12, marginTop: 16 }}>
        Funding-arb hypothesis: long the cheaper-funding venue, short the expensive
        one — but only when the basis covers fees + slippage + position risk. The
        APR shown is naive (rate × periods/year); real-world capture is lower
        after rebalancing costs.
      </p>
    </main>
  );
}
