// Small rules about people and their membership periods, used by the people page. Dates are
// "YYYY-MM-DD" texts, which compare correctly as text.

import type { Membership, Person } from '../types.team';

/** The period that counts on `today`: the one covering it, else the next one, else the last. */
export function currentPeriod(p: Person, today: string): Membership | undefined {
  const covering = p.memberships.find((m) => m.from <= today && (m.to === '' || today <= m.to));
  return covering ?? p.memberships.find((m) => m.from > today) ?? p.memberships[p.memberships.length - 1];
}

/** True while the person is in the team on `today` or will join later. */
export function isCurrent(p: Person, today: string): boolean {
  return p.memberships.some((m) => m.to === '' || m.to >= today);
}

export function entry(p: Person): string {
  return p.memberships[0]?.from ?? '';
}

/** The leaving day, "" if the person has no end. */
export function leaving(p: Person): string {
  const last = p.memberships[p.memberships.length - 1];
  return last?.to ?? '';
}

/** Share on `today` (0 when not in the team). */
export function fteOn(p: Person, today: string): number {
  const m = p.memberships.find((x) => x.from <= today && (x.to === '' || today <= x.to));
  return m?.fte ?? 0;
}

function dayBefore(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** A new share from `from` on: closes the open period the day before and starts a new one. */
export function withNewShare(p: Person, from: string, fte: number): Person {
  const ms = p.memberships.map((m) => ({ ...m }));
  const last = ms[ms.length - 1];
  if (!last || from <= last.from) return p;
  const to = last.to;
  last.to = dayBefore(from);
  ms.push({ from, to, fte });
  return { ...p, memberships: ms };
}

/** Sets the share of the period that counts on `today`. */
export function withShare(p: Person, today: string, fte: number): Person {
  const cur = currentPeriod(p, today);
  return { ...p, memberships: p.memberships.map((m) => (m === cur ? { ...m, fte } : { ...m })) };
}

/** Sets the leaving day: the end of the last period; "" makes it open again. */
export function withLeaving(p: Person, day: string): Person {
  const ms = p.memberships.map((m) => ({ ...m }));
  const last = ms[ms.length - 1];
  if (last) last.to = day;
  return { ...p, memberships: ms };
}

/** A person who returns: a new period from `from` with the share they had last. */
export function rejoined(p: Person, from: string): Person {
  const last = p.memberships[p.memberships.length - 1];
  return { ...p, memberships: [...p.memberships.map((m) => ({ ...m })), { from, to: '', fte: last?.fte ?? 1 }] };
}

export type PeriodProblem = '' | 'from' | 'order' | 'fte' | 'overlap';

/** The first problem of the periods of one person ("" = fine); the core checks again. */
export function periodProblem(p: Person): PeriodProblem {
  const ms = p.memberships;
  for (let i = 0; i < ms.length; i++) {
    const m = ms[i]!;
    if (m.from === '') return 'from';
    if (m.to !== '' && m.to < m.from) return 'order';
    if (!(m.fte > 0 && m.fte <= 1)) return 'fte';
    const prev = ms[i - 1];
    if (prev && (prev.to === '' || m.from <= prev.to)) return 'overlap';
  }
  return '';
}

/** External people are temporary: no end date is something to point out. */
export function needsEnd(p: Person): boolean {
  return p.kind === 'external' && leaving(p) === '';
}
