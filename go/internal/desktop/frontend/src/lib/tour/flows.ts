// The guided flows (Help > Guided flows, flows.md decision 13): one walk-through per flow F1 to
// F6 and F8 to F11. Each step names a page, optionally the element to mark and a sprint to
// select, and says in a few sentences what to do there. They run on the demo team (Team Atlas),
// never on the person's data.
//
// `target` is a CSS selector, by convention `[data-tour="name"]` (the names are listed in
// go/internal/desktop/README.md). A page adds the attribute to the element a step talks about;
// when the element is missing the step is still shown, without the mark.

import { t } from '../i18n.svelte';

export type SprintPick = 'running' | 'next';

export interface Step {
  /** Page to show, e.g. "/sprint/plan". */
  route: string;
  /** Element to mark. */
  target?: string;
  /** Sprint to select before showing the page. */
  sprint?: SprintPick;
  /** The page has nothing to show for a team that keeps its work packages in Foresprint. */
  trackerOnly?: boolean;
  text: () => string;
}

export interface Flow {
  id: string;
  title: () => string;
  summary: () => string;
  steps: Step[];
  /** Steps for a team without a tracker; without them the tracker-only steps are left out. */
  withoutTracker?: Step[];
}

const tour = (name: string) => `[data-tour="${name}"]`;

