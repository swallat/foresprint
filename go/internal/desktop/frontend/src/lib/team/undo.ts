// Undo of one change of a list (people, products): only the entries and fields the change touched
// are put back, so edits made to other entries in the meantime stay. When something the change
// touched was changed again since, the Undo says so and does nothing.

type Entry = { id: string };

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export interface Inverse<T> {
  /** The list with the change taken back; ok is false when it can no longer be done safely. */
  (current: T[]): { list: T[]; ok: boolean };
}

/**
 * Returns a function that takes the change from `before` to `after` back in any later list: an
 * added entry is removed, a removed one is put in again at its old place, in a changed one the
 * fields the change set get their old values (only if they still have the value the change gave
 * them). `fields` are the fields the user edits; computed fields (counts, flags the server sets)
 * are left out. The order of the entries is not restored.
 */
export function inverse<T extends Entry>(before: T[], after: T[], fields: (keyof T)[]): Inverse<T> {
  const beforeIds = new Set(before.map((x) => x.id));
  const afterById = new Map(after.map((x) => [x.id, x]));
  const added = after.filter((x) => !beforeIds.has(x.id)).map((x) => x.id);
  const removed = before.map((x, i) => ({ x, i })).filter(({ x }) => !afterById.has(x.id));
  const changes: { id: string; old: Partial<T>; now: Partial<T> }[] = [];
  for (const b of before) {
    const a = afterById.get(b.id);
    if (!a) continue;
    const diff = fields.filter((f) => !same(b[f], a[f]));
    if (!diff.length) continue;
    const old: Partial<T> = {};
    const now: Partial<T> = {};
    for (const f of diff) {
      old[f] = b[f];
      now[f] = a[f];
    }
    changes.push({ id: b.id, old, now });
  }
  return (current) => {
    let ok = true;
    let list = current.filter((x) => !added.includes(x.id));
    list = list.map((x) => {
      const c = changes.find((y) => y.id === x.id);
      if (!c) return x;
      if (!(Object.keys(c.now) as (keyof T)[]).every((f) => same(x[f], c.now[f]))) {
        ok = false;
        return x;
      }
      return { ...x, ...c.old };
    });
    if (changes.some((c) => !current.some((x) => x.id === c.id))) ok = false;
    for (const { x, i } of removed) {
      if (list.some((y) => y.id === x.id)) {
        ok = false; // the id has been given again
        continue;
      }
      list.splice(Math.min(i, list.length), 0, x);
    }
    return { list, ok };
  };
}
