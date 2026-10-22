import { describe, expect, it } from 'vitest';
import type { Person } from '../types.team';
import { currentPeriod, fteOn, isCurrent, needsEnd, periodProblem, rejoined, withLeaving, withNewShare, withShare } from './people';

const person = (over: Partial<Person> = {}): Person => ({
  id: 'a',
  name: 'A',
  kind: 'member',
  production: false,
  used: false,
  memberships: [{ from: '2025-04-01', to: '', fte: 1 }],
  ...over,
});

describe('people', () => {
  it('splits the period for a new share', () => {
    const p = withNewShare(person(), '2026-01-01', 0.8);
    expect(p.memberships).toEqual([
      { from: '2025-04-01', to: '2025-12-31', fte: 1 },
      { from: '2026-01-01', to: '', fte: 0.8 },
    ]);
    expect(fteOn(p, '2025-06-01')).toBe(1);
    expect(fteOn(p, '2026-10-22')).toBe(0.8);
  });
  it('ignores a new share that does not lie after the last start', () => {
    const p = person();
    expect(withNewShare(p, '2025-04-01', 0.5)).toBe(p);
  });
  it('changes the share of the current period only', () => {
    const p = withShare(withNewShare(person(), '2026-01-01', 0.8), '2026-10-22', 0.6);
    expect(p.memberships.map((m) => m.fte)).toEqual([1, 0.6]);
  });
  it('knows who is current', () => {
    const gone = withLeaving(person(), '2026-06-30');
    expect(isCurrent(gone, '2026-10-22')).toBe(false);
    expect(isCurrent(gone, '2026-06-30')).toBe(true);
    expect(isCurrent(person(), '2026-10-22')).toBe(true);
    expect(fteOn(gone, '2026-10-22')).toBe(0);
  });
  it('takes the next period for someone who has not started', () => {
    const p = person({ memberships: [{ from: '2027-01-01', to: '', fte: 0.5 }] });
    expect(currentPeriod(p, '2026-10-22')?.fte).toBe(0.5);
    expect(isCurrent(p, '2026-10-22')).toBe(true);
  });
  it('lets a person return with a new period', () => {
    const p = rejoined(withLeaving(person(), '2026-06-30'), '2026-10-22');
    expect(p.memberships).toHaveLength(2);
    expect(p.memberships[1]).toEqual({ from: '2026-10-22', to: '', fte: 1 });
    expect(periodProblem(p)).toBe('');
  });
  it('reports bad periods', () => {
    expect(periodProblem(person({ memberships: [{ from: '2026-02-01', to: '2026-01-01', fte: 1 }] }))).not.toBe('');
    expect(periodProblem(person({ memberships: [{ from: '2026-01-01', to: '', fte: 1.5 }] }))).not.toBe('');
    expect(
      periodProblem(
        person({
          memberships: [
            { from: '2026-01-01', to: '2026-03-01', fte: 1 },
            { from: '2026-03-01', to: '', fte: 1 },
          ],
        }),
      ),
    ).not.toBe('');
  });
  it('asks externals for an end date', () => {
    expect(needsEnd(person({ kind: 'external' }))).toBe(true);
    expect(needsEnd(withLeaving(person({ kind: 'external' }), '2026-12-31'))).toBe(false);
    expect(needsEnd(person())).toBe(false);
  });
});
