// The state and the course of a guided flow (Help > Guided flows). A tour always runs on the demo
// team: starting one switches the window to it, ending it switches back if the tour did so.

import { api } from '../api';
import { app, enterDemo, leaveDemo, selectSprint } from '../app.svelte';
import { registerCommands } from '../commands';
import { t } from '../i18n.svelte';
import { go } from '../router.svelte';
import { flowById, flows, type Flow, type SprintPick, type Step } from './flows';

export const tour = $state({
  flow: undefined as Flow | undefined,
  /** The steps shown: those of the flow that fit the team (a team without tracker skips some). */
  steps: [] as Step[],
  index: 0,
  /** The element of the current step was not found: the step is shown without a mark. */
  unmarked: false,
});

let enteredDemo = false;
let marked: Element | undefined;
let run = 0;

// A page loads its code and its data first; the mark waits for the element (60, 300, 800 ms).
const waits = [60, 300, 800];

/** Picks the sprint of a step in the sprints of the team: the running one or the next. */
export function pickSprint(pick: SprintPick, sprints: { id: string; state: string }[]): string {
  if (pick === 'running') return sprints.find((s) => s.state === 'current')?.id ?? '';
  return sprints.find((s) => s.state === 'future')?.id ?? '';
}

export function currentStep(): Step | undefined {
  return tour.steps[tour.index];
}

function unmark(): void {
  marked?.classList.remove('hl');
  marked = undefined;
}

async function show(): Promise<void> {
  const mine = ++run;
  unmark();
  const step = currentStep();
  if (!step) return;
  if (step.sprint) {
    const id = pickSprint(step.sprint, app.sprints);
    if (id) selectSprint(id);
  }
  go(step.route);
  tour.unmarked = false;
  if (!step.target) return;
  for (const wait of [0, ...waits]) {
    if (wait) await new Promise((r) => setTimeout(r, wait));
    if (mine !== run) return;
    const el = document.querySelector(step.target);
    if (el) {
      el.classList.add('hl');
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      marked = el;
      return;
    }
  }
  tour.unmarked = true;
}

/** The steps of a flow for the team shown: steps about the tracker are left out without one. */
async function stepsFor(flow: Flow): Promise<Step[]> {
  let source = 'tracker';
  try {
    source = (await api.Today(app.team)).source;
  } catch {
    /* keep all steps */
  }
  if (source === 'tracker') return flow.steps;
  return flow.withoutTracker ?? flow.steps.filter((s) => !s.trackerOnly);
}

/** Starts a flow on the demo team. */
export async function startTour(id: string): Promise<void> {
  const flow = flowById(id);
  if (!flow) return;
  if (tour.flow) await endTour();
  if (!app.demo) {
    await enterDemo();
    enteredDemo = true;
  }
  tour.steps = await stepsFor(flow);
  tour.flow = flow;
  tour.index = 0;
  await show();
}

export async function nextStep(): Promise<void> {
  if (!tour.flow) return;
  if (tour.index >= tour.steps.length - 1) {
    await endTour();
    return;
  }
  tour.index++;
  await show();
}

export async function previousStep(): Promise<void> {
  if (!tour.flow || tour.index === 0) return;
  tour.index--;
  await show();
}

/** Ends the tour; goes back to the data if the tour had switched to the demo team. */
export async function endTour(): Promise<void> {
  run++;
  unmark();
  tour.flow = undefined;
  tour.steps = [];
  tour.index = 0;
  tour.unmarked = false;
  if (enteredDemo) {
    enteredDemo = false;
    await leaveDemo();
    // The page the tour was started from: nothing on it belongs to the demo team any more.
    go('/help/guided');
  }
}

// "Guided flow: …" in the command palette, for every flow.
registerCommands(() =>
  flows.map((f) => ({
    id: `tour:${f.id}`,
    label: t('Guided flow: {name}', { name: f.title() }),
    group: 'help' as const,
    hint: f.id,
    words: 'tutorial guide anleitung rundgang hilfe',
    run: () => void startTour(f.id),
  })),
);
