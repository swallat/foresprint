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
  earmarkNote?: string;
  fixed?: boolean;
  trackerSprint: string;
  production: number | null;
  epic: string;
  subtaskCount?: number;
  labels: string[];
  dependsOn: string[];
  blocked: boolean;
  /** Place in the order of the tracker's rank, from 1. */
  rankPos: number;
}

export interface BacklogLane {
  sprint: string;
  start: string;
  end: string;
  plan: number | null;
  absences: 'confirmed' | 'announced' | 'unknown';
  tickets: BacklogTicket[];
}

export interface BacklogAdjust {
  key: string;
  title: string;
  url: string;
  /** Pro-forma sprint in the tracker / the one chosen here; "" = none (backlog). */
  from: string;
  to: string;
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
  /** Tickets that came into or left the tracker's sprint after the freeze (running sprint). */
  drift?: BacklogDrift;
  /** Tickets placed in or out of a pro-forma sprint here that the tracker still has differently. */
  adjust: BacklogAdjust[];
  /** The own order among tracker tickets is in use. */
  ownOrder: boolean;
}

export interface BacklogDrift {
  sprint: string;
  pulledIn: string[];
  dropped: string[];
  unknown: string[];
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

export interface TrackerSubtask {
  key: string;
  title: string;
  status: string;
  done: boolean;
}

export interface TrackerLink {
  type: string;
  /** How the tracker words the link from this ticket's side, e.g. "is blocked by". */
  text: string;
  key: string;
  title: string;
  status: string;
  url: string;
}

export interface TrackerAttachment {
  name: string;
  mime: string;
  size: number;
  url: string;
}

/** Read on demand from the tracker when the panel opens; available is false without Jira. */
export interface TrackerDetails {
  available: boolean;
  description: string;
  subtasks: TrackerSubtask[];
  links: TrackerLink[];
  comments: Comment[];
  attachments: TrackerAttachment[];
}

export interface BacklogApi {
  Backlog(team: string): Promise<BacklogView>;
  Ticket(team: string, key: string): Promise<TicketDetail>;
  /** Description, sub-tasks, links, comments and attachments of a tracker ticket (read only). */
  TicketTracker(team: string, key: string): Promise<TrackerDetails>;
  EarmarkTicket(team: string, key: string, sprint: string, note: string): Promise<void>;
  MoveToProForma(team: string, key: string, name: string): Promise<void>;
  ResetOrder(team: string): Promise<void>;
  MoveTicketByRank(team: string, key: string, anchor: string, after: boolean): Promise<void>;
  SetEarmarkNote(team: string, key: string, note: string): Promise<void>;
  SetEstimate(team: string, key: string, value: number | null): Promise<void>;
  SetRefined(team: string, key: string, refined: boolean): Promise<void>;
  SetAssignment(team: string, key: string, product: string, project: string, daily: boolean): Promise<void>;
  SetProduction(team: string, key: string, percent: number | null): Promise<void>;
  SaveWorkPackage(team: string, input: WorkPackageInput): Promise<string>;
  DeleteWorkPackage(team: string, key: string): Promise<void>;
  /** Puts a work package before (or after) another one; anchor "" = to the end. */
  MoveWorkPackage(team: string, key: string, anchor: string, after: boolean): Promise<void>;
}
