// Answers for a browser without the program (npm run dev, tests): the invented demo team
// "Team Atlas" (no real data, no real names). Same methods as the Go API.

import type { Api } from './api';
import { teamMock } from './mock.team';
import type { Prefs, Result, SprintInfo, Status } from './types';
import type { TodayData, TodaySprint } from './types.today';

const sprints: SprintInfo[] = Array.from({ length: 14 }, (_, i) => {
  const n = 12 + i;
  const start = new Date(Date.UTC(2026, 0, 5 + i * 14));
  const end = new Date(start.getTime() + 11 * 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const now = Date.now();
  return {
    id: `2026.${n}`,
    start: iso(start),
    end: iso(end),
    state: end.getTime() < now ? 'past' : start.getTime() <= now ? 'current' : 'future',
  } satisfies SprintInfo;
});

let prefs: Prefs = {
  language: navigator.language.startsWith('de') ? 'de' : 'en',
  languages: [
    { code: 'de', label: 'Deutsch' },
    { code: 'en', label: 'English' },
  ],
  theme: 'system',
  themes: [
    { code: 'system', label: 'As system' },
    { code: 'light', label: 'Light' },
    { code: 'dark', label: 'Dark' },
  ],
  dataDir: '/demo/teams',
  recentDataDirs: ['/demo/teams'],
};

let incoming = 2;
const status = (): Status => ({
  storage: incoming > 0 ? 'incoming' : 'saved',
  detail: '',
  incoming,
  findings: 1,
  tracker: { enabled: true, name: 'Jira', last: new Date(Date.now() - 4 * 60000).toISOString(), syncing: false, failed: '' },
});

function today(): TodayData {
  const day = new Date().toISOString().slice(0, 10);
  const at = Math.max(0, sprints.findIndex((s) => s.state === 'current'));
  const left = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.end) - Date.now()) / 86400000));
  const toStart = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.start) - Date.now()) / 86400000));
  const [cur, nxt, later] = [sprints[at], sprints[at + 1], sprints[at + 2]];
  const out: TodaySprint[] = [];
  if (cur) out.push({ ...cur, state: 'running', daysLeft: left(cur), daysToStart: 0, steps: [{ key: 'review', state: 'open', detail: '' }] });
  if (nxt)
    out.push({
      ...nxt,
      state: 'next',
      daysLeft: 0,
      daysToStart: toStart(nxt),
      steps: [
        { key: 'absences', state: 'open', detail: 'announced only (3 people)' },
        { key: 'preplan', state: 'open', detail: '2 of 4 products' },
        { key: 'plan', state: 'open', detail: '' },
      ],
    });
  if (later)
    out.push({
      ...later,
      state: 'later',
      daysLeft: 0,
      daysToStart: toStart(later),
      steps: [
        { key: 'absences', state: 'open', detail: 'not entered yet' },
        { key: 'preplan', state: 'open', detail: '' },
        { key: 'plan', state: 'open', detail: '' },
      ],
    });
  return {
    date: day,
    team: 'atlas',
    name: 'Team Atlas',
    source: 'tracker',
    sprints: out,
    errors: 0,
    notices: 2,
    findings: [
      { level: 'notice', where: 'sprints/2026.22.yaml', message: 'Absences are announced only.', route: '/sprint/prepare' },
      { level: 'notice', where: 'products.yaml: platform', message: 'The product has no share in the sprint.', route: '/team/products' },
    ],
  };
}

const ok = (message: string): Result => ({ ok: true, message });

export const mockApi: Api = {
  ...teamMock,
  async Info() {
    return { version: 'dev', os: 'browser', arch: '', dataDir: prefs.dataDir, holidaysVersion: 'mock' };
  },
  async Prefs() {
    return { ...prefs };
  },
  async SetLanguage(code) {
    prefs = { ...prefs, language: code };
  },
  async SetTheme(code) {
    prefs = { ...prefs, theme: code };
  },
  async Texts(lang) {
    if (lang !== 'de') return {};
    const mod = await import('../../../../i18n/data/de.ui.json');
    return (mod.default as { texts: Record<string, string> }).texts;
  },
  async SetDataDir(path) {
    prefs = { ...prefs, dataDir: path };
  },
  async PickDataDir() {
    return '';
  },
  async Teams() {
    return [{ key: 'atlas', name: 'Team Atlas', people: 6, sprints: sprints.length, tickets: true, products: 3 }];
  },
  async Sprints() {
    return sprints;
  },
  async Status() {
    return status();
  },
  async Save() {
    incoming = 0;
    return ok('Saved.');
  },
  async Refresh() {
    incoming = 0;
    return ok('Up to date.');
  },
  async Today() {
    return today();
  },
  async SyncTracker() {
    return ok('Tracker synced.');
  },
};
