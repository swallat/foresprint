import { describe, expect, it } from 'vitest';
import { proposeShares, shareSum } from './products';

const p = (id: string, share: number | null) => ({ id, share });
const sum = (r: Record<string, number>) => Math.round(Object.values(r).reduce((n, v) => n + v, 0) * 100);

describe('products', () => {
  it('adds up the agreed shares in whole percent', () => {
    expect(shareSum([p('a', 0.35), p('b', 0.2), p('c', null)])).toBe(55);
  });
  it('passes the share of an ended product on in proportion', () => {
    const r = proposeShares([p('a', 0.35), p('b', 0.25), p('c', 0.2)]);
    expect(sum(r)).toBe(100);
    expect(r.a).toBeGreaterThan(0.35);
    expect(r.a! / r.b!).toBeCloseTo(0.35 / 0.25, 1);
  });
  it('splits evenly when nobody has a share', () => {
    const r = proposeShares([p('a', null), p('b', 0), p('c', null)]);
    expect(sum(r)).toBe(100);
    expect(Math.max(...Object.values(r)) - Math.min(...Object.values(r))).toBeLessThan(0.0101);
  });
  it('normalizes shares that did not add up to 100', () => {
    expect(sum(proposeShares([p('a', 0.3), p('b', 0.3)]))).toBe(100);
  });
  it('is empty without remaining products', () => {
    expect(proposeShares([])).toEqual({});
  });
});
