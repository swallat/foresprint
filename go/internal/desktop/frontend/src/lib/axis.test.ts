import { describe, expect, it } from 'vitest';
import { shortNames } from './axis';

describe('shortNames', () => {
  it('drops a shared prefix up to the last separator', () => {
    expect(shortNames(['Alpha Sprint 41', 'Alpha Sprint 42'])).toEqual(['41', '42']);
    expect(shortNames(['2026.21', '2026.22'])).toEqual(['21', '22']);
  });
  it('falls back to the last word when only some names carry a prefix', () => {
    expect(shortNames(['2026.10', '2026.11', 'Team - Sprint 2026.12'])).toEqual(['2026.10', '2026.11', '2026.12']);
    expect(shortNames(['Team A 1', 'Team B 1'])).toEqual(['A 1', 'B 1']);
  });
  it('never cuts inside a word and keeps single or unrelated names', () => {
    expect(shortNames(['Sprint 10', 'Sprint 11', 'Spring'])).toEqual(['10', '11', 'Spring']);
    expect(shortNames(['Sprint 1', 'Sprint 1 b', 'Spring']).length).toBe(3);
    expect(shortNames(['Only'])).toEqual(['Only']);
  });
});
