// Answers of the projects page for a browser without the program: the invented team "Team
// Atlas" (no real data). Dates are relative to today so that the page always looks current.
// Changes are kept in memory; UndoProjects takes back the last one.

import type {
  CloseInput,
  Light,
  MilestoneView,
  ProjectDetail,
  ProjectInput,
  ProjectsApi,
  ProjectsView,
  ProjectView,
  SprintRow,
} from './types.projects';
import type { SprintInfo } from './types';

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (isoDate: string, n: number) => iso(new Date(Date.parse(isoDate) + n * 86400000));
const today = () => iso(new Date());

function sprintList(): SprintInfo[] {
  const now = today();
  const out: SprintInfo[] = [];
  // Sprints of 14 days, the running one starts up to 13 days ago.
  const first = addDays(now, -((Date.parse(now) / 86400000) % 14) - 28);
  for (let i = 0; i < 8; i++) {
    const start = addDays(first, i * 14);
    const end = addDays(start, 13);
    out.push({ id: `2026.${30 + i}`, start, end, state: end < now ? 'past' : start <= now ? 'current' : 'future' });
  }
  return out;
}

const milestone = (id: string, name: string, date: string, light: Light, done = 0, total = 0): MilestoneView => ({
  id,
  name,
  date,
  tickets: Array.from({ length: total }, (_, i) => `AT-${100 + i}`),
  done,
  total,
  light,
});

function seed(): { open: ProjectView[]; closed: ProjectView[] } {
  const t = today();
  const base = {
    note: '',
    rule: '',
    reason: '',
    start: addDays(t, -90),
    openScope: null,
    donePoints: 0,
    plannedPoints: 0,
    months: [],
    state: '' as const,
  };
  const open: ProjectView[] = [
    {
      ...base,
      id: 'self-service',
      name: 'Self-Service 2.0',
      products: ['portal', 'mobile'],
      end: addDays(t, 100),
      priority: 1,
      light: 'warn',
      reason: 'tight',
      booked: 60,
      done: 31,
      planned: 14,
      donePoints: 46.5,
      plannedPoints: 21,
      open: 14,
      rule: 'epic = "Self-Service 2.0"',
      history: true,
      milestones: [
        milestone('m1', 'Beta for pilot customers', addDays(t, 29), 'warn', 3, 6),
        milestone('m2', 'Go-live', addDays(t, 100), 'none'),
      ],
      months: [
        { month: addDays(t, 0).slice(0, 7), booked: 12, done: 20, planned: 4 },
        { month: addDays(t, 31).slice(0, 7), booked: 14, done: null, planned: 6 },
        { month: addDays(t, 62).slice(0, 7), booked: 14, done: null, planned: 4 },
      ],
    },
    {
      ...base,
      id: 'e-invoice',
      name: 'E-Invoice',
      products: ['billing', 'platform'],
      end: addDays(t, 57),
      priority: 2,
      light: 'ok',
      reason: 'on track',
      booked: 40,
      done: 22,
      planned: 9,
      donePoints: 33,
      plannedPoints: 13.5,
      open: 9,
      rule: 'epic = "E-Invoice" OR (component = "Billing" AND label ~ "xinvoice")',
      history: true,
      milestones: [milestone('m1', 'Export format', addDays(t, 36), 'ok', 2, 4), milestone('m2', 'Acceptance', addDays(t, 57), 'none')],
    },
    {
      ...base,
      id: 'login',
      name: 'Login migration',
      products: ['portal', 'mobile', 'platform'],
      end: addDays(t, 43),
      priority: 3,
      light: 'bad',
      reason: 'missed',
      booked: 25,
      done: 21,
      planned: 6,
      donePoints: 31.5,
      plannedPoints: 9,
      open: 6,
      history: true,
      milestones: [milestone('m1', 'New sign-in service live', addDays(t, 43), 'bad', 1, 5)],
    },
  ];
  const closed: ProjectView[] = [
    {
      ...base,
      id: 'dark-mode',
      name: 'Dark mode',
      products: ['mobile'],
      end: addDays(t, -40),
      priority: 9,
      light: 'none',
      booked: 12,
      done: 12,
      planned: null,
      donePoints: 18,
      plannedPoints: 0,
      open: 0,
      history: true,
      state: 'finished',
      milestones: [],
    },
  ];
  return { open, closed };
}

let state = seed();
const undoStack: (typeof state)[] = [];
const remember = () => undoStack.push(clone(state));

