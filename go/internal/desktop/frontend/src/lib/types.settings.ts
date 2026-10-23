// Types of the settings area (go/internal/app/types_settings.go).

import type { Result } from './types';

export interface ForecastSettings {
  window: number;
  trend: 'flat' | 'linear' | 'classic';
  referenceCapacity: number;
  /** Percent, 0 to 100. */
  plannableShare: number;
  rounding: number;
  horizon: number;
  basis: 'plan' | 'share';
}

export interface UnitChangeInfo {
  from: string;
  unit: string;
}

export interface TeamSettings {
  name: string;
  unit: 'SP' | 'PT';
  unitFrom: string;
  unitChanges: UnitChangeInfo[];
  /** Points per person day, null = the measured team rate. */
  factor: number | null;
  forecast: ForecastSettings;
  lengthDays: number;
  products: boolean;
  po: boolean;
  production: boolean;
  /** Percent of the production time that counts, 100 = no cap. */
  productionCap: number;
  projects: boolean;
  proForma: string[];
}

export interface TrackerFields {
  estimate: string;
  remaining: string;
  epic: string;
  status: string;
  acceptance: string;
  product: string;
  project: string;
  refined: string;
  production: string;
}

export interface ProdRule {
  rule: string;
  percent: number;
}

export interface RuleField {
  name: string;
  display: string;
}

export interface TokenState {
  host: string;
  stored: boolean;
  fromEnv: boolean;
  keychainUsable: boolean;
  variable: string;
}

export type TicketSource = 'tracker' | 'packages' | 'none';
export type By = 'rule' | 'field';

export interface TrackerSettings {
  source: TicketSource;
  kind: 'jira' | 'csv';
  baseUrl: string;
  query: string;
  fields: TrackerFields;
  productBy: By;
  projectBy: By;
  refinedBy: By;
  refinedLabel: string;
  refinedRule: string;
  productionBy: 'manual' | 'rule' | 'field+rule';
  productionLabel: string;
  prodRules: ProdRule[];
  ruleFields: RuleField[];
  fixedSources: string[];
  writeSprint: boolean;
  /** Jira board of the write-back; 0 or empty = none. */
  boardId: number | null;
  /** Minutes between two automatic fetches; 0 = only on the button. */
  fetchInterval: number;
  proForma: string[];
  /** Sprint names met in the tracker, for the table. */
  sprints: TrackerSprint[];
  sprintIds: string[];
  /** Tickets of the last import that have a value, per mapped value. */
  fieldHits: Record<string, number>;
  /** The mapping the last fetch used; the hits belong to it. */
  hitsFields: TrackerFields;
  removedTarget: '' | 'backlog' | 'pro_forma' | 'next';
  writeLabels: boolean;
  includeSubtasks: boolean;
  packagePrefix: string;
  token: TokenState;
  tickets: number;
  imported: string;
}

export interface TrackerSprint {
  name: string;
  tickets: number;
  mapsTo: string;
}

export interface Connection {
  ok: boolean;
  message: string;
  user?: string;
}

export interface QueryCheck {
  ok: boolean;
  message: string;
  count: number;
}

export interface TrackerInfo {
  enabled: boolean;
  name: string;
  last: string;
  syncing: boolean;
  failed: string;
  interval: number;
}

export interface Features {
  source: TicketSource;
  products: boolean;
  po: boolean;
  production: boolean;
  projects: boolean;
}

export interface PackageImportChange {
  key: string;
  title: string;
  update: boolean;
}

export interface PackageImportPreview {
  path: string;
  hash: string;
  changes: PackageImportChange[];
  more: number;
  new: number;
  updated: number;
  problems: { row: number; msg: string }[];
  unmapped: string[];
  cancelled: boolean;
}

export interface UpdateInfo {
  version: string;
  latest: string;
  available: boolean;
  url: string;
  mode: 'on' | 'notice' | 'off';
  modeEnv: boolean;
  lastCheck: string;
  dev: boolean;
  restart: boolean;
}

export interface SettingsApi {
  UpdateStatus(): Promise<UpdateInfo>;
  /** auto: only when the daily check is due (start of the window); false = asked for by a click. */
  CheckUpdate(auto: boolean): Promise<UpdateInfo>;
  InstallUpdate(): Promise<UpdateInfo>;
  SetUpdateMode(mode: string): Promise<void>;
  TeamFeatures(team: string): Promise<Features>;
  TeamSettings(team: string): Promise<TeamSettings>;
  SaveTeamSettings(team: string, settings: TeamSettings): Promise<void>;
  TrackerSettings(team: string): Promise<TrackerSettings>;
  SaveTrackerSettings(team: string, settings: TrackerSettings): Promise<void>;
  SetTrackerToken(team: string, baseUrl: string, token: string): Promise<void>;
  RemoveTrackerToken(team: string, baseUrl: string): Promise<void>;
  TestTrackerConnection(team: string, baseUrl: string): Promise<Connection>;
  TestTrackerQuery(team: string, baseUrl: string, query: string): Promise<QueryCheck>;
  TrackerFieldNames(team: string, baseUrl: string): Promise<string[]>;
  TrackerInfo(team: string): Promise<TrackerInfo>;
  TokenInfo(team: string, baseUrl: string): Promise<TokenState>;
  SetDensity(code: string): Promise<void>;
  SyncTracker(team: string): Promise<Result>;
  SyncTrackerAuto(team: string): Promise<Result>;
  PackageImportPreview(team: string): Promise<PackageImportPreview>;
  PackageImportApply(team: string, path: string, hash: string): Promise<Result>;
}
