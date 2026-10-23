// Answers of the Pre-plan and Plan pages in a browser without the program: the invented demo
// team "Team Atlas". The same figures as the Go core, in small form. ?mock=packages, ?mock=none
// and ?mock=simple in the address show the other ways of working (work packages, no tickets,
// one product without PO and production).

import type { SprintInfo } from '../types';
import backlog from './backlog';
import type {
  Assumption,
  FreezeInput,
  PlanApi,
  PlanProduct,
  PlanProject,
  PlanSprint,
  PlanTicket,
  RunningTicket,
  WhatIf,
  WriteMove,
} from '../types.plan';

const mode = (): string => new URLSearchParams(location.search).get('mock') ?? 'tracker';
const simple = () => mode() === 'simple';

const PRODUCTS = [
  { id: 'portal', name: 'Customer portal', po: 'Kim Berger', share: 0.35 },
  { id: 'billing', name: 'Billing', po: 'Kim Berger', share: 0.2 },
  { id: 'mobile', name: 'Mobile app', po: 'Lea Hoffmann', share: 0.25 },
  { id: 'platform', name: 'Platform', po: 'Lea Hoffmann', share: 0.2 },
];
const PROJECTS = [
  { id: 'ss2', name: 'Self-service 2.0', booked: 60 },
  { id: 'erech', name: 'E-invoice', booked: 40 },
  { id: 'login', name: 'Login switch', booked: 25 },
];

interface T {
  key: string;
  title: string;
  product: string;
  project: string;
  est: number | null;
  refined: boolean;
  sprint: string; // earmark or tracker sprint, "" = backlog; "$cur" = running sprint
  prod: number;
  prodSet: boolean;
  remaining?: number;
  status: string;
  added?: boolean;
  done?: boolean;
}

