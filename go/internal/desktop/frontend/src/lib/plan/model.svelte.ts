// State and helpers shared by the Pre-plan and Plan pages: the data of the sprint in view, the
// assumptions about the running sprint (what-if) and number formatting.

import { api } from '../api';
import { app, toast } from '../app.svelte';
import { language, t } from '../i18n.svelte';
import type { Assumption, PlanProduct, PlanSprint, PlanTicket, WhatIf } from '../types.plan';

export function emptyAssumption(label: string): Assumption {
  return { label, commitment: null, carry: [], notDone: null, extra: null, restNext: null };
}

/** Assumptions A, B, ... about the running sprint, kept while the window is open. A saved one
 * is the starting point of a label; nothing is final before the review. */
const drafts = $state<{ key: string; list: Assumption[]; active: number }>({ key: '', list: [], active: 0 });

function ensureDrafts(saved: Assumption[]): void {
  const key = `${app.team}/${app.sprint}`;
  if (drafts.key === key) return;
  drafts.key = key;
  drafts.list = saved.length ? saved.map((a) => structuredClone($state.snapshot(a))) : [emptyAssumption('A')];
  drafts.active = saved.length ? saved.length - 1 : 0;
}

export const assumptions = {
  get list(): Assumption[] {
    return drafts.list;
  },
  get active(): Assumption | undefined {
    return drafts.list[Math.min(drafts.active, drafts.list.length - 1)];
  },
  get index(): number {
    return drafts.active;
  },
  select(i: number): void {
    drafts.active = i;
  },
  add(): void {
    const copy = structuredClone($state.snapshot(assumptions.active) ?? emptyAssumption('A'));
    copy.label = String.fromCharCode(65 + drafts.list.length);
    drafts.list.push(copy);
    drafts.active = drafts.list.length - 1;
  },
  reset(): void {
    const a = assumptions.active;
    if (a) drafts.list[drafts.active] = emptyAssumption(a.label);
  },
};

/** True if the assumption changes anything (a carried ticket, or an entered number). */
export function touched(a: Assumption | undefined): boolean {
  return !!a && (a.carry.length > 0 || (a.notDone ?? 0) > 0 || (a.extra ?? 0) > 0 || a.commitment != null);
}

/** The lists of an answer as arrays, even when the core sent null for an empty one. */
export function withLists(d: PlanSprint): PlanSprint {
  const list = <T>(x: T[] | null | undefined): T[] => x ?? [];
  return {
    ...d,
    removed: list(d.removed),
    products: list(d.products),
    tickets: list(d.tickets),
    candidates: list(d.candidates),
    projects: list(d.projects),
    notes: list(d.notes),
    assumptions: list(d.assumptions).map((a) => ({ ...a, carry: list(a.carry) })),
    prod: d.prod ? { ...d.prod, people: list(d.prod.people) } : null,
    matrix: d.matrix ? { projects: list(d.matrix.projects), cells: list(d.matrix.cells) } : null,
  };
}

export class PlanModel {
  data = $state<PlanSprint | null>(null);
  error = $state('');
  loading = $state(true);
  running = $state<WhatIf | null>(null);
  private seq = 0;

  /** Reads the sprint again, with the active assumption if it changes anything. */
  async reload(): Promise<void> {
    const team = app.team;
    const sprint = app.sprint;
    if (!team || !sprint) {
      this.loading = false;
      return;
    }
    const my = ++this.seq;
    try {
      const first = withLists(await api.PlanSprint(team, sprint, null));
      if (my !== this.seq) return;
      ensureDrafts(first.assumptions);
      const a = assumptions.active;
      const use = touched(a) ? $state.snapshot(a) : null;
      const data = use ? withLists(await api.PlanSprint(team, sprint, use as Assumption)) : first;
      this.running = use && first.running ? await api.WhatIf(team, sprint, use as Assumption) : null;
      if (my !== this.seq) return;
      this.data = data;
      this.error = '';
    } catch (e) {
      if (my === this.seq) this.error = String(e);
    } finally {
      if (my === this.seq) this.loading = false;
    }
  }

  /** Calls a change on the core, shows the failure as a toast and reads the sprint again. */
  async change(call: () => Promise<void>, done?: string): Promise<boolean> {
    try {
      await call();
      if (done) toast(done, 'ok');
      await this.reload();
      return true;
    } catch (e) {
      toast(String(e), 'bad');
      await this.reload();
      return false;
    }
  }
}

// --- Formatting ---------------------------------------------------------------------------

export function fmt(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return '–';
  return new Intl.NumberFormat(language(), { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(v);
}

export function signed(v: number): string {
  if (v > 0) return `+${fmt(v)}`;
  if (v < 0) return `−${fmt(-v)}`;
  return '0';
}

/** Parses a typed amount: comma or dot, empty = no value, anything else = invalid (undefined). */
export function parseAmount(text: string): number | null | undefined {
  const s = text.trim().replace(',', '.');
  if (s === '') return null;
  const v = Number(s);
  return Number.isFinite(v) && v >= 0 ? v : undefined;
}

/** The name of the estimation unit as shown next to numbers. */
export function unitName(d: PlanSprint): string {
  return d.unit === 'SP' ? t('points') : t('PD');
}

/** The other unit: a team planning in points sees person days next to it. */
export function other(d: PlanSprint, v: number): number | null {
  return d.unit === 'SP' && d.rate && d.rate > 0 ? v / d.rate : null;
}

/** The word for one piece of work: ticket or work package. */
export function itemWord(d: PlanSprint, plural = true): string {
  if (d.source === 'packages') return plural ? t('work packages') : t('work package');
  return plural ? t('tickets') : t('ticket');
}

export function sum(list: PlanTicket[]): number {
  return list.reduce((a, x) => a + (x.size ?? 0), 0);
}

export function productRowsFor(d: PlanSprint): PlanProduct[] {
  return d.products.filter((p) => p.active || p.pre != null || p.earmark > 0);
}

export const STAGE_TEXT = { past: 'closed', current: 'running', planned: 'planned', open: 'open' } as const;
