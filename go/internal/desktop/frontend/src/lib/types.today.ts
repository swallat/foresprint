// Types of the start page (go/internal/app/api_today.go).

export type StepKey = 'absences' | 'preplan' | 'plan' | 'review';
export type StepState = 'done' | 'open' | 'none';
export type SprintPhase = 'running' | 'next' | 'later' | 'past';
export type TicketSource = 'tracker' | 'packages' | 'none';

export interface TodayStep {
  key: StepKey;
  state: StepState;
  detail: string;
}

export interface TodaySprint {
  id: string;
  start: string;
  end: string;
  state: SprintPhase;
  daysLeft: number;
  daysToStart: number;
  /** The first day has come, but the sprint is not started yet. */
  startDue: boolean;
  steps: TodayStep[];
}

export interface TodayFinding {
  level: 'error' | 'notice';
  where: string;
  message: string;
  route: string;
}

export interface TodayData {
  date: string;
  team: string;
  name: string;
  source: TicketSource;
  sprints: TodaySprint[];
  findings: TodayFinding[];
  errors: number;
  notices: number;
}

export interface TodayApi {
  Today(team: string): Promise<TodayData>;
}
