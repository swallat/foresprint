// Number and date formats of the projects pages, in the language of the window.

import { planDigits } from '../../lib/digits.svelte';
import { language } from '../../lib/i18n.svelte';

/** A number with at most `digits` decimals in the language's format (1,5 or 1.5); by default the team's
 * rounding, at least one decimal (person days and estimates are not whole numbers). */
export function num(value: number | null | undefined, digits: number = Math.max(1, planDigits())): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return new Intl.NumberFormat(language(), { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

/** A rate (points per person day) with enough decimals to reproduce the calculation. */
export function rateNum(value: number | null | undefined): string {
  return num(value, 4);
}

/** 2026-11-20 as 20.11.2026 (de) or 20/11/2026 (en). */
export function date(iso: string): string {
  if (!iso) return '–';
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }).format(
    new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1)),
  );
}

/** 2026-11 as Nov 2026. */
export function month(ym: string): string {
  const [y, m] = ym.split('-').map(Number);
  return new Intl.DateTimeFormat(language(), { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(
    new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, 1)),
  );
}

/** Colour of a product in chips and on the timeline: the chart series, repeated for more. */
const SERIES = ['var(--c-vel)', 'var(--c-nv)', 'var(--c-fc)', 'var(--c-wif)'];
export function productColor(index: number): string {
  return SERIES[Math.max(0, index) % SERIES.length] ?? SERIES[0]!;
}
