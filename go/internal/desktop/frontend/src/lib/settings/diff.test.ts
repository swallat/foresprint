import { describe, expect, it } from 'vitest';
import { changes, parseNumber, plain } from './diff';

const words = { on: 'on', off: 'off', none: '–' };

describe('changes', () => {
  const fields = [
    { label: 'Window', get: (s: { w: number }) => s.w },
    { label: 'Names', get: (s: { n: string[] }) => s.n },
    { label: 'Feature', get: (s: { f: boolean }) => s.f },
  ];
  it('lists only what differs', () => {
    const rows = changes(fields as never, { w: 5, n: ['a'], f: false }, { w: 6, n: ['a'], f: true }, words);
    expect(rows).toEqual([
      { label: 'Window', before: '5', after: '6' },
      { label: 'Feature', before: 'off', after: 'on' },
    ]);
  });
  it('shows lists with commas and empty ones as a dash', () => {
    const rows = changes(fields as never, { w: 5, n: [], f: false }, { w: 5, n: ['a', 'b'], f: false }, words);
    expect(rows).toEqual([{ label: 'Names', before: '–', after: 'a, b' }]);
  });
});

describe('plain', () => {
  it('reads values', () => {
    expect(plain(null)).toBe('–');
    expect(plain(0)).toBe('0');
    expect(plain(true, 'ja', 'nein')).toBe('ja');
  });
});

describe('parseNumber', () => {
  it('accepts a decimal comma', () => {
    expect(parseNumber('1,5')).toBe(1.5);
    expect(parseNumber(' 67 ')).toBe(67);
  });
  it('refuses text', () => {
    expect(parseNumber('abc')).toBeUndefined();
    expect(parseNumber('')).toBeUndefined();
    expect(parseNumber('1,5,2')).toBeUndefined();
  });
});
