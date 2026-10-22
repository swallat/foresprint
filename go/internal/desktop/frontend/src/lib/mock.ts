// Answers for a browser without the program (npm run dev, tests): the invented demo team
// "Team Atlas" (no real data, no real names). Same methods as the Go API.

import type { Api } from './api';
import { createSprintsMock } from './mock.sprints';
import type { Prefs, Result, SprintInfo, Status } from './types';

// Eight finished sprints, the running one and five to come, counted from today.
const monday = new Date(Date.now() - ((new Date().getUTCDay() + 6) % 7) * 86400000);
const first = Date.UTC(monday.getUTCFullYear(), monday.getUTCMonth(), monday.getUTCDate()) - 8 * 14 * 86400000;
const sprints: SprintInfo[] = Array.from({ length: 14 }, (_, i) => {
  const n = 12 + i;
  const start = new Date(first + i * 14 * 86400000);
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

const ok = (message: string): Result => ({ ok: true, message });

export const mockApi: Api = {
  ...createSprintsMock(sprints),
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
  async SyncTracker() {
    return ok('Tracker synced.');
  },
};
