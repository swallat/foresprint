import type { ChangeRow } from '../types.team';

export interface Bar {
  id: string;
  left: number;
  width: number;
  gone: boolean;
}

const DAY = 86400000;
const ms = (d: string) => Date.parse(`${d}T00:00:00Z`);

// The bars of the two lanes of a change (before and after), in percent of the whole period.
// Sprints that fall away have no bar after the change.
export function timeline(rows: ChangeRow[]): { before: Bar[]; after: Bar[] } {
  // Only the sprints up to the last one that changes (and one more), so that a far saved sprint does
  // not shrink the bars.
  const changed = rows.reduce((n, r, i) => (r.notes.length ? i : n), 0);
  const shown = rows.slice(0, changed + 2).filter((r) => r.oldStart);
  if (!shown.length) return { before: [], after: [] };
  const from = Math.min(...shown.flatMap((r) => [ms(r.oldStart), ...(r.gone ? [] : [ms(r.start)])]));
  const to = Math.max(...shown.flatMap((r) => [ms(r.oldLast), ...(r.gone ? [] : [ms(r.last)])])) + DAY;
  const span = to - from;
  const bar = (id: string, start: string, last: string, gone = false): Bar => ({
    id,
    gone,
    left: ((ms(start) - from) / span) * 100,
    width: ((ms(last) + DAY - ms(start)) / span) * 100,
  });
  return {
    before: shown.map((r) => bar(r.old, r.oldStart, r.oldLast, r.gone)),
    after: shown.filter((r) => !r.gone).map((r) => bar(r.id, r.start, r.last)),
  };
}
