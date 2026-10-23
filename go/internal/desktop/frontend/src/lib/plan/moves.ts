import type { PlanSprint } from '../types.plan';

/** True when the ticket already sits in the target column, so a drop there (re-sorting) changes nothing. */
export function isNoopMove(d: Pick<PlanSprint, 'tickets' | 'candidates'>, key: string, to: 'sprint' | 'candidates'): boolean {
  const inSprint = (d.tickets ?? []).some((q) => q.key === key);
  return to === 'sprint' ? inSprint : !inSprint;
}
