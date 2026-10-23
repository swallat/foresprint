// Types of the forecast bindings (go/internal/app/types_forecast.go).

export interface ForecastRow {
  id: string;
  start: string;
  end: string;
  state: 'past' | 'current' | 'future';
  recorded: boolean;
  capacity: number | null;
  capacitySource: string;
  unsure: boolean;
  commitment: number | null;
  velocity: number | null;
  normalizedVelocity: number | null;
  average: number | null;
  trend: number | null;
  fulfillment: number | null;
  plan: number | null;
  planSource: '' | 'actual' | 'projection';
  low: number | null;
  high: number | null;
  plannable: number | null;
  small: number | null;
  carryIn: number;
  carryAssumed: boolean;
  overbooked: boolean;
}

export interface ForecastView {
  team: string;
  today: string;
  referenceCapacity: number;
  window: number;
  roadmapShare: number;
  trendMode: string;
  horizon: number;
  rounding: number;
  products: number;
  samples: number;
  fewSamples: boolean;
  rate: number | null;
  /** The running sprint and the one after it ("" if none); the commitment of the running one. */
  running: string;
  next: string;
  runningCommitment: number | null;
  past: ForecastRow[];
  upcoming: ForecastRow[];
}

/** What the Forecast page tries; sprint "" = all coming ones, expectedVelocity null = leave the running sprint. */
export interface ForecastAssumption {
  sprint: string;
  extraAbsenceDays: number;
  focusPercent: number;
  expectedVelocity: number | null;
  label: string;
}

export interface WhatIfRow {
  id: string;
  capacity: number;
  forecast: number;
  base: number;
  delta: number;
}

export interface WhenDoneView {
  remaining: number;
  share: number;
  runs: number;
  samples: number;
  p50: string;
  p85: string;
  sprints: string[];
  cumulative: number[];
  perSprint: number;
  trendCapacity: string[];
  available: boolean;
  earliest: string;
  starts: string[];
  ends: string[];
  projectName: string;
  projectEnd: string;
  light: 'ok' | 'warn' | 'bad' | 'none';
}

export interface WhenProject {
  id: string;
  name: string;
  end: string;
  openScope: number | null;
  open: number;
}

export interface ProductCell {
  standard: number | null;
  preplanned: number | null;
  planned: number | null;
  done: number | null;
}

export interface ProductLine {
  id: string;
  name: string;
  cells: ProductCell[];
  sprints: number;
  standard: number;
  done: number;
  difference: number;
  missing: number;
}

export interface ProductsOverTime {
  enabled: boolean;
  sprints: string[];
  current: string;
  lines: ProductLine[];
}

export interface ReportFile {
  path: string;
  cancelled: boolean;
}

export interface ImportChange {
  file: string;
  path: string;
  old: string;
  new: string;
}

export interface ImportPreview {
  path: string;
  hash: string;
  changes: ImportChange[];
  more: number;
  untouched: string[];
  noTeam: boolean;
  cancelled: boolean;
  kind: 'workbook' | 'packages';
  problems: string[];
  unmapped: string[];
}

export interface ForecastApi {
  ForecastProducts(team: string): Promise<ProductsOverTime>;
  ForecastReport(team: string): Promise<string>;
  ForecastSave(team: string, kind: 'markdown' | 'excel'): Promise<ReportFile>;
  ExcelImportPreview(team: string): Promise<ImportPreview>;
  ExcelImportApply(team: string, path: string, hash: string): Promise<string[]>;
  Forecast(team: string): Promise<ForecastView>;
  ForecastWhatIf(team: string, as: ForecastAssumption): Promise<WhatIfRow[]>;
  ForecastSaveWhatIf(team: string, as: ForecastAssumption): Promise<void>;
  ForecastWhenProjects(team: string): Promise<WhenProject[]>;
  ForecastWhenDone(team: string, remaining: number, sharePercent: number, project: string): Promise<WhenDoneView>;
}
