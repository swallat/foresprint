// Mock of the Backlog bindings for a browser without the program: the invented demo team
// "Team Atlas". The ticket source can be chosen with ?source=tracker|packages|none in the
// address (before the #), for screenshots and development.

import type { SprintInfo } from '../types';
import { sprints as demoSprints } from './shared';
import type {
  BacklogApi,
  BacklogLane,
  BacklogTicket,
  BacklogView,
  Named,
  SizeSource,
  TicketDetail,
  TicketSource,
  WorkPackageInput,
} from '../types.backlog';

interface Row extends TicketDetail {
  rank: number;
}

const products: Named[] = [
  { id: 'portal', name: 'Customer portal' },
  { id: 'billing', name: 'Billing' },
  { id: 'mobile', name: 'Mobile app' },
  { id: 'platform', name: 'Platform' },
];
const projects: Named[] = [
  { id: 'ss2', name: 'Self-service 2.0' },
  { id: 'einv', name: 'E-invoice' },
  { id: 'login', name: 'Login switch' },
];

function source(): TicketSource {
  const v = new URLSearchParams(location.search).get('source');
  return v === 'packages' || v === 'none' ? v : 'tracker';
}

function seed(prefix: string): Row[] {
  const defs: [string, string, string, string, number | null, boolean, string, string][] = [
    // key number, title, product, project, estimate, refined, status, priority
    ['415', 'Show open invoices on the start page', 'billing', 'einv', 5, true, 'In review', 'High'],
    ['418', 'Export invoices as XRechnung', 'billing', 'einv', 8, true, 'New', 'Highest'],
    ['421', 'Register with a magic link', 'portal', 'ss2', 5, true, 'New', 'High'],
    ['422', 'Reset password from the app', 'mobile', 'login', 3, true, 'New', 'High'],
    ['424', 'Move the login service to the new identity provider', 'platform', 'login', 13, false, 'New', 'Highest'],
    ['426', 'Push notification for new invoices', 'mobile', 'ss2', 5, false, 'New', 'Medium'],
    ['431', 'Self-service: change the delivery address', 'portal', 'ss2', 8, true, 'New', 'Medium'],
    ['433', 'Dark mode for the customer portal', 'portal', '', 3, true, 'New', 'Low'],
    ['435', 'Show the app version in the footer', 'mobile', '', 1, true, 'New', 'Low'],
    ['440', 'Rotate certificates before they expire', 'platform', '', null, false, 'New', 'Medium'],
    ['446', 'Archive old invoices after ten years', 'billing', '', 5, false, 'New', 'Medium'],
    ['448', 'Alert when the nightly job runs late', 'platform', '', 3, false, 'New', 'Low'],
    ['452', 'Split the invoice PDF by cost centre', 'billing', 'einv', null, false, 'New', 'Medium'],
    ['455', 'Faster loading of the order list', 'portal', '', 5, true, 'New', 'Medium'],
  ];
  return defs.map(([n, title, product, project, size, refined, status, priority], i) => {
    const key = `${prefix}-${n}`;
    const hint = n === '440' ? 'none' : n === '446' ? 'several' : n === '448' ? 'none' : '';
    return {
      key,
      title,
      status,
      type: 'Story',
      priority,
      assignee: '',
      url: prefix === 'AP' ? '' : `https://jira.example.com/browse/${key}`,
      size,
      sizeSource: (size == null ? 'none' : refined ? 'refined' : 'rough') as SizeSource,
      refined,
      refinedUnclear: false,
      product: hint ? '' : product,
      project,
      productSet: false,
      projectSet: false,
      ruleHint: prefix === 'AP' ? '' : (hint as BacklogTicket['ruleHint']),
      ruleProducts: n === '446' ? ['portal', 'mobile'] : [],
      earmark: '',
      trackerSprint: '',
      production: null,
      epic: project ? (projects.find((p) => p.id === project)?.name ?? '') : '',
      labels: n === '418' ? ['xrechnung'] : [],
      dependsOn: n === '421' ? [`${prefix}-424`] : [],
      blocked: false,
      description:
        n === '421'
          ? 'Customers sign in with a link they get by e-mail. The link works once and for 15 minutes.\n\nThe old password stays as a second option.'
          : '',
      acceptance: n === '421' ? 'The link works once.\nAn expired link shows a clear message.\nSupport can see failed attempts.' : '',
      subtasks: n === '421' ? [{ title: 'Design the e-mail', done: true }, { title: 'Rate limit per address', done: false }] : [],
      comments: n === '421' ? [{ author: 'Mira Schulz', at: '2026-10-20T09:12:00Z', text: 'Security wants a short look before we start.' }] : [],
      dependencies: [],
      components: [],
      estimate: size,
      remaining: null,
      note: '',
      editable: prefix === 'AP',
      sprints: [],
      statuses: ['New', 'In progress', 'In review', 'Done'],
      types: ['Story', 'Bug', 'Task'],
      priorities: ['Highest', 'High', 'Medium', 'Low', 'Lowest'],
      people: ['Jonas Weber', 'Mira Schulz', 'Tarek Aydin'],
      rank: i,
    };
  });
}

