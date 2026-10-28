import { describe, expect, it } from 'vitest';
import type { ChangeRow } from '../types.team';
import { timeline } from './timeline';

const row = (id: string, oldStart: string, oldLast: string, start: string, last: string, gone = false): ChangeRow => ({
  id, old: id, oldStart, oldLast, start, last, workdays: 10, gone, saved: true, notes: [],
});

describe('timeline', () => {
  it('draws a lane before and after, and leaves a sprint that falls away out of the second', () => {
    const t = timeline([
      row('A', '2026-12-10', '2026-12-23', '2026-12-10', '2027-01-06'),
      row('B', '2026-12-24', '2027-01-06', '2026-12-24', '2027-01-06', true),
      row('C', '2027-01-07', '2027-01-20', '2027-01-07', '2027-01-20'),
    ]);
    expect(t.before.map((b) => b.id)).toEqual(['A', 'B', 'C']);
    expect(t.after.map((b) => b.id)).toEqual(['A', 'C']);
    expect(t.before[0]!.left).toBe(0);
    expect(t.before[2]!.left + t.before[2]!.width).toBeCloseTo(100);
    expect(t.after[0]!.width).toBeGreaterThan(t.before[0]!.width);
  });

  it('is empty without rows', () => {
    expect(timeline([])).toEqual({ before: [], after: [] });
  });
});
