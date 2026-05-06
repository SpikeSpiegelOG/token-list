export { fetchEconomicCalendar } from './forexfactory.js';
export { fetchCryptoNews } from './cryptopanic.js';
export { computeEventImpact } from './correlate.js';
export { startMacroFetchers } from './scheduler.js';
export type {
  MacroEvent,
  NewsItem,
  EventImpactRow,
  EventImpactResult,
} from './types.js';