// Arguments reach the real program as JSON; the mock sees them the same way (no state proxies).
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function createBacklogMock(sprints: () => SprintInfo[]): BacklogApi {
  const kind = source();
  const prefix = kind === 'packages' ? 'AP' : 'ATL';
  const rows: Row[] = seed(prefix);
  // ?n=3000 adds many tickets, to try the list with a long backlog
  const extra = Number(new URLSearchParams(location.search).get('n')) || 0;
  for (let i = 0; i < extra; i++) {
    const base = rows[i % 14]!;
    rows.push({ ...structuredClone(base), key: `${prefix}-${1000 + i}`, title: `${base.title} (${i})`, rank: 100 + i, earmark: '', dependsOn: [] });
  }
  const forecast = [38, 42, 41, 36];
  const proForma = ['Refinement'];
  const tracked = new Map<string, string>(); // ticket -> pro-forma sprint in the tracker
  const placed = new Map<string, string>(); // ticket -> pro-forma sprint chosen here
  if (kind === 'tracker') {
    const r = rows.find((x) => x.key === 'ATL-431');
    if (r) {
      r.trackerSprint = 'Refinement';
      tracked.set(r.key, 'Refinement');
    }
  }

  const upcoming = () => sprints().filter((s) => s.state === 'future').slice(0, 3);
  const plain = (r: Row): BacklogTicket => {
    const { rank: _rank, description: _d, acceptance: _a, subtasks: _s, comments: _c, dependencies: _dp, components: _co, estimate: _e, remaining: _r, note: _n, editable: _ed, sprints: _sp, statuses: _st, types: _t, priorities: _pr, people: _pe, ...row } = r;
    void [_rank, _d, _a, _s, _c, _dp, _co, _e, _r, _n, _ed, _sp, _st, _t, _pr, _pe];
    return { ...row, blocked: blocked(r) };
  };
  const blocked = (r: Row) =>
    !!r.earmark &&
    r.dependsOn.some((k) => {
      const d = rows.find((x) => x.key === k);
      return !!d && (!d.earmark || d.earmark >= r.earmark);
    });
  const find = (key: string) => {
    const r = rows.find((x) => x.key === key);
    if (!r) throw new Error(`Ticket ${key} not found.`);
    return r;
  };

  return {
    async Backlog() {
      const lanes: BacklogLane[] = upcoming().map((s, i) => ({
        sprint: s.id,
        start: s.start,
        end: s.end,
        plan: forecast[i] ?? null,
        absences: (['announced', 'unknown', 'unknown'] as const)[i] ?? 'unknown',
        tickets: rows.filter((r) => r.earmark === s.id).sort((a, b) => a.rank - b.rank).map(plain),
      }));
      const inLane = new Set(lanes.flatMap((l) => l.tickets.map((t) => t.key)));
      const where = (r: Row) => placed.get(r.key) ?? tracked.get(r.key) ?? '';
      const pro = (name: string) => rows.filter((r) => where(r) === name).map(plain);
      const view: BacklogView = {
        source: kind,
        tracker: kind === 'tracker' ? 'Jira' : '',
        unit: 'SP',
        products,
        projects,
        tickets:
          kind === 'none'
            ? []
            : rows
                .filter((r) => !inLane.has(r.key) && !where(r))
                .sort((a, b) => a.rank - b.rank)
                .map(plain),
        lanes: kind === 'none' ? [] : lanes,
        proForma: kind === 'none' ? [] : proForma.map((name) => ({ name, tickets: pro(name) })),
        imported: new Date(Date.now() - 3 * 60000).toISOString(),
        multi: true,
        production: true,
        cycles: [],
        adjust: [...placed].map(([key, to]) => ({ key, title: find(key).title, url: '', from: tracked.get(key) ?? '', to })),
      };
      return clone(view);
    },
    async Ticket(_team, key) {
      const r = find(key);
      const detail: TicketDetail = {
        ...clone(r),
        blocked: blocked(r),
        sprints: upcoming().map((s) => s.id),
        dependencies: r.dependsOn.map((k) => ({
          key: k,
          title: rows.find((x) => x.key === k)?.title ?? '',
          earmark: rows.find((x) => x.key === k)?.earmark ?? '',
        })),
      };
      return detail;
    },
    async EarmarkTicket(_team, key, sprint, note) {
      const r = find(key);
      r.earmark = sprint;
      if (sprint && (placed.get(key) ?? tracked.get(key))) {
        if (tracked.has(key)) placed.set(key, '');
        else placed.delete(key);
      }
      if (note) r.note = note;
    },
    async MoveToProForma(_team, key, name) {
      const r = find(key);
      if (name && !proForma.includes(name)) throw new Error(`${name} is not a pro-forma sprint of this team.`);
      if (name === (tracked.get(key) ?? '')) placed.delete(key);
      else placed.set(key, name);
      if (name) r.earmark = '';
    },
    async SetEarmarkNote(_team, key, note) {
      find(key).note = note;
    },
    async SetEstimate(_team, key, value) {
      const r = find(key);
      if (kind === 'tracker' && r.estimate != null) throw new Error(`The estimate of ${key} comes from the tracker.`);
      r.size = value;
      r.sizeSource = value == null ? 'none' : kind === 'packages' ? (r.refined ? 'refined' : 'rough') : 'manual';
      if (kind === 'packages') r.estimate = value;
    },
    async SetRefined(_team, key, refined) {
      if (kind !== 'packages') throw new Error(`${key} is refined in the tracker.`);
      const r = find(key);
      r.refined = refined;
      r.sizeSource = r.size == null ? 'none' : refined ? 'refined' : 'rough';
    },
    async SetAssignment(_team, key, product, project, daily) {
      const r = find(key);
      if (product) r.product = product;
      r.project = daily ? '' : project || r.project;
      r.productSet = !!product && kind === 'tracker';
      r.projectSet = (!!project || daily) && kind === 'tracker';
      if (product) r.ruleHint = '';
    },
    async SetProduction(_team, key, percent) {
      find(key).production = percent;
    },
    async SaveWorkPackage(_team, raw: WorkPackageInput) {
      const input = clone(raw);
      let r = rows.find((x) => x.key === input.key);
      if (!input.title.trim()) throw new Error('A work package needs a title.');
      if (!r) {
        const n = Math.max(0, ...rows.map((x) => Number(x.key.split('-')[1]) || 0)) + 1;
        r = { ...seed('AP')[0]!, key: `AP-${n}`, rank: Math.min(...rows.map((x) => x.rank)) - 1, earmark: '', description: '', acceptance: '', subtasks: [], comments: [], dependsOn: [], labels: [] } as Row;
        rows.push(r);
      }
      Object.assign(r, {
        title: input.title.trim(),
        status: input.status,
        type: input.type,
        priority: input.priority,
        assignee: input.assignee,
        product: input.product,
        project: input.project,
        size: input.estimate,
        estimate: input.estimate,
        refined: input.refined,
        sizeSource: input.estimate == null ? 'none' : input.refined ? 'refined' : 'rough',
        labels: input.labels,
        description: input.description,
        acceptance: input.acceptance,
        subtasks: input.subtasks,
        dependsOn: input.dependsOn,
        comments: input.comments,
        editable: true,
        url: '',
      });
      return r.key;
    },
    async DeleteWorkPackage(_team, key) {
      const i = rows.findIndex((x) => x.key === key);
      if (i >= 0) rows.splice(i, 1);
      rows.forEach((x) => (x.dependsOn = x.dependsOn.filter((k) => k !== key)));
    },
    async MoveWorkPackage(_team, key, before, after) {
      const order = [...rows].sort((a, b) => a.rank - b.rank).filter((x) => x.key !== key);
      const moving = rows.find((x) => x.key === key);
      if (!moving || key === before) return;
      const found = before === '' ? order.length : order.findIndex((x) => x.key === before);
      const at = found + (after && before !== '' ? 1 : 0);
      if (found < 0) throw new Error(`${before} is not in the backlog.`);
      order.splice(at, 0, moving);
      order.forEach((x, i) => (x.rank = (i + 1) * 10));
    },
  };
}

export default createBacklogMock(() => demoSprints);
