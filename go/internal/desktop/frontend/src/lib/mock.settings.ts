// Mock answers of the settings area for a browser without the program (demo team "Team Atlas").
// The checks mirror the Go ones loosely: enough for the pages to behave in the browser and in tests.

import type { Result } from './types';
import type {
  Connection,
  Features,
  QueryCheck,
  RuleCheck,
  SettingsApi,
  TeamSettings,
  TrackerInfo,
  TrackerSettings,
} from './types.settings';

let team: TeamSettings = {
  name: 'Team Atlas',
  unit: 'SP',
  unitFrom: '',
  unitChanges: [],
  factor: null,
  forecast: { window: 5, trend: 'flat', referenceCapacity: 67, plannableShare: 80, rounding: 1, horizon: 3, basis: 'plan' },
  lengthDays: 10,
  products: true,
  po: true,
  production: true,
  productionCap: 60,
  projects: true,
  proForma: ['Refinement'],
};

let tracker: TrackerSettings = {
  source: 'tracker',
  kind: 'jira',
  baseUrl: 'https://jira.example.org',
  query: 'project = ATL AND resolution = Unresolved ORDER BY Rank',
  fields: {
    estimate: 'Story Points',
    remaining: '',
    epic: 'Epic Link',
    status: 'Status',
    acceptance: 'Acceptance Criteria',
    product: '',
    project: '',
    refined: '',
    production: '',
  },
  productBy: 'rule',
  projectBy: 'rule',
  refinedBy: 'rule',
  refinedLabel: 'refined',
  refinedRule: '',
  productionBy: 'rule',
  productionLabel: '',
  prodRules: [{ rule: 'component = "Operations"', percent: 100 }],
  ruleFields: [],
  fixedSources: ['epic', 'component', 'label', 'priority', 'type', 'status'],
  writeSprint: false,
  removedTarget: 'backlog',
  writeLabels: false,
  packagePrefix: '',
  token: { host: 'jira.example.org', stored: true, fromEnv: false, keychainUsable: true, variable: 'FORESPRINT_JIRA_TOKEN' },
  tickets: 46,
  imported: new Date(Date.now() - 4 * 60000).toISOString(),
};

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const fail = (text: string) => Promise.reject(new Error(text));

function checkRule(text: string, extra: string[]): RuleCheck {
  const t = text.trim();
  if (!t) return { ok: true, message: '', text: '' };
  const sources = [...tracker.fixedSources, ...extra];
  const names = [...t.matchAll(/(?:^|\s|\()([a-z][a-z0-9_]*)\s*(?:!=|!~|=|~|\s+(?:not\s+)?in\b)/gi)].map((m) => (m[1] ?? "").toLowerCase());
  const unknown = names.find((n) => !sources.includes(n));
  if (unknown) return { ok: false, message: `Unknown field “${unknown}”.`, text: '' };
  if (/(=|~)\s*$/.test(t)) return { ok: false, message: 'A value is missing at the end.', text: '' };
  return { ok: true, message: '', text: t.replace(/\s+/g, ' ') };
}

export const settingsMock: SettingsApi = {
  async TeamSettings() {
    return clone(team);
  },
  async SaveTeamSettings(_team, s) {
    if (s.forecast.window < 1) return fail('The window must be between 1 and 52 sprints.');
    if (!(s.productionCap >= 0 && s.productionCap <= 100)) return fail('The cap of the production time must be between 0 and 100 percent.');
    team = clone(s);
  },
  async TrackerSettings() {
    return clone(tracker);
  },
  async SaveTrackerSettings(_team, s) {
    if (s.source === 'tracker' && s.kind === 'jira' && s.baseUrl && !/^https?:\/\/[^/@]+/.test(s.baseUrl))
      return fail('The address of the tracker must be a web address (https://…).');
    const extra = s.ruleFields.map((f) => f.name);
    for (const r of [s.refinedRule, ...s.prodRules.map((p) => p.rule)]) {
      const c = checkRule(r, extra);
      if (!c.ok) return fail(c.message);
    }
    tracker = clone(s);
    tracker.token = { ...tracker.token, host: (/^https?:\/\/([^/]+)/.exec(s.baseUrl) ?? [])[1] ?? '' };
  },
  async CheckRule(text, extra) {
    return checkRule(text, extra);
  },
  async SetTrackerToken(_t, _b, token) {
    if (!token.trim()) return fail('Paste the token first.');
    tracker = { ...tracker, token: { ...tracker.token, stored: true } };
  },
  async RemoveTrackerToken() {
    tracker = { ...tracker, token: { ...tracker.token, stored: false } };
  },
  async TestTrackerConnection(): Promise<Connection> {
    if (!tracker.token.stored) return { ok: false, message: 'No Jira token found.' };
    return { ok: true, user: 'svc-atlas', message: `Connected to ${tracker.token.host} as svc-atlas.` };
  },
  async TestTrackerQuery(_t, _b, query): Promise<QueryCheck> {
    if (!query.trim()) return { ok: false, message: 'The query is missing.', count: 0 };
    return { ok: true, count: 46, message: 'The query matches 46 tickets.' };
  },
  async TrackerFieldNames() {
    return ['Acceptance Criteria', 'Component/s', 'Epic Link', 'Labels', 'Original Estimate', 'Production share', 'Remaining Estimate', 'Status', 'Story Points'];
  },
  async TeamFeatures(): Promise<Features> {
    return {
      source: tracker.source,
      products: team.products,
      po: team.po,
      production: team.production,
      projects: team.projects || tracker.source !== 'none',
    };
  },
  async TrackerInfo(): Promise<TrackerInfo> {
    return {
      enabled: tracker.source === 'tracker',
      name: tracker.kind === 'csv' ? 'CSV' : 'Jira',
      last: tracker.imported,
      syncing: false,
      failed: '',
    };
  },
  // SetDensity lives in mock.ts next to the other personal settings.
  async SetDensity() {},
  async SyncTracker(): Promise<Result> {
    tracker = { ...tracker, imported: new Date().toISOString() };
    return { ok: true, message: '46 tickets read, no changes.' };
  },
};
