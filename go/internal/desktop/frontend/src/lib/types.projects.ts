// Types of the projects page (go/internal/app/types_projects.go). Dates are YYYY-MM-DD, months
// YYYY-MM; amounts of the contingent are person days (PT).

import type { SprintInfo } from './types';

export type Light = 'ok' | 'warn' | 'bad' | 'none';

export interface ProductRef {
  id: string;
  name: string;
}

export interface MilestoneView {
  id: string;
  name: string;
  date: string;
  tickets: string[];
  done: number;
  total: number;
  light: Light;
  /** The light set by hand; '' = derived from the tickets. */
  hand: HandLight;
  source: 'hand' | 'derived' | 'none';
  /** Open tickets that end after the date. */
  late: string[];
}

export type HandLight = '' | 'green' | 'yellow' | 'red';
export type UseStatus = '' | 'ok' | 'tight' | 'over';

export interface MonthRow {
  month: string;
  booked: number;
  done: number | null;
  planned: number | null;
  /** Consumption entered by hand (PD). */
  used: number | null;
  remaining: number | null;
  status: UseStatus;
}

export interface SprintRow {
  sprint: string;
  state: 'current' | 'future';
  booked: number;
  planned: number | null;
  done: number | null;
}

export interface ProjectView {
  id: string;
  name: string;
  products: string[];
  start: string;
  end: string;
  note: string;
  rule: string;
  light: Light;
  reason: string;
  priority: number;
  booked: number | null;
  done: number | null;
  planned: number | null;
  donePoints: number;
  plannedPoints: number;
  months: MonthRow[];
  /** Consumption entered by hand in PD (nil = not entered), what is left, and the core's verdict. */
  used: number | null;
  remaining: number | null;
  usedStatus: UseStatus;
  /** The total entered by hand (the form edits this one). */
  usedHand: number | null;
  contact: string;
  openScope: number | null;
  open: number;
  milestones: MilestoneView[];
  state: '' | 'finished' | 'cancelled';
  /** The day a closed project ended; its end keeps the planned end. */
  closedAt: string;
  history: boolean;
}

export interface DemandCell {
  project: string;
  points: number;
}

export interface ConflictRow {
  product: string;
  budget: number;
  demand: DemandCell[];
  rest: number;
  light: 'ok' | 'warn' | 'bad';
  suggest: ConflictSuggestion;
}

/** What the core recommends for a product: nothing, move one ticket a sprint later, or talk to the project lead. */
export interface ConflictSuggestion {
  kind: 'none' | 'move' | 'talk';
  ticket: string;
  project: string;
  projectName: string;
  light: Light;
  points: number;
}

/** Daily business of a product, without a light (PD). */
export interface DailyRow {
  product: string;
  budget: number | null;
  done: number | null;
  planned: number | null;
}

/** The need of a project from the sprint ahead against what is left of its contingent (PD). */
export interface ContingentFit {
  project: string;
  remaining: number | null;
  need: number | null;
  status: '' | 'ok' | 'tight' | 'over';
  missing: number | null;
}

export interface ProjectsView {
  today: string;
  enabled: boolean;
  source: 'tracker' | 'packages' | 'none';
  unit: string;
  rate: number | null;
  products: ProductRef[];
  projects: ProjectView[];
  closed: ProjectView[];
  sprints: SprintInfo[];
  sprintDays: number;
  conflictSprint: string;
  conflict: ConflictRow[];
  /** Daily business per product: budget of conflictSprint, finished in dailyDoneSprint (the running sprint). */
  daily: DailyRow[];
  dailyDoneSprint: string;
  fit: ContingentFit[];
  problem: string;
}

export interface TicketLine {
  key: string;
  title: string;
  status: string;
  /** Sprint in the tracker, else the earmark; '' = not earmarked. */
  sprint: string;
  estimate: number | null;
  done: boolean;
  product: string;
  estimatePD: number | null;
  refined: boolean;
  /** The sprint the distribution puts a ticket without sprint in. */
  forecast: string;
}

export interface ProjectDetail extends ProjectsView {
  project: ProjectView;
  report: SprintRow[];
  tickets: TicketLine[];
}

export interface MilestoneInput {
  id: string;
  name: string;
  date: string;
  tickets: string[];
  light: HandLight;
}

export interface ProjectInput {
  id: string;
  name: string;
  products: string[];
  start: string;
  end: string;
  note: string;
  rule: string;
  booked: number | null;
  used: number | null;
  contact: string;
  months: Record<string, number>;
  usedMonths: Record<string, number>;
  openScope: number | null;
  milestones: MilestoneInput[];
}

export interface CloseInput {
  id: string;
  how: 'finished' | 'cancelled';
  at: string;
  moveTo: string;
}

export interface ProjectsApi {
  Projects(team: string): Promise<ProjectsView>;
  Project(team: string, id: string): Promise<ProjectDetail>;
  SaveProject(team: string, input: ProjectInput): Promise<string>;
  CloseProject(team: string, input: CloseInput): Promise<void>;
  ReopenProject(team: string, id: string): Promise<void>;
  DeleteProject(team: string, id: string): Promise<void>;
  UndoProjects(team: string): Promise<void>;
}
