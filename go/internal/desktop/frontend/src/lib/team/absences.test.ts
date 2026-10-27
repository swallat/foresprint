import { describe, expect, it } from 'vitest';
import { changed, created } from './absences';

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
});
