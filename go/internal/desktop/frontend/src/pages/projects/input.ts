import type { ProjectInput, ProjectView } from '../../lib/types.projects';

/** The form values of an existing project (to change one field and save the rest unchanged). */
export function inputOf(p: ProjectView): ProjectInput {
  return {
    id: p.id,
    name: p.name,
    products: p.products,
    start: p.start,
    end: p.end,
    note: p.note,
    rule: p.rule,
    booked: p.booked,
    used: p.used,
    contact: p.contact,
    months: Object.fromEntries(p.months.filter((m) => m.booked > 0).map((m) => [m.month, m.booked])),
    usedMonths: Object.fromEntries(p.months.filter((m) => m.used !== null).map((m) => [m.month, m.used as number])),
    openScope: p.openScope,
    milestones: p.milestones.map((m) => ({ id: m.id, name: m.name, date: m.date, tickets: m.tickets, light: m.hand })),
  };
}
