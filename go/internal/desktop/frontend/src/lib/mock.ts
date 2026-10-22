// Answers for a browser without the program (npm run dev, tests): the invented demo team
// "Team Atlas" (no real data, no real names). Same methods as the Go API.

import type { Api } from './api';
import type { ForecastRow, ForecastView, WhatIfRow, WhenDoneView } from './types.forecast';
import type { Prefs, Result, SprintInfo, Status } from './types';

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

// Forecast of Team Atlas: 10 completed sprints, the current one and 4 coming ones.
const round1 = (n: number) => Math.round(n * 10) / 10;
function forecastView(): ForecastView {
  const ref = 40;
  const vel = [31, 36, 34, 38, 33, 40, 37, 41, 39, 42];
  const caps = [38, 41, 36, 40, 35, 42, 39, 41, 38, 40];
  const day = 86400000;
  const base = Date.UTC(2026, 0, 5);
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const row = (i: number, state: ForecastRow['state']): ForecastRow => {
    const v = vel[i] ?? null;
    const nv = v !== null ? round1((v / (caps[i] ?? 39)) * ref) : null;
    return {
      id: `2026.${12 + i}`, start: iso(base + i * 14 * day), end: iso(base + i * 14 * day + 11 * day), state, recorded: i < 11,
      capacity: caps[i] ?? 39, capacitySource: i < 10 ? 'recorded' : 'people list', unsure: false,
      commitment: v !== null ? v + 2 : null, velocity: v, normalizedVelocity: nv, average: nv, trend: nv,
      fulfillment: v !== null ? round1((v / (v + 2)) * 100) : null, plan: null, planSource: '', low: null, high: null, plannable: null, small: null,
    };
  };
  const past = Array.from({ length: 10 }, (_, i) => row(i, 'past'));
  const nvTrend = 40.2;
  const upcoming = Array.from({ length: 5 }, (_, k) => {
    const r = row(10 + k, k === 0 ? 'current' : 'future');
    const cap = [38, 37, 41, 36, 40][k] ?? 38;
    const plan = Math.floor((nvTrend / ref) * cap);
    return { ...r, velocity: null, commitment: null, normalizedVelocity: null, fulfillment: null, capacity: cap, capacitySource: k < 2 ? 'announced absences' : 'expected absences', unsure: k > 3,
      average: nvTrend, trend: nvTrend, plan, planSource: 'projection' as const, low: Math.floor((33 / ref) * cap), high: Math.floor((42 / ref) * cap),
      plannable: plan * 0.8, small: round1(plan * 0.2) };
  });
  return { team: 'atlas', today: iso(base + 10 * 14 * day + 3 * day), referenceCapacity: ref, window: 6, roadmapShare: 0.8, trendMode: 'flat', horizon: 4, rounding: 0, samples: 6, fewSamples: false, rate: nvTrend / ref, past, upcoming };
}

const ok = (message: string): Result => ({ ok: true, message });

export const mockApi: Api = {
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
  async Forecast() {
    return forecastView();
  },
  async ForecastWhatIf(_team, extraAbsenceDays, focusPercent): Promise<WhatIfRow[]> {
    return forecastView().upcoming.map((r) => {
      const capacity = Math.max(0, (r.capacity ?? 0) - extraAbsenceDays);
      const forecast = Math.floor(((r.trend ?? 0) / 40) * capacity * (focusPercent / 100));
      return { id: r.id, capacity, forecast, base: r.plan ?? 0, delta: forecast - (r.plan ?? 0) };
    });
  },
  async ForecastWhenDone(_team, remaining, sharePercent): Promise<WhenDoneView> {
    const per = 36 * (sharePercent / 100);
    const sprints = Array.from({ length: 12 }, (_, i) => `2026.${23 + i}`);
    const cumulative = sprints.map((_, i) => Math.min(1, Math.max(0, (per * (i + 1) - remaining * 0.6) / (remaining * 0.8))));
    const first = (p: number) => sprints.find((_, i) => (cumulative[i] ?? 0) >= p) ?? '';
    return { remaining, share: sharePercent, runs: 10000, samples: 6, p50: first(0.5), p85: first(0.85), sprints, cumulative, perSprint: per, trendCapacity: sprints.slice(6), available: remaining > 0 && sharePercent > 0 };
  },
};
