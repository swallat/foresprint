import { describe, expect, it } from 'vitest';
import { changed, created, overlapping } from './absences';

const open = '2026-10-28';
const partly = { person: 'a', from: '2026-10-20', to: '2026-11-03', confirmed: false };

describe('absence period rules', () => {
  it('keeps finished days of a partly finished period', () => {
    expect(changed(partly, { from: '2026-10-30' }, open)).toBeNull();
    expect(changed(partly, { to: '2026-10-25' }, open)).toBeNull();
    expect(changed(partly, { to: '2026-11-10' }, open)?.to).toBe('2026-11-10');
    expect(changed(partly, { confirmed: true }, open)?.confirmed).toBe(true);
  });

  it('moves the end with a later first day and refuses finished days for open periods', () => {
    const p = { person: 'a', from: '2026-11-02', to: '2026-11-03', confirmed: false };
    expect(changed(p, { from: '2026-11-05' }, open)?.to).toBe('2026-11-05');
    expect(changed(p, { from: '2026-10-20' }, open)).toBeNull();
  });

  it('creates new periods outside finished sprints', () => {
    const old = [{ person: 'a', from: '2026-08-10', to: '2026-08-14', confirmed: true }];
    expect(created(old, 'a', '2026-10-27', open).from).toBe(open);
  });

  it('finds periods of the same person that share a day', () => {
    const a = { person: 'a', from: '2027-08-13', to: '2027-08-15', confirmed: true };
    const b = { person: 'a', from: '2027-08-06', to: '2027-08-22', confirmed: false };
    expect(overlapping([a, b], b, b)).toBe(a);
    expect(overlapping([a], { ...b, to: '2027-08-12' })).toBeNull();
    expect(overlapping([a], { ...b, to: '2027-08-13' })).toBe(a);
    expect(overlapping([a], { ...b, person: 'x' })).toBeNull();
  });
});
