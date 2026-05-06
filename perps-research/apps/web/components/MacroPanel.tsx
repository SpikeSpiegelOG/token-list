'use client';

import { useEffect, useMemo, useState } from 'react';

interface MacroEvent {
  id: string;
  title: string;
  country: string;
  ts: number | null;
  impact: string;
  forecast: string | null;
  previous: string | null;
  actual: string | null;
  url: string | null;
}

interface NewsItem {
  id: string;
  source: string;
  ts: number;
  title: string;
  url: string;
  domain: string | null;
  sentiment: string | null;
  votesPos: number;
  votesNeg: number;
}

interface ImpactRow {
  offsetMin: number;
  n: number;
  meanRet: number;
  medianRet: number;
  stdRet: number;
}

interface ImpactResult {
  title: string;
  venue: string;
  symbol: string;
  events: number;
  rows: ImpactRow[];
}

const IMPACT_COLOR: Record<string, string> = {
  High: '#ef5350',
  Medium: '#f7c948',
  Low: '#8a93a6',
  Holiday: '#6c7280',
};

const SYMBOLS = ['BTC', 'ETH', 'SOL'];
const PRESET_TITLES = ['CPI', 'PPI', 'NFP', 'FOMC', 'GDP', 'PCE', 'Unemployment Rate'];

function fmtTs(ts: number | null): string {
  if (ts === null) return 'TBD';
  const d = new Date(ts);
  return d.toISOString().slice(0, 16).replace('T', ' ') + 'Z';
}

function fmtPct(x: number, digits = 3): string {
  const sign = x > 0 ? '+' : '';
  return `${sign}${(x * 100).toFixed(digits)}%`;
}

