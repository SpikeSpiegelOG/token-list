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

interface StrategyParam {
  name: string;
  default: number;
  min?: number;
  max?: number;
}

interface StrategyMeta {
  id: string;
  label: string;
  params: StrategyParam[];
}

interface EquityPoint {
  ts: number;
  equity: number;
  position: number;
}

interface TradeRecord {
  openTs: number;
  closeTs: number;
  side: 'long' | 'short';
  entry: number;
  exit: number;
  size: number;
  pnl: number;
  ret: number;
  reason?: string;
}

interface Metrics {
  finalEquity: number;
  totalReturn: number;
  sharpe: number;
  sortino: number;
  maxDrawdown: number;
  winRate: number;
  expectancy: number;
  trades: number;
  exposure: number;
}

interface BacktestResult {
  equity: EquityPoint[];
  trades: TradeRecord[];
  metrics: Metrics;
  strategy: string;
  startTs: number;
  endTs: number;
}

const SYMBOLS = ['BTC', 'ETH', 'SOL'];

function fmtPct(x: number, digits = 2): string {
  return `${(x * 100).toFixed(digits)}%`;
}

function fmtNum(x: number, digits = 2): string {
  return x.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtTs(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19);
}

export function BacktestPanel() {
  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);
  const [strategyId, setStrategyId] = useState<string>('momentum-breakout');
  const [params, setParams] = useState<Record<string, number>>({});
  const [symbol, setSymbol] = useState<string>('BTC');
  const [hours, setHours] = useState<number>(24);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const equitySeriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  // Load strategy metadata once.
  useEffect(() => {
    void fetch('/api/backtest', { cache: 'no-store' })
      .then((r) => r.json())
      .then((j: { strategies: StrategyMeta[] }) => {
        setStrategies(j.strategies);
      });
  }, []);

  // Reset params when strategy changes.
  useEffect(() => {
    const s = strategies.find((x) => x.id === strategyId);
    if (!s) return;
    const next: Record<string, number> = {};
    for (const p of s.params) next[p.name] = p.default;
    setParams(next);
  }, [strategyId, strategies]);

  // Build the chart once.
  useEffect(() => {
    const el = chartContainerRef.current;
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
    equitySeriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: '#4cc2ff',
      topColor: 'rgba(76,194,255,0.30)',
      bottomColor: 'rgba(76,194,255,0.05)',
      lineWidth: 2,
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      equitySeriesRef.current = null;
    };
  }, []);

  // Re-paint equity curve when result changes.
  useEffect(() => {
    if (!result || !equitySeriesRef.current) return;
    equitySeriesRef.current.setData(
      result.equity.map((p) => ({
        time: (p.ts / 1000) as UTCTimestamp,
        value: p.equity,
      })),
    );
  }, [result]);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const endTs = Date.now();
      const startTs = endTs - hours * 60 * 60_000;
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy: strategyId,
          params,
          venue: 'hyperliquid',
          symbol,
          startTs,
          endTs,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json.error ?? `HTTP ${res.status}`);
      }
      setResult(json.result as BacktestResult);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const stratMeta = strategies.find((s) => s.id === strategyId);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 12,
          alignItems: 'flex-end',
          padding: 12,
          border: '1px solid #2a3145',
          borderRadius: 6,
          marginBottom: 16,
          background: '#11151c',
        }}
      >
        <Field label="Strategy">
          <select
            value={strategyId}
            onChange={(e) => setStrategyId(e.target.value)}
            style={selStyle}
          >
            {strategies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Symbol">
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            style={selStyle}
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Hours back">
          <input
            type="number"
            min={1}
            max={720}
            value={hours}
            onChange={(e) => setHours(Math.max(1, Number(e.target.value) || 1))}
            style={inpStyle}
          />
        </Field>
        {stratMeta?.params.map((p) => (
          <Field key={p.name} label={p.name}>
            <input
              type="number"
              step="any"
              min={p.min}
              max={p.max}
              value={params[p.name] ?? p.default}
              onChange={(e) =>
                setParams((s) => ({
                  ...s,
                  [p.name]: Number(e.target.value),
                }))
              }
              style={inpStyle}
            />
          </Field>
        ))}
        <button onClick={run} disabled={running} aria-pressed={running}>
          {running ? 'running…' : 'run backtest'}
        </button>
      </div>

      {error && (
        <p style={{ color: '#ef5350', fontSize: 13 }}>error: {error}</p>
      )}

      <div
        ref={chartContainerRef}
        style={{ width: '100%', height: 320, minHeight: 220 }}
      />

      {result && (
        <>
          <MetricsRow m={result.metrics} />
          <TradesTable trades={result.trades.slice(-20).reverse()} />
        </>
      )}
    </div>
  );
}

function MetricsRow({ m }: { m: Metrics }) {
  const cells: Array<[string, string, string?]> = [
    ['Total return', fmtPct(m.totalReturn), m.totalReturn >= 0 ? '#26a69a' : '#ef5350'],
    ['Sharpe', fmtNum(m.sharpe, 2)],
    ['Sortino', fmtNum(m.sortino, 2)],
    ['Max DD', fmtPct(m.maxDrawdown), '#ef5350'],
    ['Win rate', fmtPct(m.winRate)],
    ['Trades', String(m.trades)],
    ['Expectancy', `$${fmtNum(m.expectancy)}`],
    ['Exposure', fmtPct(m.exposure)],
    ['Final equity', `$${fmtNum(m.finalEquity)}`],
  ];
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: 8,
        marginTop: 12,
      }}
    >
      {cells.map(([label, val, color]) => (
        <div
          key={label}
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
              fontSize: 16,
              fontVariantNumeric: 'tabular-nums',
              color: color ?? '#d4d7dd',
            }}
          >
            {val}
          </div>
        </div>
      ))}
    </div>
  );
}

function TradesTable({ trades }: { trades: TradeRecord[] }) {
  if (trades.length === 0) {
    return (
      <p style={{ color: '#8a93a6', marginTop: 12 }}>
        No closed trades in this run.
      </p>
    );
  }
  return (
    <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: 12 }}>
      <thead>
        <tr>
          {['open', 'close', 'side', 'entry', 'exit', 'size', 'pnl', 'reason'].map((h) => (
            <th key={h} style={th}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i}>
            <td style={td}>{fmtTs(t.openTs)}</td>
            <td style={td}>{fmtTs(t.closeTs)}</td>
            <td
              style={{ ...td, color: t.side === 'long' ? '#26a69a' : '#ef5350' }}
            >
              {t.side}
            </td>
            <td style={tdNum}>{fmtNum(t.entry, 2)}</td>
            <td style={tdNum}>{fmtNum(t.exit, 2)}</td>
            <td style={tdNum}>{fmtNum(t.size, 4)}</td>
            <td style={{ ...tdNum, color: t.pnl >= 0 ? '#26a69a' : '#ef5350' }}>
              {fmtNum(t.pnl, 2)}
            </td>
            <td style={{ ...td, color: '#8a93a6' }}>{t.reason ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#8a93a6' }}>{label}</span>
      {children}
    </label>
  );
}

const inpStyle: React.CSSProperties = {
  background: '#0b0e14',
  color: '#d4d7dd',
  border: '1px solid #2a3145',
  borderRadius: 4,
  padding: '4px 8px',
  width: 120,
  fontSize: 13,
};
const selStyle: React.CSSProperties = { ...inpStyle, width: 280 };
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
