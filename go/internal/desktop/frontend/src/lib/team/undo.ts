// Undo of one change of a list (people, products): only the entries the change touched are put
// back, so edits made to other entries in the meantime stay.

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Returns a function that takes the change from `before` to `after` back in any later list:
 * an added entry is removed, a removed one is put in again at its old place, a changed one
 * gets its old values. Entries that are gone or are not there are skipped.
 */
export function inverse<T extends { id: string }>(before: T[], after: T[]): (current: T[]) => T[] {
  const beforeIds = new Set(before.map((x) => x.id));
  const afterById = new Map(after.map((x) => [x.id, x]));
  const added = after.filter((x) => !beforeIds.has(x.id)).map((x) => x.id);
  const removed = before.map((x, i) => ({ x, i })).filter(({ x }) => !afterById.has(x.id));
  const changed = before.filter((x) => afterById.has(x.id) && !same(x, afterById.get(x.id)));
  return (current) => {
    let list = current.filter((x) => !added.includes(x.id));
    list = list.map((x) => changed.find((c) => c.id === x.id) ?? x);
    for (const { x, i } of removed) {
      if (!list.some((y) => y.id === x.id)) list.splice(Math.min(i, list.length), 0, x);
    }
    return list;
  };
}
