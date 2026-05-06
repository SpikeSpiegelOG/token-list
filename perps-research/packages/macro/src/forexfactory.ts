import { createHash } from 'node:crypto';
import type { MacroEvent, MacroImpact } from './types.js';

const DEFAULT_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.xml';

const EVENT_TAGS = [
  'title',
  'country',
  'date',
  'time',
  'impact',
  'forecast',
  'previous',
  'url',
] as const;

type RawEvent = Partial<Record<(typeof EVENT_TAGS)[number], string>>;

/**
 * Forex Factory ships a weekly XML calendar with no auth, refreshed nightly.
 * Format details:
 *   - root: <weeklyevents>
 *   - per item: <event> with <title>, <country>, <date> (MM-DD-YYYY),
 *     <time> ("9:30am" | "All Day" | "Tentative"), <impact>, <forecast>,
 *     <previous>, <url>.
 *   - empty fields appear as self-closing `<forecast />`.
 *   - text fields use CDATA.
 *
 * The XML is small (~50KB / week) and well-formed for our purposes; we
 * parse with regex rather than pulling in a dep. If the format changes
 * unexpectedly we fail closed (return []).
 */
export async function fetchEconomicCalendar(opts: {
  url?: string;
  signal?: AbortSignal;
} = {}): Promise<MacroEvent[]> {
  const url = opts.url ?? DEFAULT_URL;
  const res = await fetch(url, {
    headers: {
      // Some CDNs reject the default Node UA.
      'user-agent': 'perps-research/0.1 (+research)',
      accept: 'application/xml,text/xml',
    },
    signal: opts.signal,
  });
  if (!res.ok) {
    throw new Error(`forexfactory ${url} → HTTP ${res.status}`);
  }
  const xml = await res.text();
  return parseCalendarXml(xml);
}

export function parseCalendarXml(xml: string): MacroEvent[] {
  const events: MacroEvent[] = [];
  const fetchedAt = Date.now();

  // Iterate <event>...</event> blocks. The format is shallow (no nested
  // <event>), so a non-greedy regex is safe.
  const blockRe = /<event>([\s\S]*?)<\/event>/g;
  let m: RegExpExecArray | null;
  while ((m = blockRe.exec(xml)) !== null) {
    const body = m[1]!;
    const raw: RawEvent = {};
    for (const tag of EVENT_TAGS) {
      raw[tag] = extractTag(body, tag);
    }
    const ev = normalizeEvent(raw, fetchedAt);
    if (ev) events.push(ev);
  }
  return events;
}

function extractTag(body: string, tag: string): string | undefined {
  // Match either <tag>value</tag> or <tag><![CDATA[value]]></tag>
  // or self-closing <tag/>.
  const re = new RegExp(
    `<${tag}>(?:<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>|([\\s\\S]*?))</${tag}>|<${tag}\\s*/>`,
    'i',
  );
  const m = body.match(re);
  if (!m) return undefined;
  const v = (m[1] ?? m[2] ?? '').trim();
  return v.length > 0 ? v : undefined;
}

function normalizeEvent(
  raw: RawEvent,
  fetchedAt: number,
): MacroEvent | null {
  if (!raw.title || !raw.country || !raw.date) return null;
  const impact = normalizeImpact(raw.impact);
  const ts = parseEventTs(raw.date, raw.time);
  const id = stableId(raw.title, raw.country, ts ?? 0);
  return {
    id,
    title: raw.title,
    country: raw.country.toUpperCase(),
    ts,
    impact,
    forecast: raw.forecast ?? null,
    previous: raw.previous ?? null,
    actual: null,
    url: raw.url ?? null,
    fetchedAt,
  };
}

function normalizeImpact(s: string | undefined): MacroImpact {
  switch ((s ?? '').toLowerCase()) {
    case 'high':
      return 'High';
    case 'medium':
      return 'Medium';
    case 'low':
      return 'Low';
    case 'holiday':
    default:
      return 'Holiday';
  }
}

/**
 * `date` is MM-DD-YYYY; `time` is "9:30am" / "11:00pm" / "All Day" /
 * "Tentative" / undefined. ForexFactory publishes US/Eastern; we treat
 * unanchored datetimes as ET and convert to UTC ms.
 *
 * Returns null if no precise timestamp can be derived (Tentative / All Day
 * / missing time).
 */
export function parseEventTs(
  date: string,
  time: string | undefined,
): number | null {
  if (!time || time.toLowerCase() === 'all day' || time.toLowerCase() === 'tentative') {
    return null;
  }
  const d = date.split('-');
  if (d.length !== 3) return null;
  const [mm, dd, yyyy] = d;
  if (!mm || !dd || !yyyy) return null;

  const tm = time.match(/^(\d{1,2}):(\d{2})\s*(am|pm)$/i);
  if (!tm) return null;
  let hour = parseInt(tm[1]!, 10);
  const minute = parseInt(tm[2]!, 10);
  const ampm = tm[3]!.toLowerCase();
  if (ampm === 'pm' && hour !== 12) hour += 12;
  if (ampm === 'am' && hour === 12) hour = 0;

  // Build a UTC date as if ET, then offset back. ET is UTC-5 (EST) or
  // UTC-4 (EDT). We'd need TZ data to be exact; for v1, use EST and let
  // the caller treat ts as ±1h fuzzy. (Phase 4.5: pull tz from `Intl`.)
  const utcMs = Date.UTC(
    parseInt(yyyy, 10),
    parseInt(mm, 10) - 1,
    parseInt(dd, 10),
    hour + 5, // ET → UTC, EST baseline
    minute,
  );
  return utcMs;
}

function stableId(title: string, country: string, ts: number): string {
  return createHash('sha256')
    .update(`${title}|${country}|${ts}`)
    .digest('hex')
    .slice(0, 16);
}
