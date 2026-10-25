// Geometry of the portfolio timeline (flows.md F8). Pure functions: the component only draws what
// buildTimeline returns, so the layout rules can be tested without a browser.
//
// Rules: long names and product lists wrap inside the label column and the row grows, nothing is
// cut off; milestone labels sit under their diamond, and a label that would touch the previous
// one moves to the next line; a bar that runs past the window ends in an arrow.

import { shortNames } from '../../lib/axis';
import type { SprintInfo } from '../../lib/types';
import type { Light, MilestoneView, ProductRef, ProjectView } from '../../lib/types.projects';

export type Range = '2' | '3' | '6' | 'all' | 'custom';
export const RANGES: Range[] = ['2', '3', '6', 'all'];

const DAY = 86400000;
export const dayNum = (iso: string): number => {
  const [y, m, d] = iso.split('-').map(Number);
  return Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) / DAY;
};
export const addDays = (iso: string, n: number): string => new Date((dayNum(iso) + n) * DAY).toISOString().slice(0, 10);
export const addMonths = (iso: string, n: number): string => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1 + n, d ?? 1)).toISOString().slice(0, 10);
};

export interface Window {
  from: string;
  to: string;
}

/** The visible window: from the start of the running sprint to N months after today, to the last
 * end of a project, or to a date chosen by the user. It always spans at least 14 days. */
export function windowOf(
  today: string,
  sprints: SprintInfo[],
  projects: ProjectView[],
  range: Range,
  customTo: string,
): Window {
  const cur = sprints.find((s) => s.start <= today && today <= s.end);
  const from = cur?.start ?? today;
  const lastEnd = projects.reduce((acc, p) => {
    const dates = [p.end, ...p.milestones.map((m) => m.date)].filter(Boolean);
    return dates.reduce((a, d) => (d > a ? d : a), acc);
  }, today);
  let to: string;
  if (range === 'custom' && customTo) to = customTo;
  else if (range === 'all') to = addDays(lastEnd, 3);
  else to = addMonths(today, Number(range === 'custom' ? 3 : range));
  const min = addDays(from, 14);
  return { from, to: to > min ? to : min };
}

export interface Band {
  id: string;
  start: string;
  end: string;
  /** Not in the sprint calendar yet: follows the usual cadence (shown in italics). */
  ext: boolean;
}

/** Known sprints, continued with the regular length so that long windows still show sprints. */
export function bandsOf(sprints: SprintInfo[], sprintDays: number, to: string): Band[] {
  const out: Band[] = sprints.map((s) => ({ id: s.id, start: s.start, end: s.end, ext: false }));
  let last: Band | undefined = out.at(-1);
  if (!last) return out;
  const len = Math.max(1, sprintDays);
  for (let guard = 0; last.end < to && guard < 200; guard++) {
    const parts: string[] = last.id.split('.');
    const year = parts[0] ?? '';
    const no = parts[1] ?? '0';
    const start = addDays(last.end, 1);
    last = { id: `${year}.${String(Number(no) + 1).padStart(2, '0')}`, start, end: addDays(start, len - 1), ext: true };
    out.push(last);
  }
  return out;
}

export interface Piece {
  text: string;
  len: number;
}

/** Fills lines with pieces so that no line exceeds `max` characters (a piece alone may). */
export function wrapPieces<T extends Piece>(items: T[], max: number, gap = 1): T[][] {
  const lines: { items: T[]; len: number }[] = [];
  for (const it of items) {
    const last = lines.at(-1);
    if (last && last.len + gap + it.len <= max) {
      last.items.push(it);
      last.len += gap + it.len;
    } else {
      lines.push({ items: [it], len: it.len });
    }
  }
  return lines.map((l) => l.items);
}

export interface MilestoneMark {
  m: MilestoneView;
  x: number;
  anchor: 'middle' | 'end';
  /** Text line under the diamond, 0 = first. */
  line: number;
  label: string;
}

export interface Row {
  project: ProjectView;
  y: number;
  h: number;
  name: string[];
  products: ProductRef[][];
  barEnd: number;
  /** The project ends after the window: the bar ends in an arrow. */
  cut: boolean;
  later: number;
  marks: MilestoneMark[];
}

export interface BandDraw {
  band: Band;
  x0: number;
  x1: number;
  label: boolean;
  /** Axis text without the prefix all sprints share; the full id goes in the tooltip. */
  short: string;
  shaded: boolean;
}

export interface Timeline {
  W: number;
  H: number;
  L: number;
  R: number;
  T: number;
  window: Window;
  rows: Row[];
  bands: BandDraw[];
  months: { x: number; label: string; show: boolean }[];
  firstMonth: string;
  todayX: number | null;
  x: (iso: string) => number;
}

const W = 960;
const L = 210;
const R = 20;
const T = 48;
const ROW = 58;
const MS_FONT = 6.7;

