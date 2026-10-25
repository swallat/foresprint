// The list "Changes before saving" of the settings pages: what differs between the applied and
// the edited settings, as label, before and after in words.

export interface Row {
  label: string;
  before: string;
  after: string;
}

export type Show = (value: unknown) => string;

export interface Field<T> {
  label: string;
  get: (settings: T) => unknown;
  /** How a value reads in the list; default: on/off, lists with commas, numbers as they are. */
  show?: Show;
}

export function plain(value: unknown, on = 'on', off = 'off', none = '–'): string {
  if (value === true) return on;
  if (value === false) return off;
  if (value === null || value === undefined || value === '') return none;
  if (Array.isArray(value)) return value.length ? value.map((v) => plain(v, on, off, none)).join(', ') : none;
  return String(value);
}

export function changes<T>(fields: Field<T>[], before: T, after: T, words: { on: string; off: string; none: string }): Row[] {
  const rows: Row[] = [];
  for (const f of fields) {
    const a = f.get(before);
    const b = f.get(after);
    if (JSON.stringify(a) === JSON.stringify(b)) continue;
    const show = f.show ?? ((v: unknown) => plain(v, words.on, words.off, words.none));
    rows.push({ label: f.label, before: show(a), after: show(b) });
  }
  return rows;
}

/** Reads a number the way people type it ("1,5" and "1.5"); undefined if it is not one. */
export function parseNumber(text: string): number | undefined {
  const cleaned = text.trim().replace(',', '.');
  if (cleaned === '' || !/^-?\d*\.?\d+$/.test(cleaned)) return undefined;
  return Number(cleaned);
}
