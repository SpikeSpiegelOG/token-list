import Link from 'next/link';
import { PaperPanel } from '@/components/PaperPanel';

export const dynamic = 'force-dynamic';

export default function PaperPage() {
  return (
    <main style={{ padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>Paper trader</h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>
          live · 5s refresh · simulated only
        </span>
      </header>
      <PaperPanel />
      <p style={{ color: '#8a93a6', fontSize: 12, marginTop: 24 }}>
        This is paper-trading only — no real-money order routing exists in
        this codebase. The strategy runs against the same closed 1m bars
        that feed the chart, with the same half-spread + taker-fee
        slippage model the backtester uses, so a strategy validated in
        backtest will produce comparable behavior here. Run for at least
        a month (and across regime changes) before drawing conclusions.
      </p>
    </main>
  );
}
