// The entries of the command palette (Ctrl+K): pages, actions and whatever a package registers
// with registerCommands, for example the tickets of the backlog. The palette asks every source
// each time it opens or the query changes, so a source may read current state.

import { api } from './api';
import { app, openTicket, refresh, save, selectSprint, setTheme, syncTracker } from './app.svelte';
import { t } from './i18n.svelte';
import { go } from './router.svelte';
import { pages } from './routes';

export type CommandGroup = 'page' | 'action' | 'help' | 'ticket' | 'sprint';

export interface Command {
  /** Stable id, also the key of the list. */
  id: string;
  label: string;
  group: CommandGroup;
  /** Right-hand hint: the address of a page, a shortcut, a ticket title. */
  hint?: string;
  /** More words that find the entry, e.g. synonyms. */
  words?: string;
  run: () => void;
}

type Source = (query: string) => Command[];

const sources: Source[] = [];

/** Adds a source of entries. Returns a function that removes it again. */
export function registerCommands(source: Source): () => void {
  sources.push(source);
  return () => {
    const i = sources.indexOf(source);
    if (i >= 0) sources.splice(i, 1);
  };
}

const nextTheme: Record<string, string> = { system: 'light', light: 'dark', dark: 'system' };

function pageCommands(): Command[] {
  return pages
    .filter((p) => !p.path.includes(':') && !p.bare)
    .map((p) => ({ id: `page:${p.path}`, label: t(p.title), group: 'page' as const, hint: p.path, run: () => go(p.path) }));
}

function actionCommands(): Command[] {
  const out: Command[] = [
    { id: 'act:save', label: t('Save'), group: 'action', hint: 'Ctrl+S', words: 'speichern commit', run: () => void save() },
    { id: 'act:refresh', label: t('Fetch changes of others'), group: 'action', hint: 'Ctrl+Shift+R', words: 'aktualisieren pull', run: () => void refresh() },
    {
      id: 'act:theme',
      label: t('Switch colour scheme'),
      group: 'action',
      words: 'theme dark light dunkel hell farbschema',
      run: () => void setTheme(nextTheme[app.prefs?.theme ?? 'system'] ?? 'system'),
    },
    { id: 'act:setup', label: t('Run first-start setup again'), group: 'action', hint: '/setup', words: 'einrichtung', run: () => go('/setup') },
  ];
  if (app.status.tracker.enabled) {
    out.splice(2, 0, {
      id: 'act:sync',
      label: t('Fetch tickets from {name} now', { name: app.status.tracker.name || t('Tracker') }),
      group: 'action',
      words: 'jira sync abrufen',
      run: () => void syncTracker(),
    });
  }
  return out;
}

function sprintCommands(): Command[] {
  return app.sprints.map((sp) => ({
    id: `sprint:${sp.id}`,
    label: t('Sprint {id}', { id: sp.id }),
    group: 'sprint' as const,
    hint: `${sp.start} – ${sp.end}`,
    words: 'sprint',
    run: () => {
      selectSprint(sp.id);
      go('/sprints');
    },
  }));
}

// The tickets of the team, read once when the palette opens and searched in memory, so that the
// result of a keystroke never waits for the core.
let ticketTeam = '';
let tickets: { key: string; title: string }[] = [];
let loadNo = 0;

/** Forgets the ticket list (another team, tests). */
export function resetTicketIndex(): void {
  loadNo++;
  ticketTeam = '';
  tickets = [];
}

/** Reads the ticket list of the selected team for the palette; a failure leaves it empty. */
export async function loadTicketIndex(): Promise<void> {
  const team = app.team;
  if (!team) return;
  const mine = ++loadNo;
  let found: { key: string; title: string }[] = [];
  try {
    const view = await api.Backlog(team);
    // Tickets in sprint lanes and pro-forma sprints belong to the list as well.
    const all = [...view.tickets, ...view.lanes.flatMap((l) => l.tickets), ...view.proForma.flatMap((x) => x.tickets)];
    found = [...new Map(all.map((x) => [x.key, { key: x.key, title: x.title }])).values()];
  } catch {
    /* the palette still finds pages, sprints and actions */
  }
  if (mine !== loadNo) return; // a newer load is under way
  ticketTeam = team;
  tickets = found;
}

// Every ticket that contains all words of the query; commandsFor ranks them with everything else.
function ticketCommands(query: string): Command[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0 || ticketTeam !== app.team) return [];
  const out: Command[] = [];
  for (const x of tickets) {
    const hay = `${x.key} ${x.title}`.toLowerCase();
    if (words.every((w) => hay.includes(w))) {
      out.push({ id: `ticket:${x.key}`, label: `${x.key} ${x.title}`, group: 'ticket', run: () => openTicket(x.key) });
    }
  }
  return out;
}

/** Scores an entry for a query: 0 = no match, higher is better. */
export function score(c: Command, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const label = c.label.toLowerCase();
  const hay = `${label} ${(c.words ?? '').toLowerCase()} ${(c.hint ?? '').toLowerCase()}`;
  const parts = q.split(/\s+/);
  if (!parts.every((p) => hay.includes(p))) return 0;
  if (label === q) return 100;
  if (label.startsWith(q)) return 50;
  if (label.split(/\s+/).some((w) => w.startsWith(parts[0] ?? ''))) return 20;
  return 5;
}

/** The entries for a query, best first; with an empty query the groups keep their order. */
export function commandsFor(query: string, limit = 12): Command[] {
  const all = [...pageCommands(), ...sprintCommands(), ...actionCommands(), ...ticketCommands(query), ...sources.flatMap((s) => s(query))];
  const scored = all.map((c, i) => ({ c, s: score(c, query), i })).filter((x) => x.s > 0);
  scored.sort((a, b) => b.s - a.s || a.i - b.i);
  return scored.slice(0, limit).map((x) => x.c);
}
