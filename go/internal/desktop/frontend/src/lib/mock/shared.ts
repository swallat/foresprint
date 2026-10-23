// Demo state shared by the browser answers of several areas (demo team "Team Atlas"). Areas
// import from here; nothing else is shared between the files of mock/.

import type { Prefs, Result, SprintInfo } from '../types';
import { bindSprints } from './plan';

// Eight finished sprints, the running one and five to come, counted from today.
const monday = new Date(Date.now() - ((new Date().getUTCDay() + 6) % 7) * 86400000);
const first = Date.UTC(monday.getUTCFullYear(), monday.getUTCMonth(), monday.getUTCDate()) - 8 * 14 * 86400000;
export const sprints: SprintInfo[] = Array.from({ length: 14 }, (_, i) => {
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

bindSprints(() => sprints);

const prefs: Prefs = {
  language: navigator.language.startsWith('de') ? 'de' : 'en',
  languages: [
    { code: 'de', label: 'Deutsch' },
    { code: 'en', label: 'English' },
  ],
  density: 'normal',
  theme: 'system',
  themes: [
    { code: 'system', label: 'As system' },
    { code: 'light', label: 'Light' },
    { code: 'dark', label: 'Dark' },
  ],
  dataDir: '/demo/teams',
  recentDataDirs: ['/demo/teams', '/demo/archive/teams'],
};

/** The settings of this machine and the selected team; areas read and replace them here. */
export const demo = {
  prefs,
  team: { key: 'atlas', name: 'Team Atlas', people: 6, sprints: sprints.length, tickets: true, products: 3 },
};

export const ok = (message: string): Result => ({ ok: true, message });
