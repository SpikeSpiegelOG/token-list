import { describe, expect, it } from 'vitest';
import { parseCalendarXml, parseEventTs } from './forexfactory.js';

const SAMPLE = `<?xml version="1.0"?>
<weeklyevents>
  <event>
    <title><![CDATA[CPI y/y]]></title>
    <country><![CDATA[USD]]></country>
    <date><![CDATA[05-13-2026]]></date>
    <time><![CDATA[8:30am]]></time>
    <impact><![CDATA[High]]></impact>
    <forecast><![CDATA[3.1%]]></forecast>
    <previous><![CDATA[3.2%]]></previous>
    <url><![CDATA[https://example.test/cpi]]></url>
  </event>
  <event>
    <title>Bank Holiday</title>
    <country>JPY</country>
    <date>05-04-2026</date>
    <time>All Day</time>
    <impact>Holiday</impact>
    <forecast />
    <previous />
    <url />
  </event>
  <event>
    <title>FOMC Statement</title>
    <country>USD</country>
    <date>05-06-2026</date>
    <time>2:00pm</time>
    <impact>High</impact>
    <forecast />
    <previous />
    <url />
  </event>
</weeklyevents>
`;

describe('parseCalendarXml', () => {
  it('extracts events from CDATA + plain tags', () => {
    const evs = parseCalendarXml(SAMPLE);
    expect(evs).toHaveLength(3);

    const cpi = evs[0]!;
    expect(cpi.title).toBe('CPI y/y');
    expect(cpi.country).toBe('USD');
    expect(cpi.impact).toBe('High');
    expect(cpi.forecast).toBe('3.1%');
    expect(cpi.previous).toBe('3.2%');
    expect(cpi.url).toBe('https://example.test/cpi');
    // 8:30am ET on 2026-05-13 → 13:30 UTC (using EST baseline)
    expect(cpi.ts).toBe(Date.UTC(2026, 4, 13, 13, 30));

    const holiday = evs[1]!;
    expect(holiday.impact).toBe('Holiday');
    expect(holiday.ts).toBeNull();
    expect(holiday.forecast).toBeNull();

    const fomc = evs[2]!;
    expect(fomc.title).toBe('FOMC Statement');
    expect(fomc.ts).toBe(Date.UTC(2026, 4, 6, 19, 0));
  });

  it('produces stable ids for the same input', () => {
    const a = parseCalendarXml(SAMPLE)[0]!.id;
    const b = parseCalendarXml(SAMPLE)[0]!.id;
    expect(a).toBe(b);
    expect(a).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe('parseEventTs', () => {
  it('returns null for All Day / Tentative', () => {
    expect(parseEventTs('05-04-2026', 'All Day')).toBeNull();
    expect(parseEventTs('05-04-2026', 'Tentative')).toBeNull();
    expect(parseEventTs('05-04-2026', undefined)).toBeNull();
  });

  it('handles 12-hour edge cases', () => {
    // 12:00am = midnight; 12:00pm = noon
    expect(parseEventTs('05-04-2026', '12:00am')).toBe(
      Date.UTC(2026, 4, 4, 5, 0),
    );
    expect(parseEventTs('05-04-2026', '12:00pm')).toBe(
      Date.UTC(2026, 4, 4, 17, 0),
    );
  });
});
