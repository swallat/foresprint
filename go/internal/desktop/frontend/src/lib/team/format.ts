// Dates and numbers of the Team pages in the language of the window.

import { language } from '../i18n.svelte';

function utc(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

/** "22.10.2026" / "10/22/2026" as the language wants it. */
export function fmtDay(iso: string): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }).format(utc(iso));
}

/** Day and month only, "22.10.". */
export function fmtShort(iso: string): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit', timeZone: 'UTC' }).format(utc(iso));
}

/** A number with at most `digits` decimals, in the language's style ("0,8"). */
export function fmtNum(n: number, digits = 1): string {
  return new Intl.NumberFormat(language(), { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(n);
}

/** Reads "0,8" or "0.8"; NaN when it is not a number. */
export function parseNum(text: string): number {
  return Number.parseFloat(text.trim().replace(',', '.'));
}
