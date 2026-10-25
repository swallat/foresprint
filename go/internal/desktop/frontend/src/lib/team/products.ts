// Small rules about product shares, used by the products page. Shares are 0..1; the page shows
// whole percent.

import type { Product } from '../types.team';

export const percent = (share: number | null): number | null => (share === null ? null : Math.round(share * 100));

/** Sum of the agreed shares in whole percent (products without a share count 0). */
export function shareSum(products: Pick<Product, 'share'>[]): number {
  return products.reduce((n, p) => n + (percent(p.share) ?? 0), 0);
}

/**
 * Proposal for the shares of the remaining products when a product is ended: the ended share
 * goes to the others in proportion to what they have (evenly if none has any), so that the
 * remaining ones reach exactly 100 percent in whole percent (the last points go to the largest
 * remainders). Returns shares as 0..1.
 */
export function proposeShares(remaining: Pick<Product, 'id' | 'share'>[]): Record<string, number> {
  if (remaining.length === 0) return {};
  const have = remaining.map((p) => percent(p.share) ?? 0);
  const base = have.reduce((n, v) => n + v, 0);
  const exact = have.map((v) => (base > 0 ? (v / base) * 100 : 100 / remaining.length));
  const out = exact.map(Math.floor);
  const left = 100 - out.reduce((n, v) => n + v, 0);
  const order = exact.map((v, i) => ({ i, rest: v - (out[i] ?? 0) })).sort((a, b) => b.rest - a.rest || a.i - b.i);
  for (let k = 0; k < left; k++) out[order[k]!.i] = (out[order[k]!.i] ?? 0) + 1;
  const result: Record<string, number> = {};
  remaining.forEach((p, i) => (result[p.id] = (out[i] ?? 0) / 100));
  return result;
}
