import { describe, expect, it } from 'vitest';
import { binanceCoinToSymbol, binanceSymbolToCoin } from './symbols.js';

describe('binanceCoinToSymbol', () => {
  it('appends USDT for plain coin tickers', () => {
    expect(binanceCoinToSymbol('BTC')).toBe('BTCUSDT');
    expect(binanceCoinToSymbol('eth')).toBe('ETHUSDT');
  });

  it('leaves full Binance symbols alone', () => {
    expect(binanceCoinToSymbol('BTCUSDT')).toBe('BTCUSDT');
    expect(binanceCoinToSymbol('btcusdt')).toBe('BTCUSDT');
    expect(binanceCoinToSymbol('SOLBUSD')).toBe('SOLBUSD');
  });
});

describe('binanceSymbolToCoin', () => {
  it('strips USDT', () => {
    expect(binanceSymbolToCoin('BTCUSDT')).toBe('BTC');
    expect(binanceSymbolToCoin('ethusdt')).toBe('ETH');
  });

  it('leaves non-USDT pairs unchanged', () => {
    expect(binanceSymbolToCoin('SOLBUSD')).toBe('SOLBUSD');
  });

  it('round-trips with binanceCoinToSymbol', () => {
    for (const coin of ['BTC', 'ETH', 'SOL', 'AVAX']) {
      expect(binanceSymbolToCoin(binanceCoinToSymbol(coin))).toBe(coin);
    }
  });
});
