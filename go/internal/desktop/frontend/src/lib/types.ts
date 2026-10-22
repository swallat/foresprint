// Types of the Go bindings (go/internal/app). Keep them in step with the Go structs: the JSON
// names are the `json:"..."` tags. A new area adds its types in types.<area>.ts and re-exports
// nothing from here, so that areas do not collide.

export interface Info {
  version: string;
  os: string;
  arch: string;
  dataDir: string;
  holidaysVersion: string;
}

export interface Choice {
  code: string;
  label: string;
}

export interface Prefs {
  language: string;
  languages: Choice[];
  theme: string;
  themes: Choice[];
  dataDir: string;
  recentDataDirs: string[];
}

export interface TeamSummary {
  key: string;
  name: string;
  people: number;
  sprints: number;
  problem?: string;
  tickets: boolean;
  products: number;
}

export interface SprintInfo {
  id: string;
  start: string;
  end: string;
  state: 'past' | 'current' | 'future';
}

export type StorageState =
  | 'saved'
  | 'dirty'
  | 'incoming'
  | 'conflict'
  | 'offline'
  | 'mr'
  | 'readonly'
  | 'locked';

export interface TrackerStatus {
  enabled: boolean;
  name: string;
  last: string;
  syncing: boolean;
  failed: string;
}

export interface Status {
  storage: StorageState;
  detail: string;
  incoming: number;
  findings: number;
  tracker: TrackerStatus;
}

export interface Result {
  ok: boolean;
  message: string;
}
