// Inserting a field name into the text of a rule at the cursor.

export interface Inserted {
  text: string;
  /** Where the cursor goes: between the two quotes, ready to type the value. */
  caret: number;
}

/**
 * Puts `field = ""` at `at`. When the cursor is at the end of a non-empty rule the new
 * condition is joined with AND; elsewhere the text is inserted as it is.
 */
export function insertField(text: string, at: number, field: string): Inserted {
  const pos = Math.max(0, Math.min(at, text.length));
  const join = text.trim() !== '' && pos === text.length ? ' AND ' : '';
  const add = `${join}${field} = ""`;
  return { text: text.slice(0, pos) + add + text.slice(pos), caret: pos + add.length - 1 };
}
