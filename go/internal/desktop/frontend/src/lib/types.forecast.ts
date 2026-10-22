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
  samples: number;
  fewSamples: boolean;
  rate: number | null;
  past: ForecastRow[];
  upcoming: ForecastRow[];
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
}

export interface ForecastApi {
  Forecast(team: string): Promise<ForecastView>;
  ForecastWhatIf(team: string, extraAbsenceDays: number, focusPercent: number): Promise<WhatIfRow[]>;
  ForecastWhenDone(team: string, remaining: number, sharePercent: number): Promise<WhenDoneView>;
}
