// Shared state of the window: preferences, team and sprint selection, the status of storage and
// tracker, toasts, the ticket panel. Pages read from `app` and call its functions; they do not
// keep their own copy of these.

import { api } from './api';
import { useLanguage } from './i18n.svelte';
import { applyDensity, applyFeatures, applyTheme } from './theme';
import type { Prefs, Result, SprintInfo, Status, TeamSummary } from './types';
import type { Features } from './types.settings';

export interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'ok' | 'bad';
  action?: { label: string; run: () => void };
}

export const app = $state({
  ready: false,
  prefs: undefined as Prefs | undefined,
  teams: [] as TeamSummary[],
  team: '',
  sprints: [] as SprintInfo[],
  sprint: '',
  /** Optional parts of the team (ticket source, products, production); hidden when not used. */
  features: undefined as Features | undefined,
  status: { storage: 'saved', detail: '', incoming: 0, findings: 0, tracker: { enabled: false, name: '', last: '', syncing: false, failed: '' } } as Status,
  busy: '' as '' | 'save' | 'refresh' | 'sync',
  toasts: [] as Toast[],
  /** Key of the ticket shown in the side panel, "" if closed. */
  ticket: '',
  paletteOpen: false,
  railOpen: false,
  /** Set when the data folder could not be read. */
  problem: '',
});

const store = {
  get(key: string): string {
    try {
      return localStorage.getItem(`foresprint.${key}`) ?? '';
    } catch {
      return '';
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(`foresprint.${key}`, value);
    } catch {
      /* private window or blocked storage: the choice is simply not remembered */
    }
  },
};

let nextToast = 1;

/** Shows a short message; it goes away by itself unless it has an action. */
export function toast(text: string, tone: Toast['tone'] = 'info', action?: Toast['action']): void {
  const id = nextToast++;
  app.toasts.push({ id, text, tone, action });
  setTimeout(() => dismissToast(id), action ? 10000 : 4500);
}

export function dismissToast(id: number): void {
  app.toasts = app.toasts.filter((t) => t.id !== id);
}

export async function loadPrefs(): Promise<void> {
  app.prefs = await api.Prefs();
  applyTheme(app.prefs.theme);
  applyDensity(app.prefs.density);
  await useLanguage(app.prefs.language);
}

export async function setLanguage(code: string): Promise<void> {
  await api.SetLanguage(code);
  await loadPrefs();
}

export async function setTheme(code: string): Promise<void> {
  await api.SetTheme(code);
  await loadPrefs();
}

export async function setDensity(code: string): Promise<void> {
  await api.SetDensity(code);
  await loadPrefs();
}

export async function setCalcMode(code: string): Promise<void> {
  await api.SetCalcMode(code);
  await loadPrefs();
}

/** Reads which optional parts the team uses and tells the styles (data-trk and friends). Call it
 * after settings changed. */
export async function loadFeatures(): Promise<void> {
  app.features = app.team ? await api.TeamFeatures(app.team).catch(() => undefined) : undefined;
  applyFeatures(app.features);
}

/** Reads the teams of the data folder and keeps (or picks) the selected team and sprint. */
export async function loadTeams(): Promise<void> {
  try {
    app.teams = await api.Teams();
    app.problem = '';
  } catch (e) {
    app.teams = [];
    app.problem = String(e);
  }
  const wanted = store.get('team');
  const usable = app.teams.filter((t) => !t.problem);
  const team = usable.find((t) => t.key === (app.team || wanted)) ?? usable[0];
  await selectTeam(team?.key ?? '');
}

export async function selectTeam(key: string): Promise<void> {
  app.team = key;
  store.set('team', key);
  app.sprints = key ? await api.Sprints(key).catch(() => []) : [];
  const wanted = store.get(`sprint.${key}`);
  const pick =
    app.sprints.find((s) => s.id === wanted) ?? app.sprints.find((s) => s.state === 'current') ?? app.sprints.at(-1);
  app.sprint = pick?.id ?? '';
  await loadFeatures();
}

export function selectSprint(id: string): void {
  app.sprint = id;
  store.set(`sprint.${app.team}`, id);
}

export async function refreshStatus(): Promise<void> {
  try {
    const status = await api.Status();
    const tracker = app.team ? await api.TrackerInfo(app.team).catch(() => undefined) : undefined;
    app.status = tracker ? { ...status, tracker } : status;
  } catch {
    /* keep the last known state; a failing status call must not break the window */
  }
}

async function run(kind: 'save' | 'refresh' | 'sync', call: () => Promise<Result>): Promise<void> {
  if (app.busy) return;
  app.busy = kind;
  try {
    const r = await call();
    toast(r.message, r.ok ? 'ok' : 'bad');
  } catch (e) {
    toast(String(e), 'bad');
  } finally {
    app.busy = '';
    await refreshStatus();
  }
}

/** Save and share (top bar). Works from every page. */
export const save = () => run('save', () => api.Save());
/** Fetch changes of others (top bar). */
export const refresh = () => run('refresh', () => api.Refresh());
/** Fetch tickets from the tracker now (top bar). */
export const syncTracker = () => run('sync', () => api.SyncTracker(app.team));

/** Opens the ticket in the side panel. */
export function openTicket(key: string): void {
  app.ticket = key;
}

let timer: ReturnType<typeof setInterval> | undefined;

export async function start(): Promise<void> {
  await loadPrefs();
  await loadTeams();
  await refreshStatus();
  app.ready = true;
  timer ??= setInterval(refreshStatus, 15000);
}
