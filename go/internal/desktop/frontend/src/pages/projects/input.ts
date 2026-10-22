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
    months: Object.fromEntries(p.months.map((m) => [m.month, m.booked])),
    openScope: p.openScope,
    milestones: p.milestones.map((m) => ({ id: m.id, name: m.name, date: m.date, tickets: m.tickets })),
  };
}
