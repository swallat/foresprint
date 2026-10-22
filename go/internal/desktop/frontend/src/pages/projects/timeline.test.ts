import { describe, expect, it } from 'vitest';
import type { SprintInfo } from '../../lib/types';
import type { ProjectView } from '../../lib/types.projects';
import { addDays, addMonths, bandsOf, buildTimeline, windowOf, wrapPieces } from './timeline';

const sprints: SprintInfo[] = [
  { id: '2026.20', start: '2026-09-28', end: '2026-10-11', state: 'past' },
  { id: '2026.21', start: '2026-10-12', end: '2026-10-25', state: 'current' },
  { id: '2026.22', start: '2026-10-26', end: '2026-11-08', state: 'future' },
];

const project = (over: Partial<ProjectView>): ProjectView => ({
  id: 'p',
  name: 'Project',
  products: ['a'],
  start: '',
  end: '2026-12-18',
  note: '',
  rule: '',
  light: 'none',
  reason: '',
  priority: 1,
  booked: null,
  done: null,
  planned: null,
  donePoints: 0,
  plannedPoints: 0,
  months: [],
  used: null,
  remaining: null,
  usedStatus: '',
  usedHand: null,
  contact: '',
  openScope: null,
  open: 0,
  milestones: [],
  state: '',
  closedAt: '',
  history: false,
  ...over,
});

const base = {
  today: '2026-10-22',
  products: [{ id: 'a', name: 'Alpha' }],
  sprints,
  sprintDays: 14,
  customTo: '',
  monthName: (m: string) => m,
};

describe('dates', () => {
  it('adds days and months', () => {
    expect(addDays('2026-10-30', 3)).toBe('2026-11-02');
    expect(addMonths('2026-10-22', 3)).toBe('2027-01-22');
  });
});

describe('window', () => {
  it('starts with the running sprint and ends N months after today', () => {
    expect(windowOf('2026-10-22', sprints, [], '2', '')).toEqual({ from: '2026-10-12', to: '2026-12-22' });
  });
  it('reaches the last end of a project or milestone', () => {
    const p = project({ end: '2026-12-18', milestones: [{ id: 'm', name: 'x', date: '2027-02-01', tickets: [], done: 0, total: 0, light: 'none', hand: '', source: 'none', late: [] }] });
    expect(windowOf('2026-10-22', sprints, [p], 'all', '').to).toBe('2027-02-04');
  });
  it('takes a date of the user and is never shorter than 14 days', () => {
    expect(windowOf('2026-10-22', sprints, [], 'custom', '2026-11-30').to).toBe('2026-11-30');
    expect(windowOf('2026-10-22', sprints, [], 'custom', '2026-10-13').to).toBe('2026-10-26');
  });
});

describe('sprint bands', () => {
  it('continue the cadence after the calendar', () => {
    const bands = bandsOf(sprints, 14, '2026-12-01');
    expect(bands.at(-1)?.ext).toBe(true);
    expect(bands[3]).toEqual({ id: '2026.23', start: '2026-11-09', end: '2026-11-22', ext: true });
  });
});

describe('wrapping', () => {
  it('fills lines up to the width and keeps long pieces whole', () => {
    const lines = wrapPieces(['Self-Service', '2.0', 'Pilot', 'Verylongwordthatdoesnotfit'].map((text) => ({ text, len: text.length })), 14);
    expect(lines.map((l) => l.map((i) => i.text).join(' '))).toEqual(['Self-Service', '2.0 Pilot', 'Verylongwordthatdoesnotfit']);
  });
  it('wraps a long project name inside the label column', () => {
    const tl = buildTimeline({ ...base, projects: [project({ name: 'Customer self-service portal relaunch phase two' })], range: 'all' });
    expect(tl.rows[0]!.name.length).toBeGreaterThan(1);
    expect(tl.rows[0]!.name.join(' ')).toBe('Customer self-service portal relaunch phase two');
  });
});

describe('timeline', () => {
  const ms = (id: string, name: string, date: string) => ({ id, name, date, tickets: [], done: 0, total: 0, light: 'ok' as const, hand: '' as const, source: 'derived' as const, late: [] });
  it('puts overlapping milestone labels on separate lines', () => {
    const p = project({ milestones: [ms('1', 'First delivery of the pilot', '2026-11-20'), ms('2', 'Second delivery of the pilot', '2026-11-23')] });
    const tl = buildTimeline({ ...base, projects: [p], range: 'all' });
    const lines = tl.rows[0]!.marks.map((m) => m.line);
    expect(lines).toEqual([0, 1]);
    expect(tl.rows[0]!.h).toBeGreaterThan(58);
  });
  it('ends a bar that runs past the window in an arrow and counts later milestones', () => {
    const p = project({ end: '2027-06-30', milestones: [ms('1', 'Late', '2027-05-01')] });
    const tl = buildTimeline({ ...base, projects: [p], range: '2' });
    expect(tl.rows[0]!.cut).toBe(true);
    expect(tl.rows[0]!.later).toBe(1);
    expect(tl.rows[0]!.marks).toHaveLength(0);
  });
  it('marks today only inside the window', () => {
    const p = project({});
    expect(buildTimeline({ ...base, projects: [p], range: '2' }).todayX).not.toBeNull();
    expect(buildTimeline({ ...base, today: '2026-10-22', projects: [p], range: 'custom', customTo: '2026-10-25' }).todayX).not.toBeNull();
  });
  it('keeps every milestone label inside the drawing', () => {
    const p = project({ milestones: [ms('1', 'A rather long milestone name at the edge', '2026-12-18')] });
    const tl = buildTimeline({ ...base, projects: [p], range: 'all' });
    const mark = tl.rows[0]!.marks[0]!;
    expect(mark.x).toBeLessThanOrEqual(tl.W - tl.R);
    expect(mark.anchor).toBe('end');
  });
});
