import { describe, expect, it } from 'vitest';
import { isNoopMove } from './moves';

const d = { tickets: [{ key: 'A-1' }], candidates: [{ key: 'B-2' }] } as never;

describe('isNoopMove', () => {
  it('ignores a drop inside the same column', () => {
    expect(isNoopMove(d, 'B-2', 'candidates')).toBe(true);
    expect(isNoopMove(d, 'A-1', 'sprint')).toBe(true);
  });
  it('lets a drop into the other column through', () => {
    expect(isNoopMove(d, 'B-2', 'sprint')).toBe(false);
    expect(isNoopMove(d, 'A-1', 'candidates')).toBe(false);
  });
});
