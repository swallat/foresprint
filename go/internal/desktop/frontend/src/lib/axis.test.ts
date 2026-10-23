import { describe, expect, it } from 'vitest';
import { shortNames } from './axis';

describe('shortNames', () => {
  it('drops a shared prefix up to the last separator', () => {
    expect(shortNames(['Alpha Sprint 41', 'Alpha Sprint 42'])).toEqual(['41', '42']);
    expect(shortNames(['2026.21', '2026.22'])).toEqual(['21', '22']);
  });
  it('never cuts inside a word and keeps single or unrelated names', () => {
    expect(shortNames(['Sprint 10', 'Sprint 11', 'Spring'])).toEqual(['Sprint 10', 'Sprint 11', 'Spring']);
    expect(shortNames(['Only'])).toEqual(['Only']);
  });
});
