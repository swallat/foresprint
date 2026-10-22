// Pure logic of the Backlog page: filters, saved views, grouping, sums. No window, no calls, so
// it is tested alone (backlog.test.ts).

import type { BacklogTicket, BacklogView, Named } from '../../lib/types.backlog';

export type Refined = 'all' | 'yes' | 'open';
export type Flag = '' | 'unassigned' | 'earmarked';
export type Group = 'none' | 'project' | 'product';

export interface Filter {
  products: string[];
  projects: string[]; // "" = daily business
  refined: Refined;
  flag: Flag;
  q: string;
}

export const blank = (): Filter => ({ products: [], projects: [], refined: 'all', flag: '', q: '' });

export interface SavedView {
  id: string;
  filter: Partial<Filter>;
}

/** The saved views of the backlog: filters of one list (flows.md, principle 4). */
export const VIEWS: SavedView[] = [
  { id: 'all', filter: {} },
  { id: 'daily', filter: { projects: [''] } },
  { id: 'refinement', filter: { refined: 'open' } },
  { id: 'unassigned', filter: { flag: 'unassigned' } },
  { id: 'earmarked', filter: { flag: 'earmarked' } },
];

const signature = (f: Filter): string =>
  JSON.stringify([[...f.products].sort(), [...f.projects].sort(), f.refined, f.flag]);

/** The id of the saved view that equals the filter (the search text does not count), or "". */
export function activeView(f: Filter): string {
  return VIEWS.find((v) => signature({ ...blank(), ...v.filter }) === signature(f))?.id ?? '';
}

export function applyView(id: string, keepQuery: string): Filter {
  const v = VIEWS.find((x) => x.id === id);
  return { ...blank(), ...(v?.filter ?? {}), q: keepQuery };
}

/** True for a ticket whose product is open: a rule hint, or no product in a team with several. */
export function unassigned(t: BacklogTicket, multi: boolean): boolean {
  return !!t.ruleHint || (multi && !t.product);
}

// The text a search looks in, built once per ticket object (a reload makes new objects).
const haystacks = new WeakMap<BacklogTicket, string>();

function haystack(t: BacklogTicket, names: Names): string {
  let hay = haystacks.get(t);
  if (hay === undefined) {
    hay = `${t.key} ${t.title} ${names.product(t.product)} ${names.project(t.project)} ${t.epic} ${t.labels.join(' ')}`.toLowerCase();
    haystacks.set(t, hay);
  }
  return hay;
}

export interface Names {
  product: (id: string) => string;
  project: (id: string) => string;
}

export function matches(t: BacklogTicket, f: Filter, names: Names, multi: boolean): boolean {
  if (f.products.length && !f.products.includes(t.product)) return false;
  if (f.projects.length && !f.projects.includes(t.project)) return false;
  if (f.refined === 'yes' && !t.refined) return false;
  if (f.refined === 'open' && t.refined) return false;
  if (f.flag === 'unassigned' && !unassigned(t, multi)) return false;
  const q = f.q.trim().toLowerCase();
  if (q) {
    const hay = haystack(t, names);
    if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

export const sum = (items: BacklogTicket[]): number => items.reduce((acc, t) => acc + (t.size ?? 0), 0);

export interface Section {
  id: string;
  /** The group's name; "" means daily business (project) or no product. */
  name: string;
  kind: 'project' | 'product';
  items: BacklogTicket[];
}

/** Splits the list by project (with daily business last) or by product; empty groups drop out. */
export function group(items: BacklogTicket[], by: Group, view: Pick<BacklogView, 'products' | 'projects'>): Section[] {
  if (by === 'none') return [];
  const byProject = by === 'project';
  const named: Named[] = byProject ? view.projects : view.products;
  const ids = [...named.map((n) => n.id), ''];
  return ids
    .map((id) => ({
      id,
      name: named.find((n) => n.id === id)?.name ?? '',
      kind: byProject ? ('project' as const) : ('product' as const),
      items: items.filter((t) => (byProject ? t.project : t.product) === id),
    }))
    .filter((s) => s.items.length > 0);
}

/** The color of a product's dot: one of the four chart colors, by position. */
export function productColor(view: Pick<BacklogView, 'products'>, id: string): string {
  const i = view.products.findIndex((p) => p.id === id);
  return ['var(--c-vel)', 'var(--c-nv)', 'var(--c-fc)', 'var(--c-wif)'][(i < 0 ? 0 : i) % 4]!;
}

/** The sprint the keyboard moves a ticket to: the lane left/right of where it is. */
export function neighbour(lanes: string[], at: string, step: -1 | 1): string | undefined {
  if (at === '') return step === 1 ? lanes[0] : undefined;
  const i = lanes.indexOf(at);
  if (i < 0) return undefined;
  const next = i + step;
  if (next < 0) return ''; // back to the backlog
  return lanes[next];
}
