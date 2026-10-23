// Types of the Pre-plan and Plan pages (go/internal/app/types_plan.go). Keep them in step with
// the Go structs: the JSON names are the `json:"..."` tags.

export type Stage = 'past' | 'current' | 'planned' | 'open';
export type Source = 'tracker' | 'packages' | 'none';
export type Light = 'ok' | 'warn' | 'bad';

export interface PlanSplit {
  plan: number;
  carryIn: number;
  plannable: number;
  smallStuff: number;
  overbooked: boolean;
}

export interface PlanProduct {
  id: string;
  name: string;
  po: string;
  poName: string;
  default: number | null;
  pre: number | null;
  earmark: number;
  planned: number | null;
  prodPlanned: number | null;
  done: number | null;
  active: boolean;
  budget: number;
}

export interface PlanTicket {
  key: string;
  title: string;
  status: string;
  url: string;
  estimate: number | null;
  size: number | null;
  product: string;
  project: string;
  refined: boolean;
  sprint: string;
  inTracker: string;
  prodPct: number;
  prodSource: 'manual' | 'label' | 'rule' | 'none';
  remaining: number | null;
}

export interface RunningTicket extends PlanTicket {
  done: boolean;
  added: boolean;
}

export interface PlanProject {
  id: string;
  name: string;
  tickets: number;
  amount: number;
  needPD: number | null;
  bookedPD: number | null;
  usedPD: number | null;
  manual: boolean;
}

export interface PlanProdPerson {
  name: string;
  capacity: number;
  absence: number;
}

export interface PlanProduction {
  people: PlanProdPerson[];
  time: number;
  capPercent: number;
  available: number;
  /** Available is basis × share × cap (needs a Forecast PLAN); otherwise time × cap. */
  scaled: boolean;
  /** Part of the capacity that has production access, 0 to 1. */
  share: number;
  /** The plannable amount in PD. */
  basis: number;
  demand: number;
  demandSet: boolean;
  demandAmount: number;
  load: number | null;
  status: 'ok' | 'tight' | 'over';
  manual: number | null;
}

export interface PlanFrozen {
  tickets: number;
  commitment: number | null;
}

export interface CarryInput {
  ticket: string;
  rest: number;
  /** "" = the sprint of the view, a sprint id, "backlog" or "proforma:<name>". */
  target: string;
}

export interface Assumption {
  label: string;
  commitment: number | null;
  carry: CarryInput[];
  notDone: number | null;
  extra: number | null;
  restNext: number | null;
  /** From the Forecast page: share of the capacity in percent and extra person days off. */
  focusPercent?: number | null;
  extraAbsenceDays?: number | null;
}

export interface WhatIf {
  running: string;
  touched: boolean;
  commitment: number;
  notDone: number;
  extra: number;
  velocity: number;
  plan: number | null;
  planOriginal: number | null;
  low: number | null;
  high: number | null;
  rest: number;
  later: number;
  plannable: number;
  smallStuff: number;
}

export interface PlanSprint {
  team: string;
  sprint: string;
  start: string;
  end: string;
  days: number;
  stage: Stage;
  unit: 'SP' | 'PT';
  source: Source;
  trackerName: string;
  /** The team switched on writing the sprint back to the tracker. */
  writeBack: boolean;
  /** A write-back of this sprint went through in this session and can be taken back. */
  writeUndo: boolean;
  multiProduct: boolean;
  multiPO: boolean;
  production: boolean;
  absences: 'confirmed' | 'announced' | 'unknown';
  absenceDays: number;
  capacity: number | null;
  plan: number | null;
  planOriginal: number | null;
  low: number | null;
  high: number | null;
  rate: number | null;
  otherUnit: string;
  share: number;
  split: PlanSplit | null;
  carryLater: number;
  preplanned: number;
  earmarked: number;
  removed: string[];
  sprintPre: number | null;
  committed: number | null;
  products: PlanProduct[];
  tickets: PlanTicket[];
  candidates: PlanTicket[];
  projects: PlanProject[];
  /** The table product x project of the pre-planning; null without products or open projects. */
  matrix: PlanMatrix | null;
  prod: PlanProduction | null;
  frozen: PlanFrozen | null;
  assumptions: Assumption[];
  running: string;
  notes: string[];
}

/** Why the what-if table can be empty: open tickets in tracker sprints Foresprint does not know. */
export interface RunningHint {
  unresolved: number;
  names: string[];
}

export interface FreezeInput {
  tickets: string[];
  commitment: number | null;
  amounts: Record<string, number>;
  removed: string[];
}

/** The methods of the Pre-plan and Plan pages (go/internal/app/api_plan.go). */
export interface PlanApi {
  PlanSprint(team: string, sprint: string, assume: Assumption | null): Promise<PlanSprint>;
  RunningTickets(team: string, sprint: string): Promise<RunningTicket[]>;
  RunningHint(team: string, sprint: string): Promise<RunningHint>;
  WhatIf(team: string, sprint: string, assume: Assumption): Promise<WhatIf | null>;
  SaveAssumption(team: string, sprint: string, assume: Assumption): Promise<void>;
  SetPreplanned(team: string, sprint: string, product: string, value: number | null): Promise<void>;
  SetSprintPreplanned(team: string, sprint: string, value: number | null): Promise<void>;
  SetRemoved(team: string, sprint: string, ticket: string, removed: boolean): Promise<void>;
  TakeEarmarks(team: string, sprint: string): Promise<void>;
  UseDefaults(team: string, sprint: string): Promise<void>;
  SetProjectAmount(team: string, sprint: string, project: string, value: number | null): Promise<void>;
  SetProductionPT(team: string, sprint: string, value: number | null): Promise<void>;
  SetProductionPercent(team: string, ticket: string, percent: number | null): Promise<void>;
  FreezePlan(team: string, sprint: string, input: FreezeInput): Promise<string>;
  ReopenPlan(team: string, sprint: string): Promise<void>;
  SetMatrixCell(team: string, sprint: string, product: string, project: string, value: number | null): Promise<void>;
  UseMatrix(team: string, sprint: string): Promise<void>;
  PlanWritePreview(team: string, sprint: string): Promise<WritePreview>;
  PlanWriteApply(team: string, sprint: string, approved: string[]): Promise<WriteResult>;
  PlanWriteUndo(team: string, sprint: string): Promise<WriteResult>;
}

/** One ticket the write-back puts into another tracker sprint; an empty name is the backlog. */
export interface WriteMove {
  key: string;
  title: string;
  reason: 'committed' | 'taken_out' | 'undo';
  from: string;
  to: string;
  fromKnown: boolean;
}

/** What the write-back would do (go/internal/app/api_writeback.go); nothing is changed yet. */
export interface WritePreview {
  enabled: boolean;
  sprint: string;
  removedTarget: 'backlog' | 'pro_forma' | 'next';
  moves: WriteMove[];
  problems: string[];
  canUndo: boolean;
}

export interface WriteResult {
  done: WriteMove[];
  failed: WriteMove[];
  error: string;
  canUndo: boolean;
}

export interface PlanMatrix {
  projects: { id: string; name: string }[];
  cells: { product: string; project: string; value: number }[];
}
