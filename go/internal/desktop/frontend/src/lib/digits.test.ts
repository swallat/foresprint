import { afterEach, describe, expect, it } from 'vitest';
import { setDigits } from './digits.svelte';
import { fmt, fmtCap, fmtRate, fmtVal } from './format';

describe('numbers follow the rounding of the team', () => {
  afterEach(() => setDigits(1, 1));

  it('shows the plan with the chosen decimals, not as a whole number', () => {
    setDigits(2, 1);
    expect(fmt(12.89)).toBe('12.89');
    setDigits(3, 1);
    expect(fmt(12.896)).toBe('12.896');
    setDigits(0, 1);
    expect(fmt(12.896)).toBe('13');
  });

  it('keeps one decimal for entered values and estimates, whatever the rounding', () => {
    setDigits(0, 1);
    expect(fmtVal(2.5)).toBe('2.5');
    setDigits(3, 1);
    expect(fmtVal(2.125)).toBe('2.125');
  });

  it('uses the capacity rounding for capacities and enough digits for rates', () => {
    setDigits(0, 2);
    expect(fmtCap(41.6)).toBe('41.6');
    expect(fmtCap(41.666)).toBe('41.67');
    expect(fmtRate(0.30991)).toBe('0.3099');
  });

  it('falls back to one decimal for a value out of range', () => {
    setDigits(7, undefined);
    expect(fmt(1.26)).toBe('1.3');
  });
});
