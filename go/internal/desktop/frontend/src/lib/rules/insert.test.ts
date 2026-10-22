import { describe, expect, it } from 'vitest';
import { insertField } from './insert';

describe('insertField', () => {
  it('starts an empty rule without AND', () => {
    expect(insertField('', 0, 'component')).toEqual({ text: 'component = ""', caret: 13 });
  });
  it('joins with AND at the end of a rule', () => {
    const r = insertField('epic = "X"', 10, 'label');
    expect(r.text).toBe('epic = "X" AND label = ""');
    expect(r.text[r.caret]).toBe('"');
  });
  it('inserts in the middle as it is', () => {
    expect(insertField('a b', 1, 'label').text).toBe('alabel = "" b');
  });
  it('clamps a cursor outside the text', () => {
    expect(insertField('x', 99, 'label').text).toBe('x AND label = ""');
  });
});
