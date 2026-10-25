// State of the Backlog area: the loaded view, the filter (it survives page changes), the
// selection, and the actions that change tickets. The ticket panel and the presentation view
// use the same state, so a change in one shows in the others.

import { api } from '../../lib/api';
import { fmt } from '../../lib/format';
import { app, refreshStatus, toast } from '../../lib/app.svelte';
import { language, t as translate } from '../../lib/i18n.svelte';
import type { BacklogTicket, BacklogView } from '../../lib/types.backlog';
import { addCustom, blank, customKey, readCustom, removeCustom, type CustomView, type Group, type Sort } from './backlog';
import { localTerms } from './terms';

/** Translates like lib/i18n, and says "work package" for a team without a tracker. */
export function t(text: string, vars?: Record<string, string | number>): string {
  return localTerms(translate(text, vars), store.view?.source, language());
}

/** Pseudo key of the ticket panel in "create a work package" mode. */
export const NEW = '+new';

export const store = $state({
  view: undefined as BacklogView | undefined,
  team: '',
  loading: false,
  error: '',
});

export type Layout = 'side' | 'stacked';

function readLayout(): Layout {
  try {
    return localStorage.getItem('foresprint.backlog.layout') === 'stacked' ? 'stacked' : 'side';
  } catch {
    return 'side';
  }
}

/** Switches the backlog between backlog and sprints side by side or one below the other; kept on this machine. */
export function setLayout(layout: Layout): void {
  ui.layout = layout;
  try {
    localStorage.setItem('foresprint.backlog.layout', layout);
  } catch {
    /* blocked storage: the choice lasts until the window closes */
  }
}

export const ui = $state({
  filter: blank(),
  group: 'none' as Group,
  sort: 'rank' as Sort,
  layout: readLayout(),
  custom: [] as CustomView[],
  selection: [] as string[],
  menu: false,
  open: {} as Record<string, boolean>,
});

/** An action the presentation view offers next to the ticket, set by the page that opens it
 * (for example Plan: take the ticket into the sprint or out of it). */
export interface PresentAction {
  label: (key: string) => string;
  /** True when the action would undo itself (the ticket is already in). */
  active: (key: string) => boolean;
  run: (key: string) => Promise<void>;
}

export const present = $state({ keys: [] as string[], key: '', from: '', action: undefined as PresentAction | undefined });

let loadId = 0;

/** (Re)loads the backlog of the selected team. A stale answer of an earlier call is dropped. */
// The Jira board is read once per team and run of the window, in the background; a changed list
// of sprints shows on a reload. A failure (no token, offline) leaves the backlog as it is.
const boardRead = new Set<string>();
async function readBoard(team: string, tracker: boolean): Promise<void> {
  if (!tracker || boardRead.has(team)) return;
  boardRead.add(team);
  try {
    if ((await api.RefreshBoardSprints(team)) > 0 && team === app.team) await loadBacklog();
  } catch {
    /* the backlog works without the board */
  }
}

export async function loadBacklog(): Promise<void> {
  const id = ++loadId;
  const team = app.team;
  if (!team) {
    store.view = undefined;
    return;
  }
  store.loading = true;
  try {
    const view = await api.Backlog(team);
    if (id !== loadId) return;
    store.view = view;
    store.team = team;
    store.error = '';
    void readBoard(team, view.tracker !== '');
  } catch (e) {
    if (id === loadId) store.error = String(e);
  } finally {
    if (id === loadId) store.loading = false;
  }
}

/** After a change: reload the list and the status (unsaved changes) of the window. */
export async function changed(): Promise<void> {
  await Promise.all([loadBacklog(), refreshStatus()]);
}

/** Puts a work package before (or after) another one in the backlog order; anchor "" = to the end. */
export async function reorder(key: string, anchor: string, after = false): Promise<boolean> {
  try {
    // The rank order moves anywhere; the planning order only among equal priority and project.
    if (ui.sort === 'rank') await api.MoveTicketByRank(app.team, key, anchor, after);
    else await api.MoveWorkPackage(app.team, key, anchor, after);
  } catch (e) {
    toast(String(e), 'bad');
    return false;
  }
  await changed();
  return true;
}

/** Takes the own order of tracker tickets away; the tracker's rank counts again. */
export async function resetOrder(): Promise<void> {
  try {
    await api.ResetOrder(app.team);
  } catch (e) {
    toast(String(e), 'bad');
  }
  await changed();
}

/** Every ticket the view knows, wherever it sits. */
export function allTickets(view: BacklogView | undefined): BacklogTicket[] {
  if (!view) return [];
  return [...view.tickets, ...view.lanes.flatMap((l) => l.tickets), ...view.proForma.flatMap((p) => p.tickets)];
}

