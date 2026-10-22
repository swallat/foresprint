// Mock answers of the Team area for a browser without the program (demo team "Atlas").

import type { AbsencePeriod, EndResult, Owner, PeopleView, Person, Product, ProductsView, RuleOwner, RulePreview, Step, TeamApi } from '../types.team';

const fields = ['epic', 'component', 'label', 'status', 'issue_type', 'priority', 'in_sprint'];

interface DemoTicket {
  key: string;
  estimate: number;
  facts: Record<string, string[]>;
}

const tickets: DemoTicket[] = [
  { key: 'ATL-412', estimate: 5, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-415', estimate: 8, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-417', estimate: 5, facts: { component: ['Mobile App'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-421', estimate: 8, facts: { component: ['Platform'], label: ['login', 'security'], epic: ['Login switch'] } },
  { key: 'ATL-423', estimate: 5, facts: { component: ['Billing'], label: ['xrechnung'], epic: ['E-Invoice'] } },
  { key: 'ATL-426', estimate: 2, facts: { component: ['Portal'] } },
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
  { person: 'felix', from: '2026-11-02', to: '2026-11-03', confirmed: true },
  { person: 'paula', from: '2026-12-14', to: '2027-01-08', confirmed: false },
];

const peopleView = (): PeopleView => ({
  today: new Date().toISOString().slice(0, 10),
  sprintDays: 10,
  production: true,
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
  return { source: 'tracker', today: new Date().toISOString().slice(0, 10), multi: true, legacy: false, products: clone(products), owners: clone(owners) };
};
const step = (undo: number): Step => ({ view: productsView(), undo });

const teamMock: TeamApi = {
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
    const hit = tickets.filter((t) => evaluate(text, t.facts));
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
