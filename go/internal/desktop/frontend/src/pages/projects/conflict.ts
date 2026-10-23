// The notes the conflict view puts on the clipboard. Foresprint changes nothing in the plan; the
// PO takes the decision and keeps the note where the team keeps its minutes.

import { t } from '../../lib/i18n.svelte';
import type { ProjectsView } from '../../lib/types.projects';
import { num } from './format';

export type Note = 'accept' | 'talk';

/** The products that are tight or full and the contingents that do not last, one line each. */
function lines(view: ProjectsView): string[] {
  const name = (id: string) => view.products.find((p) => p.id === id)?.name ?? id;
  const short = view.fit
    .filter((f) => f.status === 'over')
    .map((f) => `- ${view.projects.find((p) => p.id === f.project)?.name ?? f.project}: ${t('contingent short by {n} PD (left {rest} PD, need {need} PD)', {
      n: num(f.missing, 1),
      rest: num(f.remaining, 1),
      need: num(f.need, 1),
    })}`);
  const products = view.conflict
    .filter((r) => r.light !== 'ok')
    .map((r) => {
      const demand = r.demand.map((d) => `${view.projects.find((p) => p.id === d.project)?.name ?? d.project} ${num(d.points, 1)}`).join(', ');
      return `- ${r.product ? name(r.product) : t('Team')}: ${t('budget {budget} {unit}, projects ask {demand}, left {rest} {unit}', {
        budget: num(r.budget, 1),
        unit: view.unit,
        demand: demand || '–',
        rest: num(r.rest, 1),
      })}`;
    });
  return [...products, ...short];
}

/** The text of a note for the PO: accepting the risk, or talking to the project lead. */
export function noteText(view: ProjectsView, kind: Note): string {
  const head =
    kind === 'accept'
      ? t('Sprint {sprint}: the PO accepts the risk that the projects crowd out daily business.', { sprint: view.conflictSprint })
      : t('Sprint {sprint}: the projects ask more than the budget of these products allows. Which project can wait?', { sprint: view.conflictSprint });
  return [head, '', ...lines(view)].join('\n');
}
