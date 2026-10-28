// Mock answers of the Team area for a browser without the program (demo team "Atlas").

import type { AbsencePeriod, CalendarChange, CalendarPreview, CalendarResult, CalendarRow, CalendarView, ChangeNote, ChangeRow, EndResult, LastDay, NamePreview, NamingPreview, Owner, PeopleView, Person, Product, ProductsDefault, ProductsView, RuleOwner, RulePreview, Step, TeamApi } from '../types.team';

const fields = ['epic', 'component', 'label', 'status', 'issue_type', 'priority', 'title', 'in_sprint'];

interface DemoTicket {
  key: string;
  title: string;
  estimate: number;
  facts: Record<string, string[]>;
}

const tickets: DemoTicket[] = [
  { key: 'ATL-412', title: 'Self-service profile page', estimate: 5, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-415', title: 'Self-service password reset', estimate: 8, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-417', title: 'Self-service in the mobile app', estimate: 5, facts: { component: ['Mobile App'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-421', title: 'Switch login to single sign-on', estimate: 8, facts: { component: ['Platform'], label: ['login', 'security'], epic: ['Login switch'] } },
  { key: 'ATL-423', title: 'Export invoices as XRechnung', estimate: 5, facts: { component: ['Billing'], label: ['xrechnung'], epic: ['E-Invoice'] } },
  { key: 'ATL-426', title: 'Fix portal footer links', estimate: 2, facts: { component: ['Portal'] } },
];

// A small reader for the rule language: field = "value", field ~ "part", AND, OR. The real
// parser is in Go; this is enough to make the editor testable in a browser.
function evaluate(text: string, facts: Record<string, string[]>): boolean {
  const ors = text.split(/\s+OR\s+/i);
  return ors.some((part) =>
    part.split(/\s+AND\s+/i).every((cond) => {
      const m = /^\s*\(*\s*(\w+)\s*(=|!=|~|!~)\s*"?([^")]*)"?\s*\)*\s*$/.exec(cond);
      if (!m) return false;
      const [, field = '', op = '=', value = ''] = m;
      const have = (facts[field] ?? []).map((v) => v.toLowerCase());
      const want = value.toLowerCase();
      const hit = op.endsWith('~') ? have.some((v) => v.includes(want)) : have.includes(want);
      return op.startsWith('!') ? !hit : hit;
    }),
  );
}

// Arguments may be Svelte state proxies, which structuredClone refuses; JSON is what the bridge sends too.
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const person = (id: string, name: string, from: string, fte: number, over: Partial<Person> = {}): Person => ({
  id,
  name,
  kind: 'member',
  production: false,
  used: true,
  memberships: [{ from, to: '', fte }],
  ...over,
});

let people: Person[] = [
  person('jonas', 'Jonas Weber', '2024-02-01', 1, { production: true }),
  person('mira', 'Mira Schulz', '2024-02-01', 1),
  person('tarek', 'Tarek Aydin', '2025-04-01', 0.8, {
    production: true,
    memberships: [
      { from: '2025-04-01', to: '2025-12-31', fte: 1 },
      { from: '2026-01-01', to: '', fte: 0.8 },
    ],
  }),
  person('paula', 'Paula Neumann', '2024-09-01', 1),
  person('felix', 'Felix Braun', '2026-07-01', 0.5, { kind: 'guest' }),
  person('sara', 'Sara Klein', '2024-02-01', 1, { production: true, memberships: [{ from: '2024-02-01', to: '2026-12-22', fte: 1 }] }),
  person('ole', 'Ole Brandt', '2024-02-01', 1, { production: true, memberships: [{ from: '2024-02-01', to: '2026-09-29', fte: 1 }] }),
  person('nina', 'Nina Roth', '2025-01-01', 0.5, { memberships: [{ from: '2025-01-01', to: '2026-06-30', fte: 0.5 }] }),
];

let absences: AbsencePeriod[] = [
  { person: 'mira', from: '2026-11-16', to: '2026-11-20', confirmed: false },
  { person: 'felix', from: '2026-08-10', to: '2026-08-14', confirmed: true },
  { person: 'felix', from: '2026-11-02', to: '2026-11-03', confirmed: true },
  { person: 'paula', from: '2026-12-14', to: '2027-01-08', confirmed: false },
];

const peopleView = (): PeopleView => ({
  today: new Date().toISOString().slice(0, 10),
  newFrom: new Date().toISOString().slice(0, 10),
  sprintDays: 10,
  production: true,
  country: 'DE',
  people: clone(people),
});

const product = (id: string, name: string, po: string, share: number | null, rule: string, over: Partial<Product> = {}): Product => ({
  id,
  name,
  po,
  share,
  rule,
  from: '',
  to: '',
  tickets: 0,
  points: 0,
  ended: false,
  used: true,
  ...over,
});

let products: Product[] = [
  product('portal', 'Customer portal', 'kim', 0.35, 'component = "Portal"', { tickets: 3, points: 15 }),
  product('billing', 'Billing', 'kim', 0.2, 'component = "Billing"', { tickets: 1, points: 5 }),
  product('mobile', 'Mobile app', 'lea', 0.25, 'component = "Mobile App" AND label != "internal"', { tickets: 1, points: 5 }),
  product('platform', 'Platform', 'lea', 0.2, 'component = "Platform" OR label = "team-platform"', { tickets: 1, points: 8 }),
  product('legacy', 'Legacy system', 'kim', 0, '', { ended: true, to: '2026-09-15' }),
];
let owners: Owner[] = [
  { id: 'kim', name: 'Kim Berger', person: '', products: 3, inTeam: false, fte: 0 },
  { id: 'lea', name: 'Lea Hoffmann', person: '', products: 2, inTeam: false, fte: 0 },
];
let lastUndo: { token: number; products: Product[]; owners: Owner[] } | undefined;
let tokens = 0;

function remember(): number {
  tokens += 1;
  lastUndo = { token: tokens, products: clone(products), owners: clone(owners) };
  return tokens;
}

const productsView = (): ProductsView => {
  const count = (id: string) => owners.length && products.filter((p) => p.po === id).length;
  owners = owners.map((o) => ({ ...o, products: count(o.id) as number }));
  const defaults: ProductsDefault[] = [
    { sprint: '2026.19', plan: 41.6, running: true },
    { sprint: '2026.20', plan: 44, running: false },
    { sprint: '2026.21', plan: 38.4, running: false },
    { sprint: '2026.22', plan: null, running: false },
  ].map(({ sprint, plan, running }) => {
    const live = products.filter((p) => !p.ended);
    const fixed = live.reduce((n, p) => n + (p.share === null ? 0 : Math.round((plan ?? 0) * p.share * 1000) / 1000), 0);
    const rest = live.filter((p) => p.share === null);
    const even = Math.max((plan ?? 0) - fixed, 0) / (rest.length || 1);
    return {
      sprint,
      running,
      roadmap: false,
      plan,
      available: plan,
      roadmapShare: 0,
      fixed,
      rest: rest.length,
      values: Object.fromEntries(live.filter(() => plan !== null).map((p) => [p.id, Math.round(p.share === null ? even : (plan as number) * p.share)])),
    };
  });
  return { source: 'tracker', today: new Date().toISOString().slice(0, 10), multi: true, legacy: false, products: clone(products), owners: clone(owners), defaults };
};
const step = (undo: number): Step => ({ view: productsView(), undo });

// ---- sprint calendar: 14-day sprints around the demo day, Atlas numbering 2026.18 and on ----
const DAY = 86400000;
const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const ms = (d: string) => Date.parse(`${d}T00:00:00Z`);
const demoToday = '2026-10-22';
const hol: Record<string, string> = { '2026-12-25': 'Weihnachtstag', '2026-12-26': 'Zweiter Weihnachtstag', '2027-01-01': 'Neujahr' };
let cal: { id: string; start: string; last: string; saved: boolean }[] = Array.from({ length: 10 }, (_, i) => {
  const start = ms('2026-09-30') + (i - 1) * 14 * DAY;
  return { id: `2026.${19 + i}`, start: iso(start), last: iso(start + 13 * DAY), saved: i < 5 };
});
let pattern = '';
const workdays = (a: string, b: string) => {
  let n = 0;
  for (let d = ms(a); d <= ms(b); d += DAY) {
    const wd = new Date(d).getUTCDay();
    if (wd !== 0 && wd !== 6 && !hol[iso(d)]) n++;
  }
  return n;
};
const calState = (r: { start: string; last: string; saved: boolean }): CalendarRow['state'] =>
  r.last < demoToday ? 'finished' : r.start <= demoToday ? 'running' : r.saved ? 'open' : 'planned';
const calView = (): CalendarView => ({
  today: demoToday,
  country: 'DE',
  region: 'NW',
  rows: cal.map((r) => ({
    id: r.id,
    start: r.start,
    last: r.last,
    workdays: workdays(r.start, r.last),
    holidays: Object.entries(hol).filter(([d]) => d >= r.start && d <= r.last).map(([date, name]) => ({ date, name })),
    state: calState(r),
    locked: calState(r) === 'finished',
    saved: r.saved,
  })),
  naming: pattern ? [{ from: '', pattern }] : [],
  pattern,
  placeholders: ['JJJJ', 'JJ', 'NN', 'N', 'LFD', 'Q', 'MM', 'KW'],
  proForma: [],
});
function isoWeek(d: string): number {
  const t = new Date(`${d}T00:00:00Z`);
  const day = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - day + 3);
  const first = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((t.getTime() - first.getTime()) / DAY - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
}
function nameAll(pat: string): string[] {
  let nn = 0;
  let year = '';
  return cal.map((r, i) => {
    const y = r.start.slice(0, 4);
    nn = i === 0 ? Number(r.id.split('.')[1]) || 1 : y !== year ? 1 : nn + 1;
    year = y;
    const m = Number(r.start.slice(5, 7));
    const pad = (v: number) => String(v).padStart(2, '0');
    return pat
      .replace(/\{JJJJ\}/g, y)
      .replace(/\{JJ\}/g, y.slice(2))
      .replace(/\{NN\}/g, pad(nn))
      .replace(/\{N\}/g, String(nn))
      .replace(/\{LFD\}/g, String(40 + i + 1))
      .replace(/\{Q\}/g, String(Math.ceil(m / 3)))
      .replace(/\{MM\}/g, pad(m))
      .replace(/\{KW\}/g, pad(isoWeek(r.start)));
  });
}
function namingPreview(pat: string, from: string, all: boolean): NamingPreview {
  const names = nameAll(pat);
  const firstOpen = cal.findIndex((r) => calState(r) !== 'finished' && calState(r) !== 'running');
  const fromIdx = all ? 0 : from ? cal.findIndex((r) => r.id === from) : firstOpen;
  const rows: NamePreview[] = cal.map((r, i) => ({
    index: i,
    start: r.start,
    old: r.id,
    new: names[i] ?? r.id,
    locked: calState(r) === 'finished' && !all,
    saved: r.saved,
    changes: i >= fromIdx && names[i] !== r.id,
  }));
  const final = rows.map((r) => (r.changes ? r.new : r.old));
  return {
    rows,
    duplicate: final.find((n, i) => final.indexOf(n) !== i) ?? '',
    noNumber: !/\{(NN|N|LFD|KW)\}/.test(pat),
    problem: /\{(?!JJJJ\}|JJ\}|NN\}|N\}|LFD\}|Q\}|MM\}|KW\})/.test(pat) ? '{…}' : '',
    count: rows.filter((r) => r.changes).length,
  };
}
let calUndo: { token: number; cal: typeof cal } | undefined;
function calResult(moved: number, undo: number): CalendarResult {
  return { view: calView(), moved, undo };
}

