import Link from 'next/link';
import { BacktestPanel } from '@/components/BacktestPanel';

export const dynamic = 'force-dynamic';

export default function BacktestPage() {
  return (
    <main style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>Backtest</h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>
          1m bars from DuckDB · in-process replay
        </span>
      </header>
      <BacktestPanel />
      <p style={{ color: '#8a93a6', fontSize: 12, marginTop: 16 }}>
        These are <em>starter hypotheses</em>, not validated edges. Single-run
        results are noise; meaningful evaluation needs walk-forward
        out-of-sample, regime stratification, and monte-carlo over reasonable
        parameter ranges. The numbers above are a sanity check on the
        plumbing — nothing more.
      </p>
    </main>
  );
}
