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
}

export interface MonthRow {
  month: string;
  booked: number;
  done: number | null;
  planned: number | null;
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
  openScope: number | null;
  open: number;
  milestones: MilestoneView[];
  state: '' | 'finished' | 'cancelled';
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
  problem: string;
}

export interface TicketLine {
  key: string;
  title: string;
  status: string;
  sprint: string;
  estimate: number | null;
  done: boolean;
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
  months: Record<string, number>;
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
