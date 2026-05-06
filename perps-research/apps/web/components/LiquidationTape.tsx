'use client';

import { useEffect, useMemo, useState } from 'react';

interface LiqRow {
  venue: string;
  symbol: string;
  ts: number;
  side: 'long' | 'short';
  size: number;
  price: number;
}

function notional(r: LiqRow): number {
  return r.size * r.price;
}

function fmtUsd(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return d.toISOString().slice(11, 19);
}

export function LiquidationTape() {
  const [rows, setRows] = useState<LiqRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch('/api/liquidations?limit=200', { cache: 'no-store' });
        if (!res.ok) throw new Error(`liquidations ${res.status}`);
        const json = (await res.json()) as { liquidations: LiqRow[] };
        if (cancelled) return;
        setRows(json.liquidations);
        setError(null);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void tick();
    const id = setInterval(tick, 2_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Group last 60s into buckets per side for the summary header.
  const summary = useMemo(() => {
    const cutoff = Date.now() - 60_000;
    let longs = 0;
    let shorts = 0;
    for (const r of rows) {
      if (r.ts < cutoff) continue;
      if (r.side === 'long') longs += notional(r);
      else shorts += notional(r);
    }
    return { longs, shorts };
  }, [rows]);

  if (loading) return <p style={{ color: '#8a93a6' }}>loading…</p>;
  if (error) return <p style={{ color: '#ef5350' }}>error: {error}</p>;

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 16,
          marginBottom: 12,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <div style={{ color: '#ef5350' }}>
          longs liq’d (60s): <strong>{fmtUsd(summary.longs)}</strong>
        </div>
        <div style={{ color: '#26a69a' }}>
          shorts liq’d (60s): <strong>{fmtUsd(summary.shorts)}</strong>
        </div>
        <div style={{ color: '#8a93a6' }}>{rows.length} recent rows</div>
      </div>
      {rows.length === 0 ? (
        <p style={{ color: '#8a93a6' }}>
          No liquidations yet — Binance forceOrder stream is sparse on quiet days.
        </p>
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              <th style={th}>time</th>
              <th style={th}>venue</th>
              <th style={th}>symbol</th>
              <th style={th}>side</th>
              <th style={{ ...th, textAlign: 'right' }}>size</th>
              <th style={{ ...th, textAlign: 'right' }}>price</th>
              <th style={{ ...th, textAlign: 'right' }}>notional</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={`${r.venue}-${r.symbol}-${r.ts}-${i}`}
                style={{
                  background: i < 3 ? '#11151c' : 'transparent',
                }}
              >
                <td style={td}>{fmtTime(r.ts)}</td>
                <td style={td}>{r.venue}</td>
                <td style={tdSym}>{r.symbol}</td>
                <td style={{ ...td, color: r.side === 'long' ? '#ef5350' : '#26a69a' }}>
                  {r.side}
                </td>
                <td style={tdNum}>
                  {r.size.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td style={tdNum}>
                  {r.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </td>
                <td style={tdNum}>{fmtUsd(notional(r))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

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