function view(): ProjectsView {
  const t = today();
  const sprints = sprintList();
  return {
    today: t,
    enabled: true,
    source: 'tracker',
    unit: 'SP',
    rate: 1.5,
    products: [
      { id: 'portal', name: 'Portal' },
      { id: 'billing', name: 'Billing' },
      { id: 'mobile', name: 'Mobile' },
      { id: 'platform', name: 'Platform' },
    ],
    projects: clone(state.open),
    closed: clone(state.closed),
    sprints,
    sprintDays: 14,
    conflictSprint: sprints.find((s) => s.state === 'future')?.id ?? '',
    conflict: [
      { product: 'portal', budget: 14, demand: [{ project: 'self-service', points: 8 }, { project: 'login', points: 4 }], rest: 2, light: 'warn' },
      { product: 'billing', budget: 8, demand: [{ project: 'e-invoice', points: 5 }], rest: 3, light: 'ok' },
      { product: 'mobile', budget: 10, demand: [{ project: 'self-service', points: 6 }, { project: 'login', points: 4 }], rest: 0, light: 'bad' },
      { product: 'platform', budget: 8, demand: [{ project: 'e-invoice', points: 2 }], rest: 6, light: 'ok' },
    ],
    problem: '',
  };
}

function find(id: string): ProjectView {
  const p = [...state.open, ...state.closed].find((x) => x.id === id);
  if (!p) throw new Error(`The project ${id} does not exist.`);
  return p;
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'project';

export const projectsMock: ProjectsApi = {
  async Projects() {
    return view();
  },
  async Project(_team, id) {
    const p = find(id);
    const v = view();
    const report: SprintRow[] = v.sprints
      .filter((s) => s.state !== 'past')
      .slice(0, 5)
      .map((s, i) => ({
        sprint: s.id,
        state: s.state === 'current' ? 'current' : 'future',
        booked: (p.booked ?? 0) / 9,
        planned: i === 0 ? null : 2 + i,
        done: i === 0 ? 3 : null,
      }));
    return {
      ...v,
      project: clone(p),
      report,
      tickets: Array.from({ length: 4 }, (_, i) => ({
        key: `AT-${100 + i}`,
        title: `Work item ${i + 1}`,
        status: i === 0 ? 'Done' : 'In progress',
        sprint: v.sprints[2 + (i % 2)]?.id ?? '',
        estimate: 3,
        done: i === 0,
      })),
    } satisfies ProjectDetail;
  },
  async SaveProject(_team, input: ProjectInput) {
    remember();
    const name = input.name.trim();
    if (!name) throw new Error('Please enter a name.');
    const id = input.id || slug(name);
    const old = state.open.find((p) => p.id === id);
    const next: ProjectView = {
      id,
      name,
      products: input.products,
      start: input.start,
      end: input.end,
      note: input.note,
      rule: input.rule,
      light: old?.light ?? 'none',
      reason: old?.reason ?? '',
      priority: old?.priority ?? state.open.length + 1,
      booked: input.booked,
      done: old?.done ?? null,
      planned: old?.planned ?? null,
      donePoints: old?.donePoints ?? 0,
      plannedPoints: old?.plannedPoints ?? 0,
      months: Object.entries(input.months)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([month, booked]) => ({ month, booked, done: null, planned: null })),
      openScope: input.openScope,
      open: old?.open ?? 0,
      milestones: input.milestones.map((m, i) => milestone(m.id || `m${i + 1}`, m.name, m.date, 'none', 0, m.tickets.length)),
      state: '',
      history: old?.history ?? false,
    };
    state.open = old ? state.open.map((p) => (p.id === id ? next : p)) : [...state.open, next];
    return id;
  },
  async CloseProject(_team, input: CloseInput) {
    remember();
    const p = find(input.id);
    state.open = state.open.filter((x) => x.id !== input.id);
    state.closed = [...state.closed, { ...p, state: input.how, end: input.at || p.end, light: 'none' }];
  },
  async ReopenProject(_team, id) {
    remember();
    const p = find(id);
    state.closed = state.closed.filter((x) => x.id !== id);
    state.open = [...state.open, { ...p, state: '' }];
  },
  async DeleteProject(_team, id) {
    const p = find(id);
    if (p.history) throw new Error(`${p.name} has history and can only be closed.`);
    remember();
    state.open = state.open.filter((x) => x.id !== id);
  },
  async UndoProjects() {
    const prev = undoStack.pop();
    if (!prev) throw new Error('There is nothing to undo.');
    state = prev;
  },
  async CheckRule(_team, _project, text) {
    if (!text.trim()) return { error: '', matches: 0, keys: [], conflicts: [] };
    if (/(AND|OR|=|~)\s*$/.test(text.trim())) return { error: 'The rule ends too early.', matches: 0, keys: [], conflicts: [] };
    return { error: '', matches: 14, keys: ['AT-100', 'AT-101', 'AT-102'], conflicts: [] };
  },
};