export function buildTimeline(args: {
  today: string;
  projects: ProjectView[];
  products: ProductRef[];
  sprints: SprintInfo[];
  sprintDays: number;
  range: Range;
  customTo: string;
  monthName: (ym: string) => string;
}): Timeline {
  const { today, projects, products, sprints } = args;
  const win = windowOf(today, sprints, projects, args.range, args.customTo);
  const t0 = dayNum(win.from);
  const t1 = dayNum(win.to);
  const plotW = W - L - R;
  const x = (iso: string) => L + ((dayNum(iso) - t0) / (t1 - t0)) * plotW;
  const inWin = (iso: string) => iso >= win.from && iso <= win.to;
  const nameCh = Math.floor((L - 20) / 8);
  const subCh = Math.floor((L - 20) / 6.6);
  const productOf = (id: string): ProductRef => products.find((p) => p.id === id) ?? { id, name: id };

  const rows: Row[] = [];
  let y = T;
  for (const p of projects) {
    const name = wrapPieces(
      p.name.split(' ').map((w) => ({ text: w, len: w.length })),
      nameCh,
    ).map((l) => l.map((i) => i.text).join(' '));
    const prods = wrapPieces(
      p.products.map((id) => ({ text: productOf(id).name, len: productOf(id).name.length + 2, product: productOf(id) })),
      subCh,
      0,
    ).map((l) => l.map((i) => i.product));
    const lineEnds: number[] = [];
    const marks: MilestoneMark[] = p.milestones
      .filter((m) => inWin(m.date))
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((m) => {
        const mx = Math.min(x(m.date), W - R - 9);
        const w = (m.name.length + 9) * MS_FONT;
        const anchor = mx + w / 2 > W - R ? 'end' : 'middle';
        const a0 = anchor === 'end' ? mx + 9 - w : mx - w / 2;
        const a1 = a0 + w;
        let line = lineEnds.findIndex((e) => e + 10 < a0);
        if (line < 0) {
          line = lineEnds.length;
          lineEnds.push(a1);
        } else {
          lineEnds[line] = a1;
        }
        return { m, x: mx, anchor, line, label: m.name } satisfies MilestoneMark;
      });
    const h = Math.max(ROW + Math.max(0, lineEnds.length - 1) * 14, 14 + name.length * 16 + prods.length * 14 + 14);
    const end = p.end || win.to;
    rows.push({
      project: p,
      y,
      h,
      name,
      products: prods,
      barEnd: Math.min(x(end), W - R),
      cut: end > win.to,
      later: p.milestones.filter((m) => m.date > win.to).length,
      marks,
    });
    y += h;
  }
  const H = y + 14;

  const all = bandsOf(sprints, args.sprintDays, win.to).filter((b) => b.end >= win.from && b.start <= win.to);
  const short = shortNames(all.map((b) => b.id));
  const labelW = Math.max(0, ...short.map((n) => n.length)) * 6.8 + 10;
  const spans = all.map((b) => ({ x0: Math.max(L, x(b.start)), x1: Math.min(W - R, x(addDays(b.end, 1))) }));
  // Thin by the narrowest full band, not by the configured length: calendar sprints can differ from it.
  const full = spans.slice(1, -1).map((sp) => sp.x1 - sp.x0);
  const narrow = Math.max(1, Math.min(...(full.length > 0 ? full : spans.map((sp) => sp.x1 - sp.x0)), plotW));
  const every = Math.max(1, Math.ceil(labelW / narrow));
  let labelEnd = -Infinity;
  const bands: BandDraw[] = all.map((b, i) => {
    const { x0, x1 } = spans[i] ?? { x0: L, x1: L };
    const mid = (x0 + x1) / 2;
    // A label is drawn only if it fits inside the plot and does not touch the previous one.
    const label = i % every === 0 && mid + labelW / 2 < W && mid - labelW / 2 > labelEnd;
    if (label) labelEnd = mid + labelW / 2;
    return { band: b, x0, x1, short: short[i] ?? b.id, label, shaded: i % 2 === 0 };
  });

  const months: Timeline['months'] = [];
  let lastLx = L + 4 + 44;
  for (let m = addMonths(`${win.from.slice(0, 8)}01`, 1); m <= win.to; m = addMonths(m, 1)) {
    const mx = x(m);
    const show = mx + 4 > lastLx + 6 && mx + 48 < W;
    if (show) lastLx = mx + 48;
    months.push({ x: mx, label: args.monthName(m.slice(0, 7)), show });
  }

  return {
    W,
    H,
    L,
    R,
    T,
    window: win,
    rows,
    bands,
    months,
    firstMonth: args.monthName(win.from.slice(0, 7)),
    todayX: inWin(today) ? x(today) : null,
    x,
  };
}

/** The worst of a list of lights, ignoring "none". */
export function worst(lights: Light[]): Light {
  const rank: Record<Light, number> = { none: 0, ok: 1, warn: 2, bad: 3 };
  return lights.reduce<Light>((a, b) => (rank[b] > rank[a] ? b : a), 'none');
}
