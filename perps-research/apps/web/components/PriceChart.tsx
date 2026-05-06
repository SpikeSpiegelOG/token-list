'use client';

import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  LineSeries,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';
import { ema } from '@perps/indicators';

interface ApiCandles {
  venue: string;
  symbol: string;
  candles: Array<{
    ts: number;
    o: number;
    h: number;
    l: number;
    c: number;
    v: number;
  }>;
}

interface SseTick {
  ts: number;
  price: number;
  size: number;
  side: string;
}

const BAR_MS = 60_000; // 1m

function bucket(ts: number): UTCTimestamp {
  return (Math.floor(ts / BAR_MS) * BAR_MS / 1000) as UTCTimestamp;
}

export function PriceChart({
  venue,
  symbol,
}: {
  venue: string;
  symbol: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const lastBarRef = useRef<CandlestickData<UTCTimestamp> | null>(null);
  const emaRef = useRef(new ema(20));
  const [status, setStatus] = useState('connecting…');
  const [lastPrice, setLastPrice] = useState<number | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0e14' },
        textColor: '#d4d7dd',
      },
      grid: {
        vertLines: { color: '#1b2030' },
        horzLines: { color: '#1b2030' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a3145' },
      timeScale: { borderColor: '#2a3145', timeVisible: true, secondsVisible: false },
      autoSize: true,
    });
    chartRef.current = chart;
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
    emaSeriesRef.current = chart.addSeries(LineSeries, {
      color: '#f7c948',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: 'EMA20',
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      emaSeriesRef.current = null;
    };
  }, []);

  // 1) Hydrate from /api/candles
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/candles?venue=${venue}&symbol=${symbol}&limit=500`,
          { cache: 'no-store' },
        );
        if (!res.ok) throw new Error(`candles ${res.status}`);
        const json = (await res.json()) as ApiCandles;
        if (cancelled) return;
        const candles: CandlestickData<UTCTimestamp>[] = json.candles.map(
          (c) => ({
            time: (c.ts / 1000) as UTCTimestamp,
            open: c.o,
            high: c.h,
            low: c.l,
            close: c.c,
          }),
        );
        candleSeriesRef.current?.setData(candles);

        // Seed EMA from history
        emaRef.current.reset();
        const emaPoints: LineData<UTCTimestamp>[] = candles.map((c) => ({
          time: c.time,
          value: emaRef.current.update(c.close),
        }));
        emaSeriesRef.current?.setData(emaPoints);

        lastBarRef.current = candles[candles.length - 1] ?? null;
        if (lastBarRef.current) setLastPrice(lastBarRef.current.close);
        setStatus(candles.length > 0 ? 'live' : 'waiting for ticks…');
      } catch (err) {
        setStatus(`error: ${(err as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [venue, symbol]);

  // 2) Subscribe to SSE tick stream
  useEffect(() => {
    const es = new EventSource(`/api/stream/${symbol}?venue=${venue}`);
    es.addEventListener('hello', () => setStatus('live'));
    es.addEventListener('error', () => setStatus('reconnecting…'));
    es.addEventListener('tick', (evt) => {
      const t = JSON.parse((evt as MessageEvent).data) as SseTick;
      const time = bucket(t.ts);
      const last = lastBarRef.current;
      let bar: CandlestickData<UTCTimestamp>;
      if (!last || last.time !== time) {
        bar = {
          time,
          open: t.price,
          high: t.price,
          low: t.price,
          close: t.price,
        };
      } else {
        bar = {
          time,
          open: last.open,
          high: Math.max(last.high, t.price),
          low: Math.min(last.low, t.price),
          close: t.price,
        };
      }
      lastBarRef.current = bar;
      candleSeriesRef.current?.update(bar);

      const emaVal = emaRef.current.update(t.price);
      emaSeriesRef.current?.update({ time, value: emaVal });
      setLastPrice(t.price);
    });
    return () => es.close();
  }, [venue, symbol]);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'baseline',
          fontSize: 12,
          color: '#8a93a6',
          marginBottom: 8,
        }}
      >
        <span>status: {status}</span>
        {lastPrice !== null && (
          <span style={{ color: '#d4d7dd' }}>
            last: {lastPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </span>
        )}
      </div>
      <div
        ref={containerRef}
        style={{
          width: '100%',
          height: 'calc(100vh - 110px)',
          minHeight: 400,
        }}
      />
    </div>
  );
}
