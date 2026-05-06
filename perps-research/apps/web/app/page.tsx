import Link from 'next/link';

const SYMBOLS = ['BTC', 'ETH', 'SOL'];

export default function Home() {
  return (
    <main style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>perps-research</h1>
      <p style={{ color: '#8a93a6', marginTop: 0 }}>
        Live perps data → DuckDB → TradingView Lightweight Charts.
      </p>

      <h2 style={{ fontSize: 16, marginTop: 32 }}>Charts</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {SYMBOLS.map((s) => (
          <li key={s} style={{ marginBottom: 8 }}>
            <Link href={`/chart/${s}`}>/chart/{s}</Link>
            <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
              hyperliquid
            </span>
          </li>
        ))}
      </ul>

      <h2 style={{ fontSize: 16, marginTop: 24 }}>Cross-venue</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        <li style={{ marginBottom: 8 }}>
          <Link href="/funding">/funding</Link>
          <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
            funding rates + open interest, hyperliquid &amp; binance
          </span>
        </li>
        <li style={{ marginBottom: 8 }}>
          <Link href="/liquidations">/liquidations</Link>
          <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
            live forced-order tape
          </span>
        </li>
      </ul>

      <h2 style={{ fontSize: 16, marginTop: 24 }}>Research</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        <li style={{ marginBottom: 8 }}>
          <Link href="/backtest">/backtest</Link>
          <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
            replay 1m bars through a strategy, see equity / Sharpe / DD
          </span>
        </li>
        <li style={{ marginBottom: 8 }}>
          <Link href="/macro">/macro</Link>
          <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
            CPI / FOMC / NFP calendar, news, event-impact correlation
          </span>
        </li>
        <li style={{ marginBottom: 8 }}>
          <Link href="/paper">/paper</Link>
          <span style={{ color: '#8a93a6', marginLeft: 8, fontSize: 12 }}>
            live paper trader (gated by PERPS_PAPER_STRATEGY env)
          </span>
        </li>
      </ul>

      <p style={{ color: '#8a93a6', marginTop: 32, fontSize: 12 }}>
        Phase 5. Real-money order routing is intentionally out of scope.
      </p>
    </main>
  );
}
