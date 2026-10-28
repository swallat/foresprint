// Types of the bindings of the Team area (go/internal/app/api_team*.go, api_rules.go).

export interface RuleOwner {
  kind: 'product' | 'project' | 'setting';
  id: string;
}

export interface RulePreview {
  valid: boolean;
  error?: string;
  /** Place of the problem in the text (0-based), -1 if unknown. */
  pos: number;
  /** The rule as Foresprint writes it. */
  normalized?: string;
  fields: string[];
  matches: number;
  points: number;
  sample: string[];
  clash: number;
  moved: number;
}

export interface Membership {
  from: string;
  /** "" = open. */
  to: string;
  fte: number;
}

export type PersonKind = 'member' | 'guest' | 'external';

export interface Person {
  /** "" for a new person; the core makes the id. */
  id: string;
  name: string;
  kind: PersonKind;
  production: boolean;
  memberships: Membership[];
  region?: string;
  country?: string;
  workweek?: string;
  /** Stands in a sprint that has begun: can be ended but not removed. Read-only. */
  used: boolean;
}

export interface PeopleView {
  today: string;
  /** The day a new person joins: the start of the first sprint while the team is in it, else today. */
  newFrom: string;
  /** Holiday country of the team. */
  country: string;
  sprintDays: number;
  production: boolean;
  people: Person[];
}

/** A planned absence: dates only, never a reason or kind. */
export interface AbsencePeriod {
  person: string;
  from: string;
  to: string;
  confirmed: boolean;
}

export interface Product {
  /** "" for a new product. */
  id: string;
  name: string;
  /** The PO reference as stored: the id of a PO of the team (a plain name in a file from 0.8). */
  po: string;
  /** Agreed share 0..1; null = the remainder is split evenly. */
  share: number | null;
  rule: string;
  from: string;
  to: string;
  tickets: number;
  points: number;
  ended: boolean;
  /** Has history: it is ended, not deleted. */
  used: boolean;
}

export interface Owner {
  id: string;
  name: string;
  /** Id of the person entry of a PO who works in the team, "" = outside. */
  person: string;
  products: number;
  inTeam: boolean;
  fte: number;
}

export type TicketSource = 'tracker' | 'packages' | 'none';

export interface ProductsView {
  source: TicketSource;
  today: string;
  multi: boolean;
  legacy: boolean;
  products: Product[];
  owners: Owner[];
  defaults: ProductsDefault[];
}

/** Default amount of one sprint: Forecast PLAN (times the plannable share on the roadmap basis) times each product's share. */
export interface ProductsDefault {
  sprint: string;
  running: boolean;
  roadmap: boolean;
  plan: number | null;
  available: number | null;
  roadmapShare: number;
  /** Sum of the fixed amounts and the number of products without a fixed share (they split the rest evenly). */
  fixed: number;
  rest: number;
  values: Record<string, number>;
}

export interface EndResult {
  view: ProductsView;
  moved: number;
  undo: number;
}

export interface Step {
  view: ProductsView;
  undo: number;
}

export interface Holiday {
  date: string;
  name: string;
}

export type CalendarState = 'finished' | 'running' | 'open' | 'planned';

export interface CalendarRow {
  id: string;
  start: string;
  /** The last day (the stored end is the day after). */
  last: string;
  workdays: number;
  holidays: Holiday[];
  state: CalendarState;
  /** Finished sprints are locked. */
  locked: boolean;
  /** Has a sprint file. */
  saved: boolean;
}

export interface NamingRule {
  from: string;
  pattern: string;
}

export interface CalendarView {
  today: string;
  country: string;
  region: string;
  rows: CalendarRow[];
  naming: NamingRule[];
  /** The pattern that names the next sprint, "" = none. */
  pattern: string;
  placeholders: string[];
  proForma: string[];
}

export interface LastDay {
  id: string;
  last: string;
}

export interface CalendarResult {
  view: CalendarView;
  moved: number;
  undo: number;
}

export type ChangeKind = 'last' | 'start' | 'remove' | 'rhythm';
export type ChangeMode = 'shift' | 'keep';
export type ChangeNaming = 'keep' | 'renumber';

export interface CalendarChange {
  kind: ChangeKind;
  id: string;
  date: string;
  mode: ChangeMode;
  naming: ChangeNaming;
}

export interface ChangeNote {
  kind: 'moved' | 'longer' | 'shorter' | 'starts-later' | 'starts-earlier' | 'gone' | 'renamed';
  days: number;
  from: string;
}

export interface ChangeRow {
  id: string;
  old: string;
  oldStart: string;
  oldLast: string;
  start: string;
  last: string;
  workdays: number;
  gone: boolean;
  saved: boolean;
  notes: ChangeNote[];
}

export interface CalendarPreview {
  rows: ChangeRow[];
  /** Sprints with a file that fall away. */
  lost: string[];
  /** Sprints without a file that fall away. */
  free: string[];
  target: string;
  /** The sprint whose last day really changes (new start or removal). */
  via: string;
  /** The later sprints have to move along. */
  forced: boolean;
  mode: ChangeMode;
  namingChoice: boolean;
  problem: string;
}

export interface NamePreview {
  index: number;
  start: string;
  old: string;
  new: string;
  locked: boolean;
  saved: boolean;
  changes: boolean;
}

export interface NamingPreview {
  rows: NamePreview[];
  duplicate: string;
  noNumber: boolean;
  problem: string;
  count: number;
}

export interface TeamApi {
  Calendar(team: string, count: number): Promise<CalendarView>;
  SaveLastDays(team: string, changes: LastDay[], count: number): Promise<CalendarResult>;
  PreviewCalendarChange(team: string, change: CalendarChange, count: number): Promise<CalendarPreview>;
  ApplyCalendarChange(team: string, change: CalendarChange, count: number): Promise<CalendarResult>;
  NamingPreview(team: string, pattern: string, from: string, all: boolean, count: number): Promise<NamingPreview>;
  ApplyNaming(team: string, pattern: string, from: string, all: boolean, count: number): Promise<CalendarResult>;
  RenameSprint(team: string, sprintId: string, newId: string, count: number): Promise<CalendarResult>;
  Products(team: string): Promise<ProductsView>;
  SaveProducts(team: string, products: Product[]): Promise<ProductsView>;
  EndProduct(team: string, id: string, lastDay: string, shares: Record<string, number>, target: string): Promise<EndResult>;
  ResumeProduct(team: string, id: string): Promise<Step>;
  AddOwner(team: string, name: string): Promise<Step>;
  RenameOwner(team: string, id: string, name: string): Promise<Step>;
  RemoveOwner(team: string, id: string, handover: Record<string, string>): Promise<Step>;
  SetOwnerInTeam(team: string, id: string, inTeam: boolean, fte: number): Promise<Step>;
  Undo(team: string, token: number): Promise<void>;
  People(team: string): Promise<PeopleView>;
  SavePeople(team: string, people: Person[]): Promise<PeopleView>;
  AbsencePeriods(team: string): Promise<AbsencePeriod[]>;
  SaveAbsencePeriods(team: string, list: AbsencePeriod[]): Promise<AbsencePeriod[]>;
  RuleFields(team: string): Promise<string[]>;
  CheckRule(team: string, text: string, owner: RuleOwner): Promise<RulePreview>;
}
