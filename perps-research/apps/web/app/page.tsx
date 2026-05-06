import Link from 'next/link';

const SYMBOLS = ['BTC', 'ETH', 'SOL'];

export default function Home() {
  return (
    <main style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>perps-research</h1>
      <p style={{ color: '#8a93a6', marginTop: 0 }}>
        Live Hyperliquid trades → DuckDB → Lightweight Charts.
      </p>

      <h2 style={{ fontSize: 16, marginTop: 32 }}>Charts</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {SYMBOLS.map((s) => (
          <li key={s} style={{ marginBottom: 8 }}>
            <Link href={`/chart/${s}`}>/chart/{s}</Link>
          </li>
        ))}
      </ul>

      <p style={{ color: '#8a93a6', marginTop: 32, fontSize: 12 }}>
        Phase 1. Real-money order routing is intentionally out of scope.
      </p>
    </main>
  );
}
