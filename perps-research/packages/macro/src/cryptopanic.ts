import { createHash } from 'node:crypto';
import type { NewsItem } from './types.js';

const DEFAULT_URL = 'https://cryptopanic.com/api/v1/posts/';

interface CpPost {
  id: number;
  kind?: string;
  domain?: string;
  title: string;
  published_at: string;
  url: string;
  source?: { domain?: string; title?: string };
  votes?: {
    negative?: number;
    positive?: number;
    important?: number;
  };
  metadata?: { description?: string };
}

interface CpResponse {
  results?: CpPost[];
}

/**
 * CryptoPanic free tier: requires `auth_token`, returns aggregated crypto
 * news. We treat it as best-effort: if no token, return []. If the
 * endpoint changes shape we log and return what we got so far.
 *
 * Public-tier rate limit is per-minute; the scheduler polls every 5m.
 */
export async function fetchCryptoNews(opts: {
  token?: string;
  baseUrl?: string;
  filter?: 'rising' | 'hot' | 'bullish' | 'bearish' | 'important';
  signal?: AbortSignal;
}): Promise<NewsItem[]> {
  const token = opts.token ?? process.env.CRYPTOPANIC_TOKEN;
  if (!token) return [];
  const params = new URLSearchParams({
    auth_token: token,
    public: 'true',
  });
  if (opts.filter) params.set('filter', opts.filter);
  const url = `${opts.baseUrl ?? DEFAULT_URL}?${params}`;

  const res = await fetch(url, {
    headers: { accept: 'application/json' },
    signal: opts.signal,
  });
  if (!res.ok) {
    throw new Error(`cryptopanic → HTTP ${res.status}`);
  }
  const json = (await res.json()) as CpResponse;
  if (!Array.isArray(json.results)) return [];

  const fetchedAt = Date.now();
  const items: NewsItem[] = [];
  for (const post of json.results) {
    const ts = Date.parse(post.published_at);
    if (!Number.isFinite(ts)) continue;
    const sentiment = inferSentiment(post);
    items.push({
      id: stableNewsId(post.url || String(post.id)),
      source: 'cryptopanic',
      ts,
      title: post.title,
      url: post.url,
      domain: post.source?.domain ?? post.domain ?? null,
      sentiment,
      votesPos: post.votes?.positive ?? 0,
      votesNeg: post.votes?.negative ?? 0,
      fetchedAt,
    });
  }
  return items;
}

function inferSentiment(post: CpPost): string | null {
  const v = post.votes ?? {};
  if ((v.important ?? 0) > 0) return 'important';
  if ((v.positive ?? 0) > (v.negative ?? 0)) return 'positive';
  if ((v.negative ?? 0) > (v.positive ?? 0)) return 'negative';
  return null;
}

function stableNewsId(seed: string): string {
  return createHash('sha256').update(seed).digest('hex').slice(0, 16);
}
