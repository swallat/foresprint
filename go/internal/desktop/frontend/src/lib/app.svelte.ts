// Shared state of the window: preferences, team and sprint selection, the status of storage and
// tracker, toasts, the ticket panel. Pages read from `app` and call its functions; they do not
// keep their own copy of these.

import { api, inProgram, setDemo } from './api';
import { setDigits } from './digits.svelte';
import { t, useLanguage } from './i18n.svelte';
import { go } from './router.svelte';
import { applyDensity, applyFeatures, applyTheme } from './theme';
import type { PendingTag } from './types.data';
import type { Prefs, Result, SprintInfo, Status, TeamSummary } from './types';
import type { Features, UpdateInfo } from './types.settings';

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
  status: {
    storage: 'saved',
    detail: '',
    incoming: 0,
    findings: 0,
    tracker: { enabled: false, name: '', last: '', syncing: false, failed: '', interval: 0 },
    data: undefined,
  } as unknown as Status,
  busy: '' as '' | 'save' | 'refresh' | 'sync',
  /** Data errors that stopped Save; the dialog offers to fix them or to save anyway. */
  findings: undefined as string[] | undefined,
  /** Tags a sprint review asked for; the next Save sets them. */
  pendingTags: [] as PendingTag[],
  /** Counts up after every Save or Refresh, so that open pages of the area Data reload. */
  rev: 0,
  /** Counts up when the data folder changed behind this view's back (the other view wrote); the page is shown anew. */
  changed: 0,
  toasts: [] as Toast[],
  /** Key of the ticket shown in the side panel, "" if closed. */
  ticket: '',
  paletteOpen: false,
  railOpen: false,
  /** Set when the data folder could not be read. */
  problem: '',
  /** Personal setting: calculations next to numbers (see lib/calc/Calc.svelte). */
  calcMode: 'icon' as CalcMode,
  /** The invented demo team is shown instead of the data folder (nothing is read or saved). */
  demo: false,
  /** The variant the demo was opened with ("atlas/packages"); see demoChoice. */
  demoVariant: '',
  /** A newer program version is known (daily check at the start); undefined if none. */
  update: undefined as UpdateInfo | undefined,
});

export type CalcMode = 'off' | 'icon' | 'inline';

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

const calcModes: CalcMode[] = ['off', 'icon', 'inline'];

/** Chooses how calculations show next to numbers; remembered on this machine. */
export function setCalcMode(mode: CalcMode): void {
  app.calcMode = mode;
  store.set('calc', mode);
}

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

/** Reads which optional parts the team uses and tells the styles (data-trk and friends). Call it
 * after settings changed. */
export async function loadFeatures(): Promise<void> {
  app.features = app.team ? await api.TeamFeatures(app.team).catch(() => undefined) : undefined;
  applyFeatures(app.features);
  setDigits(app.features?.rounding, app.features?.capacityRounding);
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
  if (!app.demo) store.set('team', key);
  app.sprints = key ? await api.Sprints(key).catch(() => []) : [];
  const wanted = store.get(`sprint.${key}`);
  // Without a remembered choice the window opens on the next sprint after the running one (the
  // one being prepared); Today and the sprint overview lead to the running sprint when needed.
  const pick =
    app.sprints.find((s) => s.id === wanted) ?? app.sprints.find((s) => s.state === 'future') ?? app.sprints.find((s) => s.state === 'current') ?? app.sprints.at(-1);
  app.sprint = pick?.id ?? '';
  await loadFeatures();
}

/** Reads the sprints of the selected team again, e.g. after the calendar changed them. A sprint
 * that was renamed keeps its place in the selection: it is found again by its start date. */
export async function refreshSprints(): Promise<void> {
  const team = app.team;
  if (!team) return;
  const before = app.sprints.find((s) => s.id === app.sprint);
  const list = await api.Sprints(team).catch(() => undefined);
  if (!list || app.team !== team) return; // the team was switched meanwhile: selectTeam reads the list itself
  app.sprints = list;
  if (list.some((s) => s.id === app.sprint)) return;
  const moved = before ? list.find((s) => s.start === before.start) : undefined;
  const pick = moved ?? list.find((s) => s.state === 'future') ?? list.find((s) => s.state === 'current') ?? list.at(-1);
  if (pick) selectSprint(pick.id);
}

export function selectSprint(id: string): void {
  app.sprint = id;
  if (!app.demo) store.set(`sprint.${app.team}`, id);
}

export async function refreshStatus(): Promise<void> {
  try {
    const status = await api.Status();
    const tracker = app.team ? await api.TrackerInfo(app.team).catch(() => undefined) : undefined;
    app.status = tracker ? { ...status, tracker } : status;
  } catch {
    /* keep the last known state; a failing status call must not break the window */
  }
  try {
    app.pendingTags = await api.PendingTags();
  } catch {
    app.pendingTags = [];
  }
}

/** Shows the answer of Save, Refresh and the like: a dialog for data errors, else a toast whose
 * action leads to the place where the person can go on. */
const textOf = (r: Result): string => {
  const extra = [r.problem?.hint, ...(r.notes ?? [])].filter(Boolean).join(' ');
  return extra ? `${r.message} ${extra}` : r.message;
};

