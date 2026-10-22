// Types of the bindings of the Team area (go/internal/app/api_team*.go, api_rules.go).

export interface RuleOwner {
  kind: 'product' | 'project';
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

export interface TeamApi {
  People(team: string): Promise<PeopleView>;
  SavePeople(team: string, people: Person[]): Promise<PeopleView>;
  AbsencePeriods(team: string): Promise<AbsencePeriod[]>;
  SaveAbsencePeriods(team: string, list: AbsencePeriod[]): Promise<AbsencePeriod[]>;
  RuleFields(team: string): Promise<string[]>;
  CheckRule(team: string, text: string, owner: RuleOwner): Promise<RulePreview>;
}
