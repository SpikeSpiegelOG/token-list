'use client';

import { useEffect, useState } from 'react';

interface FundingRow {
  venue: string;
  symbol: string;
  ts: number;
  rate: number;
  nextTs: number;
}

interface OiRow {
  venue: string;
  symbol: string;
  ts: number;
  oi: number;
}

const VENUES = ['hyperliquid', 'binance'];

function colorFor(rate: number): string {
  // Annualized rate sign: + green long-pays-short, - red short-pays-long.
  // Saturate at |rate| = 0.0005 per funding interval (≈0.5% daily Binance).
  const cap = 0.0005;
  const t = Math.max(-1, Math.min(1, rate / cap));
  if (t >= 0) {
    const a = Math.round(40 + t * 60); // 40..100
    return `rgba(38,166,154,${(a / 100).toFixed(2)})`;
  }
  const a = Math.round(40 + -t * 60);
  return `rgba(239,83,80,${(a / 100).toFixed(2)})`;
}

function annualize(rate: number, intervalHours: number): number {
  const periodsPerYear = (365 * 24) / intervalHours;
  return rate * periodsPerYear;
}

function fmtPct(x: number, digits = 4): string {
  return `${(x * 100).toFixed(digits)}%`;
}

export function FundingTable() {
  const [funding, setFunding] = useState<FundingRow[]>([]);
  const [oi, setOi] = useState<OiRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [fRes, oRes] = await Promise.all([
          fetch('/api/funding', { cache: 'no-store' }),
          fetch('/api/oi', { cache: 'no-store' }),
        ]);
        if (!fRes.ok) throw new Error(`funding ${fRes.status}`);
        if (!oRes.ok) throw new Error(`oi ${oRes.status}`);
        const f = (await fRes.json()) as { funding: FundingRow[] };
        const o = (await oRes.json()) as { openInterest: OiRow[] };
        if (cancelled) return;
        setFunding(f.funding);
        setOi(o.openInterest);
        setError(null);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void tick();
    const id = setInterval(tick, 5_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Pivot: rows = symbols, columns = venues
  const symbols = Array.from(new Set(funding.map((f) => f.symbol))).sort();
  const byKey = new Map(funding.map((f) => [`${f.venue}:${f.symbol}`, f] as const));
  const oiByKey = new Map(oi.map((o) => [`${o.venue}:${o.symbol}`, o] as const));

  if (loading) return <p style={{ color: '#8a93a6' }}>loading…</p>;
  if (error) return <p style={{ color: '#ef5350' }}>error: {error}</p>;
  if (symbols.length === 0) {
    return (
      <p style={{ color: '#8a93a6' }}>
        No funding data yet — wait ~30s for activeAssetCtx / markPrice streams to push.
      </p>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: 14, color: '#d4d7dd', marginBottom: 6 }}>
        Funding rate (per 8h on Binance, per 1h on Hyperliquid; APR shown beside)
      </h3>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={th}>Symbol</th>
            {VENUES.map((v) => (
              <th key={v} style={th}>
                {v}
              </th>
            ))}
            {VENUES.map((v) => (
              <th key={`oi-${v}`} style={th}>
                {v} OI
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((s) => (
            <tr key={s}>
              <td style={tdSymbol}>{s}</td>
              {VENUES.map((v) => {
                const row = byKey.get(`${v}:${s}`);
                if (!row) return <td key={v} style={tdEmpty}>—</td>;
                const interval = v === 'hyperliquid' ? 1 : 8;
                return (
                  <td
                    key={v}
                    style={{ ...td, background: colorFor(row.rate) }}
                    title={`next funding: ${new Date(row.nextTs).toISOString()}`}
                  >
                    <div style={{ fontWeight: 600 }}>{fmtPct(row.rate)}</div>
                    <div style={{ fontSize: 11, color: '#8a93a6' }}>
                      APR ~{fmtPct(annualize(row.rate, interval), 1)}
                    </div>
                  </td>
                );
              })}
              {VENUES.map((v) => {
                const row = oiByKey.get(`${v}:${s}`);
                if (!row)
                  return <td key={`oi-${v}`} style={tdEmpty}>—</td>;
                return (
                  <td key={`oi-${v}`} style={td}>
                    {row.oi.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
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
  padding: '8px 10px',
  borderBottom: '1px solid #1b2030',
  fontVariantNumeric: 'tabular-nums',
  fontSize: 13,
};
const tdSymbol: React.CSSProperties = {
  ...td,
  fontWeight: 600,
};
const tdEmpty: React.CSSProperties = {
  ...td,
  color: '#4a5266',
};