type CalRow = (typeof cal)[number];
// The mock of a calendar change: the same rules as the Go code, without the numbering choice.
function planCalChange(ch: CalendarChange): { rows: ChangeRow[]; next: CalRow[]; preview: CalendarPreview } {
  const old = clone(cal);
  const k = old.findIndex((r) => r.id === ch.id);
  const row = old[k];
  const empty = (problem: string) => ({ rows: [], next: old, preview: { rows: [], lost: [], free: [], target: '', via: '', forced: false, mode: ch.mode, namingChoice: false, problem } });
  if (!row) return empty('Enter a valid last day.');
  if (calState(row) === 'finished') return empty('A finished sprint is locked.');
  let idx = k;
  let last = ch.date;
  let mode = ch.mode;
  let via = '';
  let forced = false;
  let kind = ch.kind;
  if (kind === 'remove') {
    if (calState(row) === 'running') return empty('The running sprint cannot be removed.');
    const prev = old[k - 1];
    if (!prev || calState(prev) === 'finished') return empty('The sprint before is finished and locked, so it cannot take over the days.');
    idx = k - 1;
    last = row.last;
    mode = 'keep';
    via = prev.id;
    kind = 'last';
  } else if (kind === 'rhythm') {
    forced = true;
    mode = 'shift';
  } else if (kind === 'start') {
    const prev = old[k - 1];
    if (prev && calState(prev) !== 'finished') {
      idx = k - 1;
      last = iso(ms(ch.date) - DAY);
      via = prev.id;
      kind = 'last';
    } else {
      if (prev && ch.date <= prev.last) return empty(`The start is before the end of the finished sprint ${prev.id}.`);
      forced = true;
      mode = 'shift';
    }
  }
  const next = clone(old);
  const lost: string[] = [];
  const free: string[] = [];
  let target = '';
  const gone = new Set<string>();
  if (kind === 'rhythm') {
    let start = ms(next[idx]!.start);
    for (let j = idx; j < next.length; j++) {
      next[j]!.start = iso(start);
      next[j]!.last = iso(start + 13 * DAY);
      start += 14 * DAY;
    }
  } else if (forced) {
    const delta = (ms(ch.date) - ms(next[idx]!.start)) / DAY;
    for (let j = idx; j < next.length; j++) {
      next[j]!.start = iso(ms(next[j]!.start) + delta * DAY);
      next[j]!.last = iso(ms(next[j]!.last) + delta * DAY);
    }
  } else {
    const base = next[idx]!;
    if (last < base.start) return empty(`Sprint ${base.id}: last day is before the start ${base.start}`);
    base.last = last;
    for (let j = idx + 1; j < next.length; j++) {
      const cur = next[j]!;
      if (mode === 'shift') {
        const len = ms(cur.last) - ms(cur.start);
        cur.start = iso(ms(next[j - 1]!.last) + DAY);
        cur.last = iso(ms(cur.start) + len);
      } else if (cur.last <= last) {
        gone.add(cur.id);
        (cur.saved ? lost : free).push(cur.id);
      } else if (!target) {
        target = cur.id;
        cur.start = iso(ms(last) + DAY);
      }
    }
  }
  const rows: ChangeRow[] = next.slice(idx).map((r) => {
    const o = old.find((x) => x.id === r.id)!;
    const notes: ChangeNote[] = [];
    const ds = (ms(r.start) - ms(o.start)) / DAY;
    const de = (ms(r.last) - ms(o.last)) / DAY;
    if (gone.has(r.id)) notes.push({ kind: 'gone', days: 0, from: '' });
    else if (ds !== 0 && ds === de) notes.push({ kind: 'moved', days: ds, from: '' });
    else if (ds !== 0) notes.push({ kind: ds > 0 ? 'starts-later' : 'starts-earlier', days: Math.abs(ds), from: '' });
    else if (de !== 0) notes.push({ kind: de > 0 ? 'longer' : 'shorter', days: Math.abs(de), from: '' });
    return { id: r.id, old: r.id, oldStart: o.start, oldLast: o.last, start: r.start, last: r.last, workdays: workdays(r.start, r.last), gone: gone.has(r.id), saved: r.saved, notes };
  });
  return { rows, next: next.filter((r) => !gone.has(r.id)), preview: { rows, lost, free, target, via, forced, mode, namingChoice: false, problem: '' } };
}

