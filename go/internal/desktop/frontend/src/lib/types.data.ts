// Types of the area Data (go/internal/datasvc, bound by internal/app/api_data.go). The JSON names
// are the `json:"..."` tags of the Go structs.

export interface Problem {
  kind: string;
  title: string;
  message: string;
  hint?: string;
}

export type ChipState =
  | 'decided'
  | 'conflict'
  | 'problem'
  | 'offline'
  | 'incoming'
  | 'waiting_for_review'
  | 'unsaved'
  | 'pending'
  | 'local'
  | 'ok';

export interface DataStatus {
  kind: string;
  /** Address of the server without credentials, "" = none set up. */
  location: string;
  configured: boolean;
  writable: boolean;
  connected: boolean;
  unsaved: number;
  pending: number;
  incoming: number;
  incomingFrom: string[];
  conflicts: number;
  link?: string;
  chip: { state: ChipState; text: string; link?: string };
  capabilities: { offlineWrite: boolean; tags: boolean; branches: boolean; snapshots: boolean };
  problem?: Problem;
}

export interface Change {
  who: string;
  day: string;
  summary: string;
}

export interface ConflictEntry {
  path: string[];
  label: string;
  mine: string;
  theirs: string;
  mineMissing: boolean;
  theirsMissing: boolean;
  before: string;
  hasBefore: boolean;
}

export interface Conflict {
  file: string;
  entries: ConflictEntry[];
  whole: boolean;
  mineDeleted: boolean;
  theirsDeleted: boolean;
}

export interface Decision {
  file: string;
  path: string[];
  choice: 'ours' | 'theirs';
}

export interface Version {
  id: string;
  short: string;
  who: string;
  day: string;
  summary: string;
  files: string[];
  merge: boolean;
  tags: string[];
}

export interface Label {
  name: string;
  target: string;
  day: string;
  summary: string;
  onServer?: boolean;
  differs: boolean;
}

export interface LostFile {
  status: string;
  file: string;
  added: number;
  removed: number;
  orig?: string;
}

export interface Done {
  version: string;
  warning?: string;
  problem?: Problem;
  status: DataStatus;
}

export interface SetupItem {
  key: string;
  ok: boolean;
  detail: string;
  page?: string;
}

export interface SignInGuide {
  kind: string;
  username: string;
  steps: string;
}

export interface StorageSettings {
  kind: string;
  folder: string;
  ready: boolean;
  server: string;
  special?: string;
  hasSecret: boolean;
  branch: string;
  share: 'direct' | 'merge_request' | '';
  autoMerge: boolean;
  host: string;
  detectedHost: string;
  hosts: string[];
  name: string;
  email: string;
  helper: string;
  suggestedHelper: string;
  setup: SetupItem[];
  guide: SignInGuide;
  problem?: Problem;
}

export interface ServerCheck {
  ok: boolean;
  address: string;
  empty: boolean;
  branchMissing: boolean;
  heads: string[];
  problem?: Problem;
}

export interface ServerOptions {
  allowInsecure: boolean;
  acceptNewBranch: boolean;
  allowOffline: boolean;
}

export interface ServerSaved {
  address: string;
  verified: boolean;
  problem?: Problem;
}

export interface Branch {
  name: string;
  local: boolean;
  remote: boolean;
  current: boolean;
}

export interface Reattached {
  branch: string;
  rescue: string;
  commits: boolean;
  changes: boolean;
  problem?: Problem;
}

export interface Opened {
  folder: string;
  problem?: Problem;
}

/** The methods of the area Data (internal/app/api_data.go). */
export interface DataApi {
  SaveAnyway(): Promise<import('./types').Result>;
  DataIncoming(): Promise<Change[]>;
  CheckForChanges(): Promise<import('./types').Status>;
  AbortSync(): Promise<boolean>;
  Conflicts(): Promise<Conflict[]>;
  ResolveConflicts(decisions: Decision[]): Promise<import('./types').Result>;
  TakeTheirs(): Promise<import('./types').Result>;
  AbortMerge(): Promise<import('./types').Status>;
  History(scope: string, limit: number): Promise<Version[]>;
  Restore(scope: string, version: string, message: string): Promise<Done>;
  Revert(version: string): Promise<Done>;
  Discard(files: string[]): Promise<Done>;
  Lost(files: string[]): Promise<LostFile[]>;
  Labels(checkServer: boolean): Promise<Label[]>;
  SetLabel(name: string, version: string, message: string): Promise<Done>;
  ShareLabel(name: string): Promise<Done>;
  DeleteLabel(name: string): Promise<Done>;
  Storage(): Promise<StorageSettings>;
  CheckServer(address: string, allowInsecure: boolean): Promise<ServerCheck>;
  SaveServer(address: string, opts: ServerOptions): Promise<ServerSaved>;
  SetShare(mode: string): Promise<Problem | null>;
  SetHost(kind: string): Promise<Problem | null>;
  SetAutoMerge(enabled: boolean): Promise<Problem | null>;
  SetIdentity(name: string, email: string): Promise<Problem | null>;
  EnableHelper(name: string): Promise<Problem | null>;
  SignInGuide(kind: string): Promise<SignInGuide>;
  SignIn(address: string, username: string, token: string): Promise<Problem | null>;
  ForgetSignIn(address: string, username: string): Promise<Problem | null>;
  Branches(): Promise<Branch[]>;
  SwitchBranch(name: string): Promise<Done>;
  Reattach(): Promise<Reattached>;
  CloneFrom(address: string, folder: string): Promise<Opened>;
  CreateFolder(folder: string): Promise<Opened>;
  OpenFolder(folder: string): Promise<Opened>;
  PickFolder(title: string): Promise<string>;
}
