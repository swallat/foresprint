import { language } from './i18n.svelte';

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
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(language(), { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1)));
}