export function MacroPanel() {
  const [events, setEvents] = useState<MacroEvent[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [impact, setImpact] = useState<ImpactResult | null>(null);
  const [impactTitle, setImpactTitle] = useState('CPI');
  const [impactSymbol, setImpactSymbol] = useState('BTC');
  const [impactLoading, setImpactLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [evRes, newsRes] = await Promise.all([
          fetch('/api/macro/events?days=7&impacts=High,Medium', { cache: 'no-store' }),
          fetch('/api/macro/news?limit=30', { cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (evRes.ok) {
          const j = (await evRes.json()) as { events: MacroEvent[] };
          setEvents(j.events);
        }
        if (newsRes.ok) {
          const j = (await newsRes.json()) as { news: NewsItem[] };
          setNews(j.news);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void tick();
    const id = setInterval(tick, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const runImpact = async () => {
    setImpactLoading(true);
    try {
      const res = await fetch(
        `/api/macro/impact?title=${encodeURIComponent(impactTitle)}&symbol=${impactSymbol}`,
        { cache: 'no-store' },
      );
      const j = (await res.json()) as ImpactResult;
      setImpact(j);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setImpactLoading(false);
    }
  };

  const upcoming = useMemo(() => {
    const now = Date.now();
    return events.filter((e) => e.ts !== null && e.ts >= now - 60_000);
  }, [events]);
  const past = useMemo(() => {
    const now = Date.now();
    return events.filter((e) => e.ts !== null && e.ts < now - 60_000).slice(-30).reverse();
  }, [events]);

  return (
    <div>
      {error && <p style={{ color: '#ef5350', fontSize: 13 }}>error: {error}</p>}

      <h3 style={h3}>Upcoming high/medium-impact events (next 7 days)</h3>
      {upcoming.length === 0 ? (
        <p style={{ color: '#8a93a6', fontSize: 13 }}>
          No events yet. The calendar refreshes every 6 hours; first fetch
          happens on server start.
        </p>
      ) : (
        <table style={tbl}>
          <thead>
            <tr>
              <th style={th}>when</th>
              <th style={th}>country</th>
              <th style={th}>event</th>
              <th style={th}>impact</th>
              <th style={th}>forecast</th>
              <th style={th}>previous</th>
            </tr>
          </thead>
          <tbody>
            {upcoming.slice(0, 30).map((e) => (
              <tr key={e.id}>
                <td style={td}>{fmtTs(e.ts)}</td>
                <td style={tdSym}>{e.country}</td>
                <td style={td}>
                  {e.url ? (
                    <a href={e.url} target="_blank" rel="noreferrer">
                      {e.title}
                    </a>
                  ) : (
                    e.title
                  )}
                </td>
                <td style={{ ...td, color: IMPACT_COLOR[e.impact] }}>{e.impact}</td>
                <td style={td}>{e.forecast ?? '—'}</td>
                <td style={td}>{e.previous ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={h3}>Event-impact correlation</h3>
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'flex-end',
          padding: 12,
          border: '1px solid #2a3145',
          borderRadius: 6,
          background: '#11151c',
          marginBottom: 12,
        }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: '#8a93a6' }}>event title</span>
          <select
            value={impactTitle}
            onChange={(e) => setImpactTitle(e.target.value)}
            style={selStyle}
          >
            {PRESET_TITLES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: '#8a93a6' }}>symbol</span>
          <select
            value={impactSymbol}
            onChange={(e) => setImpactSymbol(e.target.value)}
            style={selStyle}
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button onClick={runImpact} disabled={impactLoading}>
          {impactLoading ? 'computing…' : 'compute impact'}
        </button>
      </div>

      {impact && (
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 13, color: '#8a93a6' }}>
            {impact.events} events matched · {impact.venue}/{impact.symbol}
          </p>
          {impact.events === 0 ? (
            <p style={{ color: '#8a93a6', fontSize: 13 }}>
              No matching events in the calendar window — accumulate more
              data first, or pick a different event title.
            </p>
          ) : (
            <table style={tbl}>
              <thead>
                <tr>
                  <th style={th}>offset</th>
                  <th style={{ ...th, textAlign: 'right' }}>n</th>
                  <th style={{ ...th, textAlign: 'right' }}>mean</th>
                  <th style={{ ...th, textAlign: 'right' }}>median</th>
                  <th style={{ ...th, textAlign: 'right' }}>std</th>
                </tr>
              </thead>
              <tbody>
                {impact.rows.map((r) => (
                  <tr key={r.offsetMin}>
                    <td style={td}>{r.offsetMin >= 0 ? `+${r.offsetMin}` : r.offsetMin}m</td>
                    <td style={tdNum}>{r.n}</td>
                    <td
                      style={{
                        ...tdNum,
                        color:
                          r.n === 0
                            ? '#4a5266'
                            : r.meanRet >= 0
                              ? '#26a69a'
                              : '#ef5350',
                      }}
                    >
                      {r.n === 0 ? '—' : fmtPct(r.meanRet)}
                    </td>
                    <td
                      style={{
                        ...tdNum,
                        color:
                          r.n === 0
                            ? '#4a5266'
                            : r.medianRet >= 0
                              ? '#26a69a'
                              : '#ef5350',
                      }}
                    >
                      {r.n === 0 ? '—' : fmtPct(r.medianRet)}
                    </td>
                    <td style={tdNum}>{r.n === 0 ? '—' : fmtPct(r.stdRet)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <h3 style={h3}>Recent past events</h3>
      {past.length === 0 ? (
        <p style={{ color: '#8a93a6', fontSize: 13 }}>—</p>
      ) : (
        <table style={tbl}>
          <thead>
            <tr>
              <th style={th}>when</th>
              <th style={th}>country</th>
              <th style={th}>event</th>
              <th style={th}>impact</th>
              <th style={th}>forecast</th>
              <th style={th}>previous</th>
            </tr>
          </thead>
          <tbody>
            {past.map((e) => (
              <tr key={e.id}>
                <td style={td}>{fmtTs(e.ts)}</td>
                <td style={tdSym}>{e.country}</td>
                <td style={td}>{e.title}</td>
                <td style={{ ...td, color: IMPACT_COLOR[e.impact] }}>{e.impact}</td>
                <td style={td}>{e.forecast ?? '—'}</td>
                <td style={td}>{e.previous ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={h3}>Crypto news</h3>
      {news.length === 0 ? (
        <p style={{ color: '#8a93a6', fontSize: 13 }}>
          No news yet. Set <code>CRYPTOPANIC_TOKEN</code> to enable polling.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {news.map((n) => (
            <li
              key={n.id}
              style={{ borderBottom: '1px solid #1b2030', padding: '6px 0' }}
            >
              <div style={{ fontSize: 11, color: '#8a93a6' }}>
                {new Date(n.ts).toISOString().slice(0, 16).replace('T', ' ')}Z ·{' '}
                {n.domain ?? n.source}
                {n.sentiment && (
                  <span
                    style={{
                      marginLeft: 8,
                      color:
                        n.sentiment === 'positive'
                          ? '#26a69a'
                          : n.sentiment === 'negative'
                            ? '#ef5350'
                            : n.sentiment === 'important'
                              ? '#f7c948'
                              : '#8a93a6',
                    }}
                  >
                    {n.sentiment}
                  </span>
                )}
              </div>
              <a href={n.url} target="_blank" rel="noreferrer">
                {n.title}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const tbl: React.CSSProperties = { borderCollapse: 'collapse', width: '100%' };
const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  fontWeight: 600,
  fontSize: 12,
  color: '#8a93a6',
  borderBottom: '1px solid #2a3145',
};
const td: React.CSSProperties = {
  padding: '6px 10px',
  borderBottom: '1px solid #1b2030',
  fontSize: 13,
};
const tdSym: React.CSSProperties = { ...td, fontWeight: 600 };
const tdNum: React.CSSProperties = {
  ...td,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
};
const h3: React.CSSProperties = { fontSize: 14, color: '#d4d7dd', marginTop: 24, marginBottom: 8 };
const selStyle: React.CSSProperties = {
  background: '#0b0e14',
  color: '#d4d7dd',
  border: '1px solid #2a3145',
  borderRadius: 4,
  padding: '4px 8px',
  width: 200,
  fontSize: 13,
};
