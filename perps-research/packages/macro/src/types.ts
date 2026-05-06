export type MacroImpact = 'Holiday' | 'Low' | 'Medium' | 'High';

export interface MacroEvent {
  /** stable id derived from title + country + ts */
  id: string;
  title: string;
  /** 3-letter currency code: USD, EUR, JPY, ... */
  country: string;
  /** epoch ms; null when the calendar entry has no specific time */
  ts: number | null;
  impact: MacroImpact;
  forecast: string | null;
  previous: string | null;
  actual: string | null;
  url: string | null;
  fetchedAt: number;
}

export interface NewsItem {
  id: string;
  source: string;
  ts: number;
  title: string;
  url: string;
  domain: string | null;
  /** "positive" | "negative" | "important" | "neutral" — provider-defined */
  sentiment: string | null;
  votesPos: number;
  votesNeg: number;
  fetchedAt: number;
}

export interface EventImpactRow {
  /** offset from event in minutes */
  offsetMin: number;
  /** number of (event, symbol) pairs that contributed */
  n: number;
  /** percentage returns from event time to event+offset */
  meanRet: number;
  medianRet: number;
  stdRet: number;
}

export interface EventImpactResult {
  title: string;
  venue: string;
  symbol: string;
  events: number;
  rows: EventImpactRow[];
}
