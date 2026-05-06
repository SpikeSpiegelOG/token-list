'use client';

import {
  AreaSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';

interface Status {
  running: boolean;
  hint?: string;
  status?: {
    runId: string;
    venue: string;
    symbol: string;
    strategy: string;
    strategyId: string;
    startedAt: number;
    lastBarTs: number | null;
    equity: number;
    initialCash: number;
    position: number;
    avgEntry: number;
    bars: number;
    fills: number;
  };
}

interface EquityRow {
  ts: number;
  equity: number;
  position: number;
}

interface FillRow {
  ts: number;
  side: string;
  price: number;
  size: number;
  fee: number;
  reason: string;
}

function fmtPct(x: number, digits = 2): string {
  const sign = x > 0 ? '+' : '';
  return `${sign}${(x * 100).toFixed(digits)}%`;
}

function fmtNum(x: number, digits = 2): string {
  return x.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtTs(ms: number): string {
  return new Date(ms).toISOString().slice(5, 19).replace('T', ' ');
}

export function PaperPanel() {
  const [runId, setRunId] = useState('default');
  const [status, setStatus] = useState<Status | null>(null);
  const [equity, setEquity] = useState<EquityRow[]>([]);
  const [fills, setFills] = useState<FillRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Build chart once.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0e14' },
        textColor: '#d4d7dd',
      },
      grid: {
        vertLines: { color: '#1b2030' },
        horzLines: { color: '#1b2030' },
      },
      timeScale: {
        borderColor: '#2a3145',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: '#2a3145' },
      autoSize: true,
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: '#4cc2ff',
      topColor: 'rgba(76,194,255,0.30)',
      bottomColor: 'rgba(76,194,255,0.05)',
      lineWidth: 2,
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Poll status + equity + fills.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [sRes, eRes, fRes] = await Promise.all([
          fetch('/api/paper/status', { cache: 'no-store' }),
          fetch(`/api/paper/equity?runId=${encodeURIComponent(runId)}&limit=2000`, { cache: 'no-store' }),
          fetch(`/api/paper/fills?runId=${encodeURIComponent(runId)}&limit=20`, { cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (sRes.ok) {
          setStatus((await sRes.json()) as Status);
        }
        if (eRes.ok) {
          const j = (await eRes.json()) as { equity: EquityRow[] };
          setEquity(j.equity);
        }
        if (fRes.ok) {
          const j = (await fRes.json()) as { fills: FillRow[] };
          setFills(j.fills);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void tick();
    const id = setInterval(tick, 5_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId]);

  // Update chart when equity changes.
  useEffect(() => {
    if (!seriesRef.current) return;
    seriesRef.current.setData(
      equity.map((p) => ({
        time: (p.ts / 1000) as UTCTimestamp,
        value: p.equity,
      })),
    );
  }, [equity]);

  if (!status) return <p style={{ color: '#8a93a6' }}>loading…</p>;

  if (!status.running) {
    return (
      <div>
        <p style={{ color: '#8a93a6' }}>
          Paper trader is not running. {status.hint}
        </p>
        <pre
          style={{
            background: '#11151c',
            border: '1px solid #2a3145',
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflowX: 'auto',
          }}
        >
{`# Example startup config
PERPS_PAPER_STRATEGY=momentum-breakout \\
PERPS_PAPER_SYMBOL=BTC \\
PERPS_PAPER_PARAMS='{"lookback":20,"minVolPct":0.0005}' \\
PERPS_PAPER_INITIAL_CASH=10000 \\
PERPS_PAPER_SIZE=0.05 \\
pnpm start`}
        </pre>
      </div>
    );
  }

  const s = status.status!;
  const totalReturn = s.initialCash > 0 ? s.equity / s.initialCash - 1 : 0;
  const positionLabel =
    s.position === 0
      ? 'flat'
      : s.position > 0
        ? `long ${s.position.toFixed(4)} @ ${s.avgEntry.toFixed(2)}`
        : `short ${(-s.position).toFixed(4)} @ ${s.avgEntry.toFixed(2)}`;

  return (
    <div>
      {error && (
        <p style={{ color: '#ef5350', fontSize: 13 }}>error: {error}</p>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 8,
          marginBottom: 16,
        }}
      >
        <Card label="Run ID">
          <input
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            style={{
              background: '#0b0e14',
              color: '#d4d7dd',
              border: '1px solid #2a3145',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
              width: '100%',
            }}
          />
        </Card>
        <Card label="Strategy">{s.strategy}</Card>
        <Card label="Market">{`${s.venue} · ${s.symbol}`}</Card>
        <Card
          label="Equity"
          color={totalReturn >= 0 ? '#26a69a' : '#ef5350'}
        >
          {`$${fmtNum(s.equity)} (${fmtPct(totalReturn)})`}
        </Card>
        <Card label="Position">{positionLabel}</Card>
        <Card label="Bars / fills">{`${s.bars} / ${s.fills}`}</Card>
        <Card label="Last bar">
          {s.lastBarTs ? fmtTs(s.lastBarTs) : '—'}
        </Card>
        <Card label="Started">{fmtTs(s.startedAt)}</Card>
      </div>

      <div
        ref={containerRef}
        style={{ width: '100%', height: 320, minHeight: 220 }}
      />

      <h3 style={h3}>Recent fills</h3>
      {fills.length === 0 ? (
        <p style={{ color: '#8a93a6', fontSize: 13 }}>No fills yet.</p>
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              <th style={th}>time</th>
              <th style={th}>side</th>
              <th style={{ ...th, textAlign: 'right' }}>price</th>
              <th style={{ ...th, textAlign: 'right' }}>size</th>
              <th style={{ ...th, textAlign: 'right' }}>fee</th>
              <th style={th}>reason</th>
            </tr>
          </thead>
          <tbody>
            {fills.map((f, i) => (
              <tr key={`${f.ts}-${i}`}>
                <td style={td}>{fmtTs(f.ts)}</td>
                <td
                  style={{ ...td, color: f.side === 'buy' ? '#26a69a' : '#ef5350' }}
                >
                  {f.side}
                </td>
                <td style={tdNum}>{fmtNum(f.price, 2)}</td>
                <td style={tdNum}>{fmtNum(f.size, 4)}</td>
                <td style={tdNum}>{fmtNum(f.fee, 4)}</td>
                <td style={{ ...td, color: '#8a93a6' }}>{f.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Card({
  label,
  children,
  color,
}: {
  label: string;
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <div
      style={{
        background: '#11151c',
        border: '1px solid #2a3145',
        padding: '8px 12px',
        borderRadius: 4,
      }}
    >
      <div style={{ fontSize: 11, color: '#8a93a6' }}>{label}</div>
      <div
        style={{
          fontSize: 14,
          fontVariantNumeric: 'tabular-nums',
          color: color ?? '#d4d7dd',
          marginTop: 2,
        }}
      >
        {children}
      </div>
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
const tdNum: React.CSSProperties = {
  ...td,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
};
const h3: React.CSSProperties = {
  fontSize: 14,
  color: '#d4d7dd',
  marginTop: 24,
  marginBottom: 8,
};
