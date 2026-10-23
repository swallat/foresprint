// Number and date formats of the absence grid, in the language of the window.

import { language } from '../i18n.svelte';

/** Days with up to one decimal ("2,5" in German), no trailing zero. */
export function days(v: number): string {
  return new Intl.NumberFormat(language(), { maximumFractionDigits: 1 }).format(v);
}

/** Parses what a person typed: comma or point, half days. NaN if it is not a number. */
export function parseDays(text: string): number {
  const s = text.trim().replace(',', '.');
  return s === '' ? 0 : Number(s);
}
