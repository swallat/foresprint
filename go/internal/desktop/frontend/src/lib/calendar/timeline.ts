import type { ChangeRow } from '../types.team';

export interface Bar {
  id: string;
  left: number;
  width: number;
}

const DAY = 86400000;
const ms = (d: string) => Date.parse(`${d}T00:00:00Z`);

// The bars of the two lanes of a change (before and after), in percent of the whole period.
// Sprints that fall away have no bar after the change.
export function timeline(rows: ChangeRow[]): { before: Bar[]; after: Bar[] } {
  const shown = rows.filter((r) => r.oldStart);
  if (!shown.length) return { before: [], after: [] };
  const from = Math.min(...shown.flatMap((r) => [ms(r.oldStart), ...(r.gone ? [] : [ms(r.start)])]));
  const to = Math.max(...shown.flatMap((r) => [ms(r.oldLast), ...(r.gone ? [] : [ms(r.last)])])) + DAY;
  const span = to - from;
  const bar = (id: string, start: string, last: string): Bar => ({
    id,
    left: ((ms(start) - from) / span) * 100,
    width: ((ms(last) + DAY - ms(start)) / span) * 100,
  });
  return {
    before: shown.map((r) => bar(r.old, r.oldStart, r.oldLast)),
    after: shown.filter((r) => !r.gone).map((r) => bar(r.id, r.start, r.last)),
  };
}
