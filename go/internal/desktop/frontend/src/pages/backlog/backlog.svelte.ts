// State of the Backlog area: the loaded view, the filter (it survives page changes), the
// selection, and the actions that change tickets. The ticket panel and the presentation view
// use the same state, so a change in one shows in the others.

import { api } from '../../lib/api';
import { app, refreshStatus, toast } from '../../lib/app.svelte';
import { t } from '../../lib/i18n.svelte';
import type { BacklogTicket, BacklogView } from '../../lib/types.backlog';
import { blank, type Group } from './backlog';

/** Pseudo key of the ticket panel in "create a work package" mode. */
export const NEW = '+new';

export const store = $state({
  view: undefined as BacklogView | undefined,
  team: '',
  loading: false,
  error: '',
});

export const ui = $state({
  filter: blank(),
  group: 'none' as Group,
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

/** Every ticket the view knows, wherever it sits. */
export function allTickets(view: BacklogView | undefined): BacklogTicket[] {
  if (!view) return [];
  return [...view.tickets, ...view.lanes.flatMap((l) => l.tickets), ...view.proForma.flatMap((p) => p.tickets)];
}

/** Earmarks tickets for a sprint ("" takes the earmark away) and offers to undo it. */
export async function earmark(keys: string[], sprint: string): Promise<void> {
  const view = store.view;
  if (!view || keys.length === 0) return;
  const before = new Map(allTickets(view).map((tk) => [tk.key, tk.earmark]));
  const moved: string[] = [];
  try {
    for (const key of keys) {
      if ((before.get(key) ?? '') === sprint) continue;
      await api.SetEarmark(app.team, key, sprint, '');
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
  toast(over ? `${text} ${t('Over the Forecast PLAN: {used} of {plan}.', { used, plan: lane.plan ?? 0 })}` : text, over ? 'info' : 'ok', {
    label: t('Undo'),
    run: async () => {
      try {
        for (const key of moved) await api.SetEarmark(app.team, key, before.get(key) ?? '', '');
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
