import { describe, expect, it } from 'vitest';
import { format } from './i18n.svelte';

describe('format', () => {
  it('fills placeholders', () => {
    expect(format('{n} new changes from {who}', { n: 2, who: 'Anna' })).toBe('2 new changes from Anna');
  });
  it('keeps unknown placeholders', () => {
    expect(format('Hello {name}', {})).toBe('Hello {name}');
  });
  it('returns the text without values', () => {
    expect(format('Save')).toBe('Save');
  });
});
