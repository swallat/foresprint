// Rules for editing planned absence periods (dates only, never a reason).
import type { AbsencePeriod } from '../types.team';

/** The period with a change applied, or null when the result is not allowed (kept as saved). */
export function changed(a: AbsencePeriod, patch: Partial<AbsencePeriod>, openFrom: string): AbsencePeriod | null {
  const next = { ...a, ...patch };
  if (isFixedStart(a, openFrom) && next.from !== a.from) return null; // finished days stay as they are
  if (isFixedStart(a, openFrom) && next.to < openFrom) return null; // the end may not cut into finished sprints
  if (patch.from && openFrom && patch.from < openFrom && patch.from !== a.from) return null;
  if (patch.from && patch.from > next.to) next.to = patch.from; // the period moves with its first day
  if (next.from === '' || next.to === '' || next.to < next.from) return null;
  return next;
}

/** A new one-day period for a person, a week after the last one and never in finished sprints. */
export function created(absences: AbsencePeriod[], person: string, today: string, openFrom: string): AbsencePeriod {
  const mine = absences.filter((a) => a.person === person).sort((a, b) => a.from.localeCompare(b.from));
  const day = new Date(`${mine.length ? mine[mine.length - 1]!.to : today}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + (mine.length ? 7 : 0));
  const earliest = openFrom > today ? openFrom : today;
  const iso = day.toISOString().slice(0, 10);
  const from = iso < earliest ? earliest : iso;
  return { person, from, to: from, confirmed: false };
}

/** Days in finished sprints stay as they were: whole finished periods are locked. */
export const isLocked = (a: AbsencePeriod, openFrom: string) => openFrom !== '' && a.to < openFrom;
export const touchesFinished = (a: AbsencePeriod, openFrom: string) => openFrom !== '' && a.from < openFrom && a.to >= openFrom;

/** A period that starts in a finished sprint keeps its first day and cannot be deleted: only its end moves. */
export const isFixedStart = (a: AbsencePeriod, openFrom: string) => openFrom !== '' && a.from < openFrom;
/** The same period (the list is replaced as a whole after every save, so identity is not enough). */
export const same = (a: AbsencePeriod, b: AbsencePeriod) => a.person === b.person && a.from === b.from && a.to === b.to;
