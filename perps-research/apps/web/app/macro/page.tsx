import Link from 'next/link';
import { MacroPanel } from '@/components/MacroPanel';

export const dynamic = 'force-dynamic';

export default function MacroPage() {
  return (
    <main style={{ padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      <header
        style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}
      >
        <Link href="/" style={{ fontSize: 12 }}>
          ← home
        </Link>
        <h1 style={{ fontSize: 18, margin: 0 }}>Macro &amp; news</h1>
        <span style={{ color: '#8a93a6', fontSize: 12 }}>
          forexfactory · cryptopanic · 30s refresh
        </span>
      </header>
      <MacroPanel />
      <p style={{ color: '#8a93a6', fontSize: 12, marginTop: 24 }}>
        Event-impact stats are computed from your local 1m bar history.
        Numbers are unreliable until you have at least a few observations
        per event type and several weeks of price coverage. Treat single-N
        results with extreme skepticism — release-day reactions vary by
        regime (rate-cut vs hike, hot vs cold print) and a small sample
        will mostly tell you about idiosyncratic days.
      </p>
    </main>
  );
}
