/**
 * Map between our canonical short symbols ("BTC", "ETH", "SOL") and the
 * USDⓈ-M Futures contract names Binance uses ("BTCUSDT", "ETHUSDT", etc.).
 *
 * For Phase 2 we restrict to USDT-margined linear perps, which is the venue
 * Binance Futures WS streams cover. Coin-margined perps (`@dapi`) are a
 * separate API surface and not modeled here.
 */

const QUOTE = 'USDT';

export function binanceCoinToSymbol(coin: string): string {
  const u = coin.toUpperCase();
  // Already a full Binance symbol? leave alone.
  if (u.endsWith(QUOTE) || u.endsWith('BUSD') || u.endsWith('USD')) {
    return u;
  }
  return `${u}${QUOTE}`;
}

export function binanceSymbolToCoin(symbol: string): string {
  const s = symbol.toUpperCase();
  if (s.endsWith(QUOTE)) return s.slice(0, -QUOTE.length);
  // `BUSD` etc — fall through unchanged.
  return s;
}
