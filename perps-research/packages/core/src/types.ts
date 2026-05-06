export type Venue = 'hyperliquid' | 'binance' | 'coinbase' | 'kraken';
export type Side = 'buy' | 'sell';
export type Timeframe = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

export interface Tick {
  venue: Venue;
  symbol: string;
  /** epoch milliseconds */
  ts: number;
  price: number;
  size: number;
  side: Side;
}

export interface Bar {
  venue: Venue;
  symbol: string;
  /** bar open time, epoch milliseconds */
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  tf: Timeframe;
}

export interface Funding {
  venue: Venue;
  symbol: string;
  ts: number;
  /** decimal rate (e.g. 0.0001 = 1bp) */
  rate: number;
  /** epoch ms of next scheduled funding */
  nextTs: number;
}

export interface OpenInterest {
  venue: Venue;
  symbol: string;
  ts: number;
  /** open interest in base units */
  oi: number;
}

export interface Liquidation {
  venue: Venue;
  symbol: string;
  ts: number;
  side: 'long' | 'short';
  size: number;
  price: number;
}

export interface Signal {
  ts: number;
  symbol: string;
  side: 'long' | 'short' | 'flat';
  /** -1..1, sign matches direction; magnitude is conviction */
  strength: number;
  reason: string;
}

export interface Order {
  id: string;
  ts: number;
  symbol: string;
  side: Side;
  type: 'mkt' | 'lmt';
  size: number;
  price?: number;
}

export interface Fill {
  orderId: string;
  ts: number;
  price: number;
  size: number;
  fee: number;
}

/**
 * Every venue adapter implements this. The adapter is responsible for
 * connection lifecycle, subscription messages, and normalizing payloads.
 */
export interface VenueAdapter {
  readonly venue: Venue;
  start(symbols: readonly string[]): Promise<void>;
  stop(): Promise<void>;
  onTick(handler: (tick: Tick) => void): void;
  /** optional streams; not all venues expose all of these */
  onFunding?(handler: (f: Funding) => void): void;
  onOpenInterest?(handler: (oi: OpenInterest) => void): void;
  onLiquidation?(handler: (l: Liquidation) => void): void;
}
