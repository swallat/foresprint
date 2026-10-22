// Browser answers of the sprint workspace for the demo team "Team Atlas" (invented people).
// The same rules as go/internal/app/api_sprints.go: half days, cut to the working days, an entry
// in a frozen sprint stays confirmed, "unknown" while nothing is entered.

import type {
  AbsenceColumn,
  AbsenceGrid,
  AbsenceState,
  CellState,
  NextStep,
  ReadyItem,
  SprintOverview,
  SprintPrepare,
  SprintRow,
  SprintsApi,
} from '../types.sprints';
import type { SprintInfo } from '../types';
import { sprints as demoSprints } from './shared';

const people = [
  { person: 'anna', name: 'Anna', fte: 1 },
  { person: 'ben', name: 'Ben', fte: 1 },
  { person: 'chiara', name: 'Chiara', fte: 0.8 },
  { person: 'david', name: 'David', fte: 1 },
  { person: 'eva', name: 'Eva', fte: 0.6 },
  { person: 'farid', name: 'Farid', fte: 1 },
];

const WORKDAYS = 10;
const RATE = 1.5; // points per person day

export function createSprintsMock(sprints: SprintInfo[]): SprintsApi {
  const days = new Map<string, number>(); // "sprint|person"
  const locked = new Set<string>(); // confirmed cells of an open sprint
  const state = new Map<string, AbsenceState>();
  // Two announced absences in the running or next sprint, one in the sprint after it.
  const ahead = sprints.filter((s) => s.state !== 'past');
  const demo: [number, string, number][] = [
    [0, 'anna', 3],
    [0, 'eva', 2],
    [1, 'ben', 5],
  ];
  for (const [i, p, d] of demo) if (ahead[i]) days.set(`${ahead[i].id}|${p}`, d);
  if (ahead[0]) state.set(ahead[0].id, 'announced');

  const known = (id: string) => {
    const s = sprints.find((x) => x.id === id);
    if (!s) throw new Error(`Sprint ${id} does not exist.`);
    return s;
  };
  const stateOf = (s: SprintInfo): AbsenceState => (s.state === 'past' ? 'confirmed' : (state.get(s.id) ?? 'unknown'));
  const cellState = (s: SprintInfo, person: string): CellState => {
    if (stateOf(s) === 'confirmed') return 'confirmed'; // frozen: every cell, empty ones count as 0 days
    if ((days.get(`${s.id}|${person}`) ?? 0) === 0) return 'empty';
    return locked.has(`${s.id}|${person}`) ? 'confirmed' : 'announced';
  };
  const entries = (id: string) => people.filter((p) => (days.get(`${id}|${p.person}`) ?? 0) > 0);
  const absent = (id: string) => entries(id).reduce((sum, p) => sum + (days.get(`${id}|${p.person}`) ?? 0), 0);
  const fullCapacity = () => people.reduce((sum, p) => sum + p.fte * WORKDAYS, 0);
  const capacityOf = (id: string) => Math.max(0, fullCapacity() - people.reduce((sum, p) => sum + (days.get(`${id}|${p.person}`) ?? 0) * p.fte, 0));

  const column = (s: SprintInfo): AbsenceColumn => ({
    id: s.id,
    name: s.id,
    start: s.start,
    end: s.end,
    state: stateOf(s),
    workdays: WORKDAYS,
    entries: entries(s.id).length,
    absent: absent(s.id),
    capacity: Math.round(capacityOf(s.id) * 10) / 10,
    plan: s.state === 'past' ? null : Math.floor(capacityOf(s.id) * RATE),
    planLow: s.state === 'past' ? null : Math.floor(capacityOf(s.id) * RATE * 0.92),
    planHigh: s.state === 'past' ? null : Math.floor(capacityOf(s.id) * RATE * 1.08),
    past: s.state === 'past',
  });

  const window = (from: string, count: number) => {
    let i = sprints.findIndex((s) => (from ? s.id === from : s.state !== 'past'));
    if (i < 0) i = Math.max(0, sprints.length - count);
    return sprints.slice(i, i + count);
  };

  const touch = (id: string) => {
    const s = known(id);
    if (stateOf(s) !== 'confirmed') state.set(id, entries(id).length ? 'announced' : 'unknown');
  };

  return {
    async SprintOverview(_team, past): Promise<SprintOverview> {
      const finished = sprints.filter((s) => s.state === 'past');
      const shown = [...(past < 0 ? finished : finished.slice(-past)), ...sprints.filter((s) => s.state !== 'past')];
      let velocity = 31;
      const rows = shown.map((s, i): SprintRow => {
        const col = column(s);
        const done = s.state === 'past';
        velocity = done ? 29 + ((i * 7) % 6) : velocity;
        const next: NextStep = done ? 'none' : s.state === 'current' ? 'review' : col.state !== 'confirmed' ? 'absences' : 'plan';
        return {
          id: s.id,
          name: s.id,
          start: s.start,
          end: s.end,
          state: done ? 'past' : s.state === 'current' ? 'current' : 'future',
          absences: col.state,
          capacity: col.capacity,
          plan: col.plan,
          planLow: col.planLow,
          planHigh: col.planHigh,
          commitment: done || s.state === 'current' ? velocity + 2 : null,
          velocity: done ? velocity : null,
          normalized: done ? Math.round(((velocity / col.capacity) * fullCapacity()) * 10) / 10 : null,
          rate: done ? Math.round((velocity / col.capacity) * 100) / 100 : null,
          next,
        };
      });
      return { rows, reference: fullCapacity(), unit: 'SP', currentIndex: rows.findIndex((r) => r.state !== 'past') };
    },
    async AbsenceGrid(_team, from, count): Promise<AbsenceGrid> {
      const cols = window(from, count);
      return {
        columns: cols.map(column),
        rows: people.map((p) => ({
          ...p,
          cells: cols.map((s) => ({ days: days.get(`${s.id}|${p.person}`) ?? 0, state: cellState(s, p.person), max: WORKDAYS, active: true })),
        })),
      };
    },
    async SetAbsence(_team, sprint, person, value) {
      const s = known(sprint);
      if (!people.some((p) => p.person === person)) throw new Error(`Person ${person} does not exist.`);
      if (!(value >= 0)) throw new Error('Enter a number of days from 0 to the working days of the sprint.');
      const d = Math.min(WORKDAYS, Math.round(value * 2) / 2);
      if (d === 0) days.delete(`${sprint}|${person}`);
      else days.set(`${sprint}|${person}`, d);
      touch(sprint);
      return column(s);
    },
    async SetAbsenceConfirmed(_team, sprint, person, confirmed) {
      const key = `${sprint}|${person}`;
      if (confirmed && (days.get(key) ?? 0) > 0) locked.add(key);
      else locked.delete(key);
      return column(known(sprint));
    },
    async FreezeAbsences(_team, sprint) {
      state.set(sprint, 'confirmed');
      return column(known(sprint));
    },
    async UnfreezeAbsences(_team, sprint) {
      for (const p of people) locked.delete(`${sprint}|${p.person}`);
      state.set(sprint, 'unknown');
      touch(sprint);
      return column(known(sprint));
    },
    async SprintPrepare(_team, sprint): Promise<SprintPrepare> {
      const col = column(known(sprint));
      const ready: ReadyItem[] = [
        { kind: 'absences', state: col.state === 'confirmed' ? 'done' : 'open', count: col.entries, names: [] },
        { kind: 'refinement', state: 'open', count: 2, names: ['ATL-212', 'ATL-218'] },
        { kind: 'preplan', state: 'open', count: 1, names: ['Mobile'] },
      ];
      return {
        sprint: col,
        capacityBase: fullCapacity(),
        planBase: Math.floor(fullCapacity() * RATE),
        preplanned: 24,
        unit: 'SP',
        ready,
      };
    },
  };
}

export default createSprintsMock(demoSprints);
