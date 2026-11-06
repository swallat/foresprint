import { describe, expect, it } from 'vitest';
import { frac, par, sq, sqrt, id, op, lines } from './mathml';

describe('mathml', () => {
  it('puts the whole radicand under one root and parenthesises the square base', () => {
    const m = sqrt(frac(sq(par(id('a'), op('−'), id('b'))), id('n')));
    expect(m).toBe('<msqrt><mfrac><mrow><msup><mrow><mo>(</mo><mi>a</mi><mo>−</mo><mi>b</mi><mo>)</mo></mrow><mn>2</mn></msup></mrow><mrow><mi>n</mi></mrow></mfrac></msqrt>');
  });
  it('wraps every line in its own math element', () => {
    expect(lines(id('a'), id('b')).match(/<math /g)?.length).toBe(2);
  });
});