/** Earmarks tickets for a sprint ("" takes the earmark away) and offers to undo it. */
export async function earmark(keys: string[], sprint: string): Promise<void> {
  const view = store.view;
  if (!view || keys.length === 0) return;
  const rows = allTickets(view);
  const before = new Map(rows.map((tk) => [tk.key, tk.earmark]));
  const notes = new Map(rows.map((tk) => [tk.key, tk.earmarkNote ?? '']));
  const fixed = new Set(rows.filter((tk) => tk.fixed).map((tk) => tk.key));
  const pro = new Map(rows.map((tk) => [tk.key, proFormaOf(view, tk.key)]));
  const moved: string[] = [];
  try {
    for (const key of keys) {
      if ((before.get(key) ?? '') === sprint || fixed.has(key)) continue;
      await api.EarmarkTicket(app.team, key, sprint, '');
      moved.push(key);
    }
  } catch (e) {
    toast(String(e), 'bad');
  }
  ui.selection = ui.selection.filter((k) => !moved.includes(k));
  ui.menu = false;
  await changed();
  if (moved.length === 0) return;
  const lane = view.lanes.find((l) => l.sprint === sprint);
  const text =
    moved.length === 1
      ? sprint
        ? t('{key} earmarked for {sprint}.', { key: moved[0] ?? '', sprint })
        : t('{key} is back in the backlog.', { key: moved[0] ?? '' })
      : sprint
        ? t('{count} tickets earmarked for {sprint}.', { count: moved.length, sprint })
        : t('{count} tickets are back in the backlog.', { count: moved.length });
  const used = lane && lane.plan != null ? usedAfter(lane.sprint, moved) : 0;
  const over = lane && lane.plan != null && used > lane.plan;
  toast(over ? `${text} ${t('Over the Forecast PLAN: {used} of {plan}.', { used: fmt(used), plan: fmt(lane.plan ?? 0) })}` : text, over ? 'info' : 'ok', {
    label: t('Undo'),
    run: async () => {
      try {
        for (const key of moved) {
          await api.EarmarkTicket(app.team, key, before.get(key) ?? '', notes.get(key) ?? '');
          if (pro.get(key)) await api.MoveToProForma(app.team, key, pro.get(key) ?? '');
        }
      } catch (e) {
        toast(String(e), 'bad');
      }
      await changed();
    },
  });
}

/** Where a ticket sits among the pro-forma sprints ("" = none). */
function proFormaOf(view: BacklogView, key: string): string {
  return view.proForma.find((p) => p.tickets.some((tk) => tk.key === key))?.name ?? '';
}

/** Puts tickets into a pro-forma sprint ("" = back to the backlog) and offers to undo it. */
export async function toProForma(keys: string[], name: string, quiet = false): Promise<void> {
  const view = store.view;
  if (!view || keys.length === 0) return;
  const before = new Map(keys.map((k) => [k, proFormaOf(view, k)]));
  const rows = allTickets(view);
  const earmarks = new Map(rows.map((tk) => [tk.key, { sprint: tk.earmark, note: tk.earmarkNote ?? '' }]));
  const moved: string[] = [];
  try {
    for (const key of keys) {
      if (before.get(key) === name) continue;
      await api.MoveToProForma(app.team, key, name);
      moved.push(key);
    }
  } catch (e) {
    toast(String(e), 'bad');
  }
  ui.selection = ui.selection.filter((k) => !moved.includes(k));
  ui.menu = false;
  await changed();
  if (moved.length === 0 || quiet) return;
  const text =
    moved.length === 1
      ? name
        ? t('{key} moved to {name}. Adjust it in the tracker.', { key: moved[0] ?? '', name })
        : t('{key} is back in the backlog. Adjust it in the tracker.', { key: moved[0] ?? '' })
      : name
        ? t('{count} tickets moved to {name}. Adjust them in the tracker.', { count: moved.length, name })
        : t('{count} tickets are back in the backlog. Adjust them in the tracker.', { count: moved.length });
  toast(text, 'ok', {
    label: t('Undo'),
    run: async () => {
      try {
        for (const key of moved) {
          await api.MoveToProForma(app.team, key, before.get(key) ?? '');
          const e = earmarks.get(key);
          if (e?.sprint) await api.EarmarkTicket(app.team, key, e.sprint, e.note);
        }
      } catch (e) {
        toast(String(e), 'bad');
      }
      await changed();
    },
  });
}

function usedAfter(sprint: string, moved: string[]): number {
  const view = store.view;
  if (!view) return 0;
  const lane = view.lanes.find((l) => l.sprint === sprint);
  const there = (lane?.tickets ?? []).filter((tk) => !moved.includes(tk.key));
  const added = allTickets(view).filter((tk) => moved.includes(tk.key));
  return [...there, ...added].reduce((acc, tk) => acc + (tk.size ?? 0), 0);
}

export function toggleSelected(key: string, on: boolean): void {
  ui.selection = on ? [...new Set([...ui.selection, key])] : ui.selection.filter((k) => k !== key);
}

/** Shows the tickets large in the presentation view; `key` is the one to start with. Closing
 * returns to the page that opened it. */
export function openPresent(keys: string[], key: string, action?: PresentAction): void {
  present.keys = keys;
  present.key = key;
  present.action = action;
  present.from = location.hash.startsWith('#/present') ? present.from : location.hash || '#/backlog';
  app.ticket = '';
  location.hash = '#/present';
}

function readStored(team: string): CustomView[] {
  try {
    return readCustom(localStorage.getItem(`foresprint.${customKey(team)}`) ?? '');
  } catch {
    return [];
  }
}

function writeStored(): void {
  try {
    localStorage.setItem(`foresprint.${customKey(app.team)}`, JSON.stringify(ui.custom));
  } catch {
    /* blocked storage: the views last until the window closes */
  }
}

/** Loads the custom views of the selected team (kept on this machine, not in the team's data). */
export function loadCustomViews(): void {
  ui.custom = app.team ? readStored(app.team) : [];
}

export function saveCustomView(name: string): void {
  ui.custom = addCustom(ui.custom, name, ui.filter, ui.group, ui.sort);
  writeStored();
}

export function deleteCustomView(id: string): void {
  ui.custom = removeCustom(ui.custom, id);
  writeStored();
}

/** Applies a custom view: its filter, grouping and sorting; the search text stays. */
export function applyCustomView(v: CustomView): void {
  ui.filter = { ...blank(), ...v.filter, q: ui.filter.q };
  ui.group = v.group;
  ui.sort = v.sort;
  ui.selection = [];
}
