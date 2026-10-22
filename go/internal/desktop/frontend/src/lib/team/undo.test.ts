import { describe, expect, it } from 'vitest';
import { inverse } from './undo';

interface E {
  id: string;
  name: string;
  count?: number;
}
const e = (id: string, name = id, count = 0): E => ({ id, name, count });
const F: (keyof E)[] = ['name'];

describe('inverse', () => {
  it('removes what was added and keeps later edits of others', () => {
    const undo = inverse([e('a'), e('b')], [e('a'), e('b'), e('c')], F);
    expect(undo([e('a', 'A2'), e('b'), e('c')])).toEqual({ list: [e('a', 'A2'), e('b')], ok: true });
  });
  it('puts removed entries back at their places, several at once', () => {
    const undo = inverse([e('a'), e('b'), e('c'), e('d')], [e('a'), e('d')], F);
    expect(undo([e('a'), e('d', 'D2')]).list).toEqual([e('a'), e('b'), e('c'), e('d', 'D2')]);
  });
  it('restores only the changed field of the changed entry', () => {
    const undo = inverse([e('a'), e('b')], [e('a', 'A2'), e('b')], F);
    expect(undo([e('a', 'A2', 7), e('b', 'B2')])).toEqual({ list: [e('a', 'a', 7), e('b', 'B2')], ok: true });
  });
  it('refuses when the entry was changed again', () => {
    const undo = inverse([e('a', 'X')], [e('a', 'Y')], F);
    expect(undo([e('a', 'Z')])).toEqual({ list: [e('a', 'Z')], ok: false });
    expect(undo([]).ok).toBe(false);
  });
  it('ignores computed fields', () => {
    const undo = inverse([e('a'), e('b', 'b', 1)], [e('b', 'b', 5)], F);
    expect(undo([e('b', 'B2', 5)])).toEqual({ list: [e('a'), e('b', 'B2', 5)], ok: true });
  });
  it('reports a removed entry whose id was given again', () => {
    const undo = inverse([e('a')], [], F);
    expect(undo([e('a', 'new')]).ok).toBe(false);
  });
  it('handles an add and a remove in one change', () => {
    const undo = inverse([e('a'), e('b')], [e('b'), e('c')], F);
    expect(undo([e('b'), e('c')])).toEqual({ list: [e('a'), e('b')], ok: true });
  });
});