export function announce(r: Result): void {
  if (r.outcome === 'findings') {
    app.findings = r.findings ?? [];
    return;
  }
  if (r.outcome === 'conflict') {
    toast(textOf(r), 'bad', { label: t('Decide'), run: () => go('/data/conflicts') });
  } else if (r.problem?.kind === 'auth') {
    toast(textOf(r), 'bad', { label: t('Sign in'), run: () => go('/settings/storage') });
  } else if (r.outcome === 'waiting_for_review') {
    toast(textOf(r), 'ok', { label: t('Details'), run: () => go('/data') });
  } else if (r.outcome === 'decided') {
    toast(textOf(r), 'ok');
  } else {
    toast(textOf(r), r.ok ? 'ok' : 'bad');
  }
}

async function run(kind: 'save' | 'refresh' | 'sync', call: () => Promise<Result>): Promise<void> {
  if (app.busy) return;
  app.busy = kind;
  try {
    announce(await call());
  } catch (e) {
    toast(String(e), 'bad');
  } finally {
    app.busy = '';
    await refreshStatus();
    app.rev++;
    // Tickets or the changes of others are new data: the open page shows them at once.
    if (kind !== 'save') await showNewData();
  }
}

/** The page reads its data anew (like after a change from the other view). Sprints may have
 * come with a fetch, so the list is read again first. */
export async function showNewData(): Promise<void> {
  await refreshSprints();
  app.changed++;
}

/** Save and share (top bar). Works from every page. */
export const save = () => run('save', () => api.Save());
/** Save although the check of the data found errors (after the person has seen them). */
export const saveAnyway = () => run('save', () => api.SaveAnyway());
/** Fetch changes of others (top bar). */
export const refresh = () => run('refresh', () => api.Refresh());
/** Fetch tickets from the tracker now (top bar). */
export const syncTracker = () => {
  lastTry.set(app.team, Date.now());
  return run('sync', () => api.SyncTracker(app.team));
};

/** Opens the ticket in the side panel. */
export function openTicket(key: string): void {
  app.ticket = key;
}

/** The variant of the demo team the person picked: the team and where its work comes from. */
export const demoChoice = $state({ team: 'atlas' as 'atlas' | 'simple', source: 'packages' as 'packages' | 'tracker' | 'none' });

/** Key of the picked variant, to see whether the open demo still matches it. */
export const demoVariantKey = () => `${demoChoice.team}/${demoChoice.source}`;

/** Shows the demo team (Team Atlas) instead of the data folder, until leaveDemo(). */
export async function enterDemo(): Promise<void> {
  // the core writes the tutorial team
  if (inProgram) await api.EnterDemo(app.prefs?.language ?? '', demoChoice.team, demoChoice.source);
  setDemo(true);
  app.demo = true;
  app.demoVariant = demoVariantKey();
  app.team = '';
  await loadTeams();
  await refreshStatus();
}

/** Back to the data folder. */
export async function leaveDemo(): Promise<void> {
  setDemo(false);
  if (inProgram) await api.LeaveDemo();
  app.demo = false;
  app.demoVariant = '';
  app.team = '';
  await loadTeams();
  await refreshStatus();
}

let timer: ReturnType<typeof setInterval> | undefined;
let fetchTimer: ReturnType<typeof setInterval> | undefined;
const lastTry = new Map<string, number>(); // per team: when the window last started an automatic fetch

/** Fetches the tickets when the interval of the team has passed. Silent: the top bar chip shows a
 * failure, and the own order of the backlog stays (only the button takes the tracker's again). */
export async function autoFetch(): Promise<void> {
  const tr = app.status.tracker;
  if (app.demo || !app.team || app.busy || !tr.enabled || tr.interval <= 0 || tr.syncing) return;
  const since = Math.max(lastTry.get(app.team) ?? 0, Date.parse(tr.last) || 0);
  if (Date.now() - since < tr.interval * 60000) return;
  const team = app.team;
  lastTry.set(team, Date.now());
  app.busy = 'sync'; // the top bar buttons wait, as for a fetch by hand
  try {
    await api.SyncTrackerAuto(team);
  } catch {
    /* shown by the chip through refreshStatus */
  } finally {
    app.busy = '';
  }
  const before = tr.last;
  await refreshStatus();
  if (app.team === team && app.status.tracker.last !== before) {
    app.rev++;
    // not pulled away from under someone who is typing: the live watcher waits for a quiet moment
    window.dispatchEvent(new CustomEvent('foresprint:news'));
  }
}

/** Looks for a new version (once a day, never in the demo or a development build); silent on failure. */
export async function checkUpdate(): Promise<void> {
  try {
    const info = await api.CheckUpdate(true);
    app.update = info.available ? info : undefined;
  } catch {
    app.update = undefined;
  }
}

export async function start(): Promise<void> {
  // A reload of the window must not leave the core in demo mode while the window looks real.
  if (inProgram && (await api.InDemo())) await api.LeaveDemo();
  const calc = store.get('calc') as CalcMode;
  if (calcModes.includes(calc)) app.calcMode = calc;
  await loadPrefs();
  await loadTeams();
  await refreshStatus();
  app.ready = true;
  void checkUpdate();
  timer ??= setInterval(refreshStatus, 15000);
  fetchTimer ??= setInterval(autoFetch, 30000);
}
