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