const base: T[] = [
  { key: 'ATL-412', title: 'Filter the invoice list by period', product: 'portal', project: 'ss2', est: 5, refined: true, sprint: '$next', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-415', title: 'Self-service: change address', product: 'portal', project: 'ss2', est: 8, refined: true, sprint: '$next', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-417', title: 'Push note for a new invoice', product: 'mobile', project: 'ss2', est: 5, refined: true, sprint: '$next', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-420', title: 'Register OAuth client for the mobile app', product: 'mobile', project: 'login', est: 3, refined: true, sprint: '$next', prod: 100, prodSet: false, status: 'Ready' },
  { key: 'ATL-421', title: 'Login service: token renewal', product: 'platform', project: 'login', est: 8, refined: true, sprint: '$next', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-423', title: 'E-invoice: check required fields', product: 'billing', project: 'erech', est: 5, refined: true, sprint: '$next', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-424', title: 'Direct debit mandate as PDF', product: 'billing', project: '', est: 3, refined: true, sprint: '', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-426', title: 'Error page during maintenance', product: 'portal', project: '', est: 2, refined: true, sprint: '', prod: 0, prodSet: false, status: 'Ready' },
  { key: 'ATL-427', title: 'Move logging to the new format', product: 'platform', project: '', est: 5, refined: true, sprint: '', prod: 50, prodSet: false, status: 'Ready' },
  { key: 'ATL-433', title: 'Biometric sign-in (iOS)', product: 'mobile', project: 'login', est: 8, refined: false, sprint: '', prod: 0, prodSet: false, status: 'New' },
  { key: 'ATL-436', title: 'Offline mode for invoices', product: 'mobile', project: 'ss2', est: 13, refined: false, sprint: '', prod: 0, prodSet: false, status: 'New' },
  { key: 'ATL-443', title: 'Dark mode in the app', product: 'mobile', project: '', est: null, refined: false, sprint: '', prod: 0, prodSet: false, status: 'New' },
  { key: 'ATL-401', title: 'Invoice detail: expand positions', product: 'portal', project: 'ss2', est: 5, refined: true, sprint: '$cur', prod: 0, prodSet: false, remaining: 2, status: 'In progress' },
  { key: 'ATL-402', title: 'Cancellation form', product: 'portal', project: '', est: 5, refined: true, sprint: '$cur', prod: 0, prodSet: false, status: 'In progress' },
  { key: 'ATL-404', title: 'Credit notes in the export', product: 'billing', project: 'erech', est: 8, refined: true, sprint: '$cur', prod: 0, prodSet: false, status: 'Done', done: true },
  { key: 'ATL-405', title: 'Release pipeline for the app', product: 'mobile', project: '', est: 5, refined: true, sprint: '$cur', prod: 100, prodSet: false, remaining: 3, status: 'In progress' },
  { key: 'ATL-411', title: 'Hotfix: rounding in the invoice PDF', product: 'billing', project: '', est: 3, refined: true, sprint: '$cur', prod: 50, prodSet: false, status: 'In progress', added: true },
];

let tickets: T[] = structuredClone(base);
let pre: Record<string, Record<string, number>> = {};
let matrixMock: Record<string, Record<string, Record<string, number>>> = {};
let projAmt: Record<string, Record<string, number>> = {};
let sprintPre: Record<string, number> = {};
let removedMock: Record<string, string[]> = {};
let prodPT: Record<string, number> = {};
let saved: Record<string, Assumption[]> = {};
let frozen: Record<string, { keys: string[]; commitment: number }> = {};
let planned: Record<string, Record<string, number>> = {};
let writeDone: Record<string, WriteMove[]> = {};

let sprintsOf: () => SprintInfo[] = () => [];
export function bindSprints(fn: () => SprintInfo[]): void {
  sprintsOf = fn;
}

const RATE = 0.85;
const SHARE = 0.85;
const capacityOf = (i: number) => [44, 48, 41, 50, 49, 38, 46, 47, 45, 44, 43, 48, 46, 47][i % 14] ?? 45;
const idx = (id: string) => sprintsOf().findIndex((s) => s.id === id);
const curId = () => sprintsOf().find((s) => s.state === 'current')?.id ?? '';
const nextOf = (id: string) => sprintsOf()[idx(id) + 1]?.id ?? '';
const resolve = (s: string) => (s === '$cur' ? curId() : s === '$next' ? nextOf(curId()) : s);
const round1 = (v: number) => Math.round(v * 10) / 10;

function moveOf(key: string, reason: WriteMove['reason'], from: string, to: string): WriteMove {
  return { key, title: tickets.find((x) => x.key === key)?.title ?? key, reason, from, to, fromKnown: true };
}

function ticketOf(x: T): PlanTicket {
  const size = x.est;
  return {
    key: x.key, title: x.title, status: x.status, url: mode() === 'packages' ? '' : `https://jira.example.com/browse/${x.key}`,
    estimate: x.est, size, product: simple() ? '' : x.product, project: x.project, refined: x.refined && x.est != null,
    sprint: resolve(x.sprint), inTracker: x.sprint === '$cur' ? curId() : '',
    prodPct: x.prod, prodSource: x.prodSet ? 'manual' : x.prod > 0 ? 'rule' : 'none', remaining: x.remaining ?? null,
  };
}

function figures(sid: string): { cap: number; plan: number; low: number; high: number } {
  const i = Math.max(0, idx(sid));
  const cap = capacityOf(i);
  return { cap, plan: Math.round(cap * RATE), low: Math.round(cap * 0.74), high: Math.round(cap * 0.97) };
}

function whatIf(sid: string, as: Assumption): WhatIf | null {
  const cur = curId();
  if (!cur || nextOf(cur) !== sid) return null;
  const f = figures(sid);
  const noT = mode() === 'none';
  let commitment = 0, notDone = 0, extra = 0, rest = 0, later = 0;
  if (noT) {
    commitment = as.commitment ?? 40;
    notDone = as.notDone ?? 0;
    extra = as.extra ?? 0;
    rest = Math.min(as.restNext ?? notDone, notDone);
    later = notDone - rest;
  } else {
    for (const x of tickets.filter((q) => q.sprint === '$cur')) {
      const c = as.carry.find((k) => k.ticket === x.key);
      if (!x.added) {
        commitment += x.est ?? 0;
        if (c) notDone += x.est ?? 0;
      } else if (!c) extra += x.est ?? 0;
      if (c) (c.target === '' || c.target === sid ? (rest += c.rest) : (later += c.rest));
    }
  }
  const adjusted = as.focusPercent != null || as.extraAbsenceDays != null;
  const touched = adjusted || (noT ? notDone > 0 || extra > 0 || as.commitment != null : as.carry.length > 0);
  const velocity = Math.max(commitment - notDone + extra, 0);
  const capShare = Math.max(f.cap - (as.extraAbsenceDays ?? 0), 0) / (f.cap || 1) * ((as.focusPercent ?? 100) / 100);
  const k = (touched ? 1 + (velocity - commitment) / (commitment * 12) : 1) * capShare;
  const plan = Math.round(f.plan * k);
  const free = Math.floor(Math.max(plan - rest, 0) * SHARE);
  return {
    running: cur, touched, commitment, notDone, extra, velocity, plan, planOriginal: f.plan,
    low: Math.round(f.low * k), high: Math.round(f.high * k), rest, later, plannable: free, smallStuff: Math.max(plan - rest, 0) - free,
  };
}

function view(sid: string, as: Assumption | null): PlanSprint {
  const sp = sprintsOf().find((s) => s.id === sid);
  const noT = mode() === 'none';
  const f = figures(sid);
  const w = as ? whatIf(sid, as) : null;
  const use = w && w.touched ? w : null;
  const plan = use?.plan ?? f.plan;
  const savedA = saved[sid] ?? [];
  const lastSaved = savedA.at(-1);
  const sw = !use && lastSaved ? whatIf(sid, lastSaved) : null;
  const rest = use ? use.rest : sw ? sw.rest : 0;
  const free = Math.floor(Math.max(plan - rest, 0) * SHARE);
  const lane = noT ? [] : tickets.filter((x) => resolve(x.sprint) === sid || (frozen[sid]?.keys.includes(x.key) ?? false)).filter((x) => frozen[sid] ? frozen[sid]!.keys.includes(x.key) : true).map(ticketOf);
  const cand = noT ? [] : tickets.filter((x) => !x.done && x.sprint !== '$cur' && !lane.some((l) => l.key === x.key) && (resolve(x.sprint) === '' || idx(resolve(x.sprint)) > idx(sid))).map(ticketOf);
  const multi = !simple();
  const earmark: Record<string, number> = {};
  for (const x of lane) earmark[x.product] = (earmark[x.product] ?? 0) + (x.size ?? 0);
  const products: PlanProduct[] = multi
    ? PRODUCTS.map((p) => ({
        id: p.id, name: p.name, po: p.po, poName: p.po, default: Math.round(p.share * plan), pre: pre[sid]?.[p.id] ?? null,
        earmark: earmark[p.id] ?? 0, planned: planned[sid]?.[p.id] ?? null, prodPlanned: null, done: null, active: true,
        budget: pre[sid]?.[p.id] ?? Math.round(p.share * plan),
      }))
    : [];
  const preSum = products.reduce((a, p) => a + (p.pre ?? 0), 0);
  const rate = RATE;
  const projects: PlanProject[] = PROJECTS.map((p) => {
    const l = lane.filter((x) => x.project === p.id);
    const amount = noT ? projAmt[sid]?.[p.id] ?? 0 : l.reduce((a, x) => a + (x.size ?? 0), 0);
    return { id: p.id, name: p.name, tickets: l.length, amount, needPD: amount ? amount / rate : null, bookedPD: p.booked, usedPD: p.booked == null ? null : Math.round(p.booked * 0.3), manual: noT };
  }).filter((p) => p.amount > 0 || noT);
  const demandAmount = lane.reduce((a, x) => a + (x.size ?? 0) * x.prodPct / 100, 0);
  const avail = 11.4;
  const demand = noT ? prodPT[sid] ?? 0 : demandAmount / rate;
  const load = avail > 0 ? demand / avail : null;
  const st = sp?.state === 'past' ? 'past' : sp?.state === 'current' ? 'current' : frozen[sid] ? 'planned' : 'open';
  return {
    team: 'atlas', sprint: sid, start: sp?.start ?? '', end: sp?.end ?? '', days: 10, stage: st,
    unit: 'SP', source: noT ? 'none' : mode() === 'packages' ? 'packages' : 'tracker', trackerName: mode() === 'tracker' || mode() === 'simple' ? 'Jira' : '', writeBack: mode() === 'tracker', writeUndo: (writeDone[sid] ?? []).length > 0,
    multiProduct: multi, multiPO: multi, production: multi,
    absences: absencesFrozen.has(sid) || idx(sid) % 3 === 0 ? 'confirmed' : 'announced', absenceDays: 6, capacity: f.cap,
    plan, planOriginal: f.plan, low: use?.low ?? f.low, high: use?.high ?? f.high, rate, otherUnit: 'PT', share: SHARE,
    split: { plan, carryIn: rest, plannable: free, smallStuff: Math.max(plan - rest, 0) - free, overbooked: rest > plan },
    carryLater: use?.later ?? sw?.later ?? 0, preplanned: multi ? preSum : (sprintPre[sid] ?? 0), removed: removedMock[sid] ?? [], sprintPre: multi ? null : (sprintPre[sid] ?? null), earmarked: lane.reduce((a, x) => a + (x.size ?? 0), 0),
    committed: frozen[sid]?.commitment ?? null, products, tickets: lane, candidates: cand, projects,
    matrix: multi ? { projects: PROJECTS.map((p) => ({ id: p.id, name: p.name })), cells: Object.entries(matrixMock[sid] ?? {}).flatMap(([product, row]) => Object.entries(row).map(([project, value]) => ({ product, project, value }))) } : null,
    prod: multi ? {
      people: [{ name: 'Jonas Weber', capacity: 6.2, absence: 1 }, { name: 'Tarek Aydin', capacity: 5.2, absence: 0 }], time: avail, capPercent: 100, available: avail, scaled: false, share: 0, basis: 0,
      demand, demandSet: noT ? prodPT[sid] != null : true, demandAmount: noT ? demand * rate : demandAmount, load, manual: prodPT[sid] ?? null,
      status: load == null ? 'ok' : load > 1 ? 'over' : load > 0.8 ? 'tight' : 'ok',
    } : null,
    frozen: frozen[sid] ? { tickets: frozen[sid]!.keys.length, commitment: frozen[sid]!.commitment } : null,
    assumptions: savedA, running: curId() && nextOf(curId()) === sid ? curId() : '', notes: [],
  };
}

/** Earmarks a ticket of the Plan mock (the Backlog mock keeps its own list); false if unknown. */
export function planEarmark(ticket: string, sprint: string): boolean {
  const x = tickets.find((q) => q.key === ticket);
  if (x) x.sprint = sprint;
  return !!x;
}

/** Sprints whose allocation was frozen in the mock of the sprint pages. */
export const absencesFrozen = new Set<string>();

export const planMock: PlanApi = {
  async PlanSprint(_team, sprint, assume) {
    return view(sprint, assume);
  },
  async RunningTickets() {
    return tickets.filter((x) => x.sprint === '$cur').map((x) => ({ ...ticketOf(x), done: !!x.done, added: !!x.added }) satisfies RunningTicket);
  },
  async RunningHint() {
    return { unresolved: 0, names: [] };
  },
  async WhatIf(_t, sprint, as) {
    return whatIf(sprint, as);
  },
  async SaveAssumption(_t, sprint, as) {
    saved[sprint] = [...(saved[sprint] ?? []).filter((a) => a.label !== as.label), structuredClone(as)];
  },
  async SetPreplanned(_t, sprint, product, value) {
    if (value != null && value < 0) throw new Error('The amount must be a number of 0 or more.');
    (pre[sprint] ??= {})[product] = value as number;
    if (value == null) delete pre[sprint]![product];
  },
  async SetSprintPreplanned(_t, sprint, value) {
    if (value != null && value < 0) throw new Error('The amount must be a number of 0 or more.');
    if (value == null) delete sprintPre[sprint];
    else sprintPre[sprint] = value;
  },
  async SetRemoved(_t, sprint, ticket, removed) {
    const rest = (removedMock[sprint] ?? []).filter((k) => k !== ticket);
    removedMock[sprint] = removed ? [...rest, ticket] : rest;
  },
  async TakeEarmarks(_t, sprint) {
    const v = view(sprint, null);
    for (const p of v.products) (pre[sprint] ??= {})[p.id] = round1(p.earmark);
  },
  async UseDefaults(_t, sprint) {
    const v = view(sprint, null);
    for (const p of v.products) if (p.default != null) (pre[sprint] ??= {})[p.id] = p.default;
  },
  async SetProjectAmount(_t, sprint, project, value) {
    (projAmt[sprint] ??= {})[project] = value ?? 0;
  },
  async SetMatrixCell(_t, sprint, product, project, value) {
    const row = ((matrixMock[sprint] ??= {})[product] ??= {});
    if (value) row[project] = value;
    else delete row[project];
  },
  async UseMatrix(_t, sprint) {
    const cols: Record<string, number> = {};
    for (const [product, row] of Object.entries(matrixMock[sprint] ?? {})) {
      const sum = Object.values(row).reduce((a, v) => a + v, 0);
      for (const [project, v] of Object.entries(row)) cols[project] = (cols[project] ?? 0) + v;
      const cur = (pre[sprint] ??= {})[product];
      if (cur == null || cur < sum) pre[sprint]![product] = sum;
    }
    for (const [project, v] of Object.entries(cols)) (projAmt[sprint] ??= {})[project] = v;
  },
  async SetProductionPT(_t, sprint, value) {
    if (value == null) delete prodPT[sprint];
    else prodPT[sprint] = value;
  },
  async SetProductionPercent(_t, ticket, percent) {
    const x = tickets.find((q) => q.key === ticket);
    if (!x) return;
    x.prod = percent ?? 0;
    x.prodSet = percent != null;
  },
  async FreezePlan(_t, sprint, input: FreezeInput) {
    const noT = mode() === 'none';
    const lane = tickets.filter((x) => input.tickets.includes(x.key));
    const commit = noT ? (input.commitment ?? Object.values(input.amounts).reduce((a, v) => a + v, 0)) : lane.reduce((a, x) => a + (x.est ?? 0), 0);
    frozen[sprint] = { keys: input.tickets, commitment: commit };
    planned[sprint] = noT ? input.amounts : {};
    if (!noT) for (const x of lane) planned[sprint]![x.product] = (planned[sprint]![x.product] ?? 0) + (x.est ?? 0);
    return `${sprint}-planning-20261022-140500.md`;
  },
  async ReopenPlan(_t, sprint) {
    delete frozen[sprint];
    delete planned[sprint];
  },
  async PlanWritePreview(_t, sprint) {
    const fz = frozen[sprint];
    const moves: WriteMove[] = fz
      ? [
          ...fz.keys.filter((k) => !tickets.find((x) => x.key === k)?.sprint.startsWith('$cur')).map((k) => moveOf(k, 'committed', '', sprint)),
          ...(removedMock[sprint] ?? []).map((k) => moveOf(k, 'taken_out', sprint, '')),
        ]
      : [];
    return {
      enabled: true, sprint, removedTarget: 'backlog', moves,
      problems: fz ? [] : ['Freeze the plan first; only the agreed tickets are written to the tracker.'], canUndo: (writeDone[sprint] ?? []).length > 0,
    };
  },
  async PlanWriteApply(_t, sprint, approved) {
    const p = await planMock.PlanWritePreview(_t, sprint);
    const done = p.moves.filter((m) => approved.includes(m.key));
    writeDone[sprint] = [...(writeDone[sprint] ?? []), ...done];
    return { done, failed: [], error: '', canUndo: writeDone[sprint]!.length > 0 };
  },
  async PlanWriteUndo(_t, sprint) {
    const done = (writeDone[sprint] ?? []).map((m): WriteMove => ({ ...m, reason: 'undo', from: m.to, to: m.from }));
    delete writeDone[sprint];
    return { done, failed: [], error: '', canUndo: false };
  },
};

/** Resets the answers (tests). */
export function resetPlanMock(): void {
  tickets = structuredClone(base);
  pre = {}; matrixMock = {}; projAmt = {}; sprintPre = {}; removedMock = {}; prodPT = {}; saved = {}; frozen = {}; planned = {}; writeDone = {};
}

/** One earmark for both pages: the Backlog and the Plan mock keep their own tickets. */
const earmark = {
  async EarmarkTicket(team: string, key: string, sprint: string, note: string): Promise<void> {
    const inPlan = planEarmark(key, sprint);
    try {
      await backlog.EarmarkTicket(team, key, sprint, note);
    } catch (e) {
      if (!inPlan) throw e;
    }
  },
};

export default { ...planMock, ...earmark };
