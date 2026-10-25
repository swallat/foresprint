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

/** A day with the year as numbers, e.g. "30.09.2026". */
export function formatDate(day: string): string {
  return new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', year: 'numeric' }).format(parseDay(day));
}

/** A period of days with the year on both ends, e.g. "30.09.2026 – 14.10.2026". */
export function formatPeriod(start: string, end: string): string {
  return `${formatDate(start)} – ${formatDate(end)}`;
}

type DayPart = 'day' | 'month' | 'year';

/** The order and separator in which the language writes a day with numbers: de "22.10.2026", en-US "10/22/2026". */
function dayLayout(): { order: DayPart[]; separator: string } {
  const parts = new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', year: 'numeric' }).formatToParts(new Date(2026, 9, 22));
  const order = parts.filter((p) => p.type === 'day' || p.type === 'month' || p.type === 'year').map((p) => p.type as DayPart);
  const separator = parts.find((p) => p.type === 'literal')?.value.trim() || '.';
  return { order, separator };
}

/** What to type for a day, in the form of the language: "DD.MM.YYYY" (shown as "TT.MM.JJJJ" in German). */
export function dayPlaceholder(names: { day: string; month: string; year: string }): string {
  const { order, separator } = dayLayout();
  return order.map((p) => names[p]).join(separator);
}

/** A day (YYYY-MM-DD) as typed in the language of the window, e.g. "20.10.2026". */
export function formatDayInput(day: string): string {
  return day ? formatDate(day) : '';
}

/** Reads a day typed in the form of the language ("20.10.2026") or as YYYY-MM-DD; returns YYYY-MM-DD, or '' if it is no day. */
export function parseDayInput(text: string): string {
  const clean = text.trim();
  let y: number, m: number, d: number;
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(clean);
  if (iso) {
    [y, m, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  } else {
    const parts = clean.split(/[^\d]+/).filter(Boolean);
    if (parts.length !== 3 || !/^\d+(\D+\d+){2}$/.test(clean)) return '';
    const { order } = dayLayout();
    const byPart: Record<DayPart, number> = { day: 0, month: 0, year: 0 };
    order.forEach((p, i) => (byPart[p] = Number(parts[i])));
    if (parts[order.indexOf('year')]!.length !== 4) return '';
    ({ day: d, month: m, year: y } = byPart);
  }
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${String(y).padStart(4, '0')}-${p(m)}-${p(d)}`;
}