export const teamMock: TeamApi = {
  async Calendar() {
    return calView();
  },
  async PreviewCalendarChange(_team: string, ch: CalendarChange) {
    return planCalChange(ch).preview;
  },
  async ApplyCalendarChange(_team: string, ch: CalendarChange) {
    const plan = planCalChange(ch);
    if (plan.preview.problem) throw new Error(plan.preview.problem);
    const before = clone(cal);
    cal = plan.next;
    calUndo = { token: ++tokens, cal: before };
    return calResult(plan.rows.filter((r) => r.notes.length).length, calUndo.token);
  },
  async SaveLastDays(_team: string, changes: LastDay[]) {
    const before = clone(cal);
    let moved = 0;
    for (const c of changes) {
      const k = cal.findIndex((r) => r.id === c.id);
      const row = cal[k];
      if (!row) throw new Error('Enter a valid last day.');
      if (calState(row) === 'finished') throw new Error('A finished sprint is locked.');
      if (c.last < row.start) throw new Error(`Sprint ${row.id}: last day is before the start ${row.start}`);
      row.last = c.last;
      for (let j = k + 1; j < cal.length; j++) {
        const prev = cal[j - 1]!;
        const cur = cal[j]!;
        const len = ms(cur.last) - ms(cur.start);
        const start = iso(ms(prev.last) + DAY);
        if (start !== cur.start) moved++;
        cur.start = start;
        cur.last = iso(ms(start) + len);
      }
    }
    calUndo = { token: ++tokens, cal: before };
    return calResult(moved, calUndo.token);
  },
  async NamingPreview(_team: string, pat: string, from: string, all: boolean) {
    return namingPreview(pat, from, all);
  },
  async ApplyNaming(_team: string, pat: string, from: string, all: boolean) {
    const prev = namingPreview(pat, from, all);
    if (prev.problem) throw new Error(`unknown placeholder ${prev.problem} in sprint naming pattern`);
    for (const r of prev.rows) if (r.changes && cal[r.index]) cal[r.index]!.id = r.new;
    pattern = pat;
    return calResult(prev.count, 0);
  },
  async RenameSprint(_team: string, id: string, newId: string) {
    if (!newId.trim()) throw new Error('Please enter a new sprint ID.');
    if (cal.some((r) => r.id === newId && r.id !== id)) throw new Error(`Sprint ID '${newId}' is already taken (by an earlier sprint).`);
    const row = cal.find((r) => r.id === id);
    if (row) row.id = newId.trim();
    return calResult(0, 0);
  },
  async Products() {
    return productsView();
  },
  async SaveProducts(_team, list) {
    const before = new Map(products.map((p) => [p.id, p]));
    for (const p of products) {
      if (p.used && !list.some((x) => x.id === p.id)) throw new Error(`${p.name} has history and cannot be deleted. End it instead.`);
    }
    products = list.map((p) => ({ ...clone(p), id: p.id || p.name.toLowerCase().replace(/\s+/g, '-'), used: before.get(p.id)?.used ?? false }));
    return productsView();
  },
  async EndProduct(_team, id, lastDay, shares, target): Promise<EndResult> {
    const sum = Object.values(shares).reduce((n, v) => n + v, 0);
    if (Math.abs(sum - 1) > 0.005) throw new Error(`The shares add up to ${Math.round(sum * 100)} percent, not 100.`);
    const undo = remember();
    const ended = products.find((p) => p.id === id);
    const moved = target && ended ? ended.tickets : 0;
    products = products.map((p) => {
      if (p.id === id) return { ...p, ended: true, to: lastDay, share: 0, rule: '', tickets: 0, points: 0 };
      if (p.id === target && ended) return { ...p, tickets: p.tickets + ended.tickets, points: p.points + ended.points };
      return { ...p, share: shares[p.id] ?? p.share };
    });
    return { view: productsView(), moved, undo };
  },
  async ResumeProduct(_team, id) {
    const undo = remember();
    products = products.map((p) => (p.id === id ? { ...p, ended: false, to: '', share: 0 } : p));
    return step(undo);
  },
  async AddOwner(_team, name) {
    const undo = remember();
    owners = [...owners, { id: name.toLowerCase().replace(/\s+/g, '-'), name, person: '', products: 0, inTeam: false, fte: 0 }];
    return step(undo);
  },
  async RenameOwner(_team, id, name) {
    const undo = remember();
    owners = owners.map((o) => (o.id === id ? { ...o, name } : o));
    return step(undo);
  },
  async RemoveOwner(_team, id, handover) {
    if (owners.length < 2) throw new Error('The only PO cannot be removed.');
    const undo = remember();
    products = products.map((p) => (p.po === id ? { ...p, po: handover[p.id] ?? p.po } : p));
    owners = owners.filter((o) => o.id !== id);
    return step(undo);
  },
  async SetOwnerInTeam(_team, id, inTeam, fte) {
    const undo = remember();
    owners = owners.map((o) => (o.id === id ? { ...o, inTeam, fte: inTeam ? fte : 0, person: inTeam ? id : '' } : o));
    return step(undo);
  },
  async Undo(_team, token) {
    if (calUndo && calUndo.token === token) {
      cal = calUndo.cal;
      calUndo = undefined;
      return;
    }
    if (!lastUndo || lastUndo.token !== token) throw new Error('This change can no longer be undone.');
    products = lastUndo.products;
    owners = lastUndo.owners;
    lastUndo = undefined;
  },
  async People() {
    return peopleView();
  },
  async SavePeople(_team, list) {
    const before = new Map(people.map((p) => [p.id, p]));
    for (const p of before.values()) {
      if (p.used && !list.some((x) => x.id === p.id)) throw new Error(`${p.name} stands in sprints and cannot be removed.`);
    }
    people = list.map((p) => ({ ...clone(p), id: p.id || p.name.toLowerCase().replace(/\s+/g, '-'), used: before.get(p.id)?.used ?? false }));
    return peopleView();
  },
  async AbsencePeriods() {
    return clone(absences);
  },
  async SaveAbsencePeriods(_team, list) {
    absences = clone(list);
    return clone(absences);
  },
  async RuleFields() {
    return fields;
  },
  async CheckRule(_team: string, text: string, _owner: RuleOwner): Promise<RulePreview> {
    const base = { fields, pos: -1, sample: [] as string[], clash: 0, moved: 0, matches: 0, points: 0 };
    if (!text.trim()) return { ...base, valid: false, error: 'The expression is empty', pos: 0 };
    const first = (/^\s*\(*\s*(\w+)/.exec(text)?.[1] ?? '').toLowerCase();
    if (!fields.includes(first)) {
      return { ...base, valid: false, error: `Unknown field '${first}'`, pos: 0 };
    }
    const hit = tickets.filter((t) => evaluate(text, { ...t.facts, title: [t.title] }));
    return {
      ...base,
      valid: true,
      normalized: text.trim(),
      matches: hit.length,
      points: hit.reduce((n, t) => n + t.estimate, 0),
      sample: hit.slice(0, 5).map((t) => t.key),
    };
  },
};

export default teamMock;