export const flows: Flow[] = [
  {
    id: 'F1',
    title: () => t('First start'),
    summary: () => t('From the empty app to Today: storage, sign-in, team and where the work comes from.'),
    steps: [
      { route: '/setup', target: tour('firstrun-step'), text: () => t('The app does not know your data yet, so it starts with the setup. Choose where the team keeps its data: load it from an address, open a folder or start a new one.') },
      { route: '/setup', target: tour('firstrun-step'), text: () => t('If the server asks for a sign-in you paste a token and test it. Your name and email are entered once.') },
      { route: '/setup', target: tour('firstrun-step'), text: () => t('Then the team: open one that is already in the data, create a new one with name, region and first sprint, or open the demo team.') },
      { route: '/setup', target: tour('firstrun-step'), text: () => t('Finally the source of the work: work packages kept in Foresprint, no tickets, or a tracker such as Jira. You can change this later under Settings.') },
      { route: '/today', target: tour('today-running'), text: () => t('Today shows the next step for every sprint. The setup is finished; each choice stays changeable in the settings.') },
    ],
  },
  {
    id: 'F2',
    title: () => t('Groom the backlog'),
    summary: () => t('Check the sync, filter, order and earmark tickets, maintain the ticket panel, clear rule conflicts.'),
    steps: [
      { route: '/backlog', target: tour('backlog-sync'), trackerOnly: true, text: () => t('First the sync state. If it is stale or failed, a banner offers a retry. Work continues with the last data; nothing is locked.') },
      { route: '/backlog', target: tour('backlog-views'), text: () => t('Pick a saved view such as Refinement or click a filter. The list reacts at once, also while you search.') },
      { route: '/backlog', target: tour('backlog-list'), text: () => t('Order the tickets by dragging the handle up or down, or with Alt and the arrow keys. Dragging into a sprint earmarks the ticket; a toast offers Undo.') },
      { route: '/backlog', target: tour('backlog-ticket'), text: () => t('A click on the title opens the ticket panel. The key and the arrow open the ticket in the tracker.') },
      { route: '/backlog', target: tour('ticket-panel'), text: () => t('In the panel you maintain estimate, product, project and earmark and see whether the ticket is refined. The history is below.') },
      { route: '/backlog', target: tour('backlog-ruleflag'), trackerOnly: true, text: () => t('If no product rule or more than one applies, the row is marked. The product of the rule decides; you can set it by hand for this ticket.') },
    ],
  },
  {
    id: 'F3',
    title: () => t('Prepare and pre-plan a sprint'),
    summary: () => t('Clear absences, check readiness and set the amount per product from the earmarks.'),
    steps: [
      { route: '/sprint/prepare', sprint: 'next', target: tour('sprint-stepper'), text: () => t('Today says the next sprint needs preparation. The stages at the top are links; "missing" is only a hint, nothing is locked.') },
      { route: '/sprint/prepare', sprint: 'next', target: tour('prepare-grid'), text: () => t('The grid shows absences for this and the next sprints. Type the days directly; Tab or Enter moves on. A new entry is announced (open lock); a click on the lock confirms it.') },
      { route: '/sprint/prepare', sprint: 'next', target: tour('prepare-freeze'), text: () => t('"Freeze" confirms the whole allocation of a sprint: every entry counts as confirmed, empty cells as 0 days. A sprint with nobody absent is done this way too.') },
      { route: '/sprint/prepare', sprint: 'next', target: tour('prepare-ready'), text: () => t('Readiness sums up absences, refinement and pre-planning. Open points only warn; you can always go on.') },
      { route: '/sprint/preplan', sprint: 'next', target: tour('preplan-whatif'), text: () => t('While the running sprint is still open you estimate what will finish. Mark tickets as carried over and estimate their rest; the expected velocity falls by the full estimate, only the rest moves on.') },
      { route: '/sprint/preplan', sprint: 'next', target: tour('preplan-earmarks'), text: () => t('You can pre-plan at any time, also for later sprints. The earmarks from the backlog are listed by project and daily business, with a hint on the contingent.') },
      { route: '/sprint/preplan', sprint: 'next', target: tour('preplan-table'), text: () => t('One table per sprint: you enter the pre-planned amount, "Take over earmarks" makes a proposal. Planned and done are read-only at this stage.') },
      { route: '/sprint/preplan', sprint: 'next', target: tour('preplan-table'), text: () => t('Try it: an amount above the forecast PLAN shows a warning. It never blocks. When everything fits, the sprint is ready for planning.') },
    ],
  },
  {
    id: 'F4',
    title: () => t('Plan a sprint'),
    summary: () => t('Confirm absences, weigh tickets live against forecast, products and contingents, freeze the agreement.'),
    steps: [
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-absences'), text: () => t('First the absences: if they are only announced you confirm them right here. You can plan without confirming.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-sumbar'), text: () => t('At the top is the forecast PLAN with its range. The calculator button shows how it is calculated.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-lanes'), text: () => t('Candidates on the left, the sprint on the right, prefilled from the earmarks. Drag a ticket, or move it with Alt and the arrow keys.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-live'), text: () => t('Live: the sum against the range, products against their budget, projects against their contingent. This is a hint for the team, not a stop.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-lanes'), text: () => t('If the team does not want a ticket in the sprint, take it out. It then appears in the list "Adjust in the tracker".') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-freeze'), text: () => t('When everybody agrees, "Freeze the agreement" locks the plan. A planning minute is written and, if you wish, a label is set on the tracker ticket.') },
    ],
  },
  {
    id: 'F5',
    title: () => t('Close a sprint'),
    summary: () => t('Record velocity, scope change and what was done per product, freeze the person days and tag.'),
    steps: [
      { route: '/sprint/review', sprint: 'running', target: tour('review-velocity'), text: () => t('The review of the sprint: the velocity follows from the commitment, what was not done and what was additionally done.') },
      { route: '/sprint/review', sprint: 'running', target: tour('review-scope'), text: () => t('Enter the scope change: points not done and points done in addition. The velocity above follows along.') },
      { route: '/sprint/review', sprint: 'running', target: tour('review-done'), text: () => t('Done per product, with the share that needed production. The sum should match the velocity, otherwise a hint warns.') },
      { route: '/sprint/review', sprint: 'running', target: tour('review-capacity'), text: () => t('The available person days are frozen here. They give the actual rate used for contingents (an estimate).') },
      { route: '/sprint/review', sprint: 'running', target: tour('review-tag'), text: () => t('Optionally tag the sprint and share it with the team.') },
      { route: '/sprint/review', sprint: 'running', target: tour('review-close'), text: () => t('"Close sprint" writes the review minutes. Afterwards the next sprint shows on Today.') },
    ],
  },
  {
    id: 'F6',
    title: () => t('When will it be done?'),
    summary: () => t('Look at the forecast with its range, try assumptions, check a project and export the numbers.'),
    steps: [
      { route: '/forecast', target: tour('forecast-chart'), text: () => t('The forecast is always reachable. The chart shows the velocity of past sprints and the forecast PLAN of the coming ones with their range.') },
      { route: '/forecast', target: tour('forecast-table'), text: () => t('The table lists capacity, forecast PLAN and range. Missing absences are only a hint; the page stays usable. The calculator symbol explains each row.') },
      { route: '/forecast', target: tour('forecast-whatif'), text: () => t('What if: change an assumption and see the result in the chart. Only if you save it explicitly does it become a prognosis; otherwise the forecast stays as it is.') },
      { route: '/forecast', target: tour('forecast-analysis'), text: () => t('Analysis: pick a project. Foresprint names the likely sprint with its range and compares it with the end of the project.') },
      { route: '/forecast', target: tour('forecast-history'), text: () => t('Products over time: the same stages as in the sprint views, across many sprints and grouped by PO. Check that budgets match the agreement.') },
      { route: '/forecast', target: tour('forecast-reports'), text: () => t('Reports and export: Excel or a Markdown report. The question is answered and the result is where it is needed.') },
    ],
  },
  {
    id: 'F8',
    title: () => t('Prepare with projects and report back'),
    summary: () => t('Create a project, check the timeline and contingent, spot conflicts, report to the project lead.'),
    steps: [
      { route: '/projects', target: tour('projects-new'), text: () => t('Create a project: name, products, end, milestones and contingent in person days. This works without a tracker and offline.') },
      { route: '/projects', target: tour('projects-timeline'), text: () => t('The timeline shows the duration, the milestones with their traffic light (symbol and colour) and today.') },
      { route: '/projects', target: tour('projects-table'), text: () => t('If the demand fits budgets and contingents you continue with the pre-planning. Contingents are in person days; planned work is an estimate.') },
      { route: '/projects', target: tour('projects-conflict'), text: () => t('If it does not fit, the conflict view sets demand against product budget and contingent. The PO decides; Foresprint only recommends.') },
      { route: '/projects/self-service', target: tour('project-tickets'), text: () => t('Inside a project you see milestones, the contingent per month and the tickets by sprint. From here you move tickets in the backlog or the pre-planning.') },
      { route: '/projects/self-service', target: tour('project-report'), text: () => t('The report for the project lead shows booked, planned and done per sprint. Export it to pass it on.') },
    ],
  },
  {
    id: 'F9',
    title: () => t('Understand a calculation'),
    summary: () => t('From the calculator symbol at a number to the full explanation, and how to switch the display.'),
    steps: [
      { route: '/sprint/plan', sprint: 'next', target: tour('calc'), text: () => t('Next to derived numbers is a small calculator symbol. A click opens the calculation with the numbers put in.') },
      { route: '/help/calculations', target: tour('help-calculations'), text: () => t('Under Help > Calculations every calculation is written out once: the lead sentence, the formula, an example with your numbers and the special cases.') },
      { route: '/settings/personal', target: tour('personal-calc'), text: () => t('If you always want to see the calculations, switch to "always expanded". If you do not need them, hide them. This applies to you only.') },
    ],
  },
  {
    id: 'F10',
    title: () => t('Show tickets in a meeting'),
    summary: () => t('Share one window: show the ticket details large, page through and plan at the same time.'),
    steps: [
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-present'), text: () => t('In the planning you share only Foresprint. The presentation view shows the tickets of the sprint and the candidates large in the window.') },
      { route: '/present', text: () => t('Description, acceptance criteria, subtasks, links, comments and attachments come with the sync. The arrow keys page through; the space bar puts the ticket into the sprint or takes it out.') },
      { route: '/backlog', target: tour('ticket-panel'), text: () => t('The same details are in the ticket panel everywhere, for example in the backlog. The presentation view opens from there as well.') },
    ],
  },
  {
    id: 'F11',
    title: () => t('Take the planned sprint over into the tracker'),
    summary: () => t('Optional: write the sprint assignment from the planning to the tracker, with preview and undo.'),
    steps: [
      { route: '/settings/tickets', target: tour('settings-writeback'), trackerOnly: true, text: () => t('By default Foresprint only reads. Here the team switches writing back on and says where tickets that were taken out go.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-jira'), trackerOnly: true, text: () => t('In the planning, "Reconcile with the tracker" shows which tickets enter or leave the sprint in the tracker.') },
      { route: '/sprint/plan', sprint: 'next', target: tour('plan-jira-write'), trackerOnly: true, text: () => t('"Take over into the tracker" opens a preview. Untick what should stay, then write. Only the sprint field is written; the step is logged in the planning minutes and can be undone.') },
    ],
    withoutTracker: [
      { route: '/settings/tickets', text: () => t('This team keeps its work packages in Foresprint, so there is nothing to write back. A team with a tracker finds the switch for writing back here, and in the planning "Reconcile with the tracker" and "Take over into the tracker".') },
    ],
  },
];

export function flowById(id: string): Flow | undefined {
  return flows.find((f) => f.id === id);
}
