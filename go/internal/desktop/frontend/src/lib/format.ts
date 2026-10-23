// Formatting of dates and counts for the current language.

import { language } from './i18n.svelte';

/** "2026-10-22" as a local date, without a time zone shift. */
export function parseDay(day: string): Date {
  const [y = 1970, m = 1, d = 1] = day.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** A day as the user's language writes it, e.g. "22 Oct 2026" or "22. Okt. 2026". */
export function formatDay(day: string, style: 'long' | 'short' = 'short'): string {
  const d = parseDay(day);
  return new Intl.DateTimeFormat(language(), style === 'long' ? { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' } : { day: 'numeric', month: 'short' }).format(d);
}

/** A number in the language of the window; `digits` is the largest number of decimals shown. */
export function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return new Intl.NumberFormat(language(), { maximumFractionDigits: digits }).format(value);
}

/** A share (0.8) as "80 %". */
export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '–';
  return `${fmt(value * 100, digits)} %`;
}

/** "2026-01-05" as a short date in the language of the window ("5 Jan" / "5. Jan."). */
export function shortDate(iso: string): string {
  return formatDay(iso, 'short');
}

/** A period of days with the year on both ends, e.g. "30.09.2026 – 14.10.2026". */
export function formatPeriod(start: string, end: string): string {
  const f = new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', year: 'numeric' });
  return `${f.format(parseDay(start))} – ${f.format(parseDay(end))}`;
}
