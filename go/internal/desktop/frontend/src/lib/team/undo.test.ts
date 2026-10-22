import { describe, expect, it } from 'vitest';
import { inverse } from './undo';

const e = (id: string, name = id) => ({ id, name });

describe('inverse', () => {
  it('removes what was added and keeps later edits of others', () => {
    const undo = inverse([e('a'), e('b')], [e('a'), e('b'), e('c')]);
    expect(undo([e('a', 'A2'), e('b'), e('c')])).toEqual([e('a', 'A2'), e('b')]);
  });
  it('puts a removed entry back at its place', () => {
    const undo = inverse([e('a'), e('b'), e('c')], [e('a'), e('c')]);
    expect(undo([e('a'), e('c', 'C2')])).toEqual([e('a'), e('b'), e('c', 'C2')]);
  });
  it('restores only the changed entry', () => {
    const undo = inverse([e('a'), e('b')], [e('a', 'A2'), e('b')]);
    expect(undo([e('a', 'A2'), e('b', 'B2')])).toEqual([e('a'), e('b', 'B2')]);
  });
  it('skips an entry that is gone and does not add one twice', () => {
    const undo = inverse([e('a'), e('b')], [e('a', 'A2'), e('b')]);
    expect(undo([e('b')])).toEqual([e('b')]);
    expect(inverse([e('a')], [])([e('a')])).toEqual([e('a')]);
  });
});
