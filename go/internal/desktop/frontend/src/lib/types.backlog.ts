// Types of the Backlog bindings (go/internal/app/types_backlog.go).

export type TicketSource = 'tracker' | 'packages' | 'none';
export type SizeSource = 'refined' | 'rough' | 'manual' | 'none';
export type RuleHint = '' | 'none' | 'several' | 'project';

export interface Named {
  id: string;
  name: string;
  closed?: boolean;
}

export interface BacklogTicket {
  key: string;
  title: string;
  status: string;
  type: string;
  priority: string;
  assignee: string;
  url: string;
  size: number | null;
  sizeSource: SizeSource;
  refined: boolean;
  refinedUnclear: boolean;
  product: string;
  project: string;
  productSet: boolean;
  projectSet: boolean;
  ruleHint?: RuleHint;
  ruleProducts?: string[];
  earmark: string;
  trackerSprint: string;
  production: number | null;
  epic: string;
  labels: string[];
  dependsOn: string[];
  blocked: boolean;
}

export interface BacklogLane {
  sprint: string;
  start: string;
  end: string;
  plan: number | null;
  absences: 'confirmed' | 'announced' | 'unknown';
  tickets: BacklogTicket[];
}

export interface ProFormaSprint {
  name: string;
  tickets: BacklogTicket[];
}

export interface BacklogView {
  source: TicketSource;
  tracker: string;
  unit: string;
  products: Named[];
  projects: Named[];
  tickets: BacklogTicket[];
  lanes: BacklogLane[];
  proForma: ProFormaSprint[];
  imported: string;
  multi: boolean;
  production: boolean;
  cycles: string[][];
}

export interface Subtask {
  title: string;
  done: boolean;
}

export interface Comment {
  author: string;
  at: string;
  text: string;
}

export interface Dependency {
  key: string;
  title: string;
  earmark: string;
}

export interface TicketDetail extends BacklogTicket {
  description: string;
  acceptance: string;
  subtasks: Subtask[];
  comments: Comment[];
  dependencies: Dependency[];
  components: string[];
  estimate: number | null;
  remaining: number | null;
  note: string;
  editable: boolean;
  sprints: string[];
  statuses: string[];
  types: string[];
  priorities: string[];
  people: string[];
}

export interface WorkPackageInput {
  key: string;
  title: string;
  status: string;
  type: string;
  priority: string;
  assignee: string;
  product: string;
  project: string;
  estimate: number | null;
  refined: boolean;
  labels: string[];
  description: string;
  acceptance: string;
  subtasks: Subtask[];
  dependsOn: string[];
  comments: Comment[];
  done: boolean;
}

export interface BacklogApi {
  Backlog(team: string): Promise<BacklogView>;
  Ticket(team: string, key: string): Promise<TicketDetail>;
  SetEarmark(team: string, key: string, sprint: string, note: string): Promise<void>;
  SetEstimate(team: string, key: string, value: number | null): Promise<void>;
  SetRefined(team: string, key: string, refined: boolean): Promise<void>;
  SetAssignment(team: string, key: string, product: string, project: string, daily: boolean): Promise<void>;
  SetProduction(team: string, key: string, percent: number | null): Promise<void>;
  SaveWorkPackage(team: string, input: WorkPackageInput): Promise<string>;
  DeleteWorkPackage(team: string, key: string): Promise<void>;
}
