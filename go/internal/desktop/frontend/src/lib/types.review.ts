// Types of the Review and the minutes, as go/internal/app/types_review.go sends them.

import type { AbsenceColumn } from './types.sprints';

export interface ReviewTicket {
  key: string;
  title: string;
  estimate: number;
  done: boolean;
  /** What is left of a ticket that is not done. */
  rest: number;
  /** Where the rest continues: "" = next sprint, a sprint id, "backlog". */
  target: string;
}

export interface ReviewProduct {
  id: string;
  name: string;
  planned: number;
  done: number;
  prodDone: number;
}

export interface ReviewTarget {
  id: string;
  name: string;
}

export interface SprintReview {
  sprint: AbsenceColumn;
  unit: string;
  started: boolean;
  reviewed: boolean;
  reopenable: boolean;
  /** The team commits to tickets: the list below replaces the typed numbers. */
  tickets: boolean;
  commitment: number;
  /** False for a sprint without a recorded commitment: the page asks for it. */
  commitmentSet: boolean;
  notDone: number;
  additionalDone: number;
  /** Done tickets pulled in after the freeze; their estimates prefill additionalDone. */
  pulled: string[];
  /** Among them those without an estimate. */
  noEstimate: string[];
  /** Without tickets: the part of "not done" that continues in the next sprint. */
  restNext: number;
  velocity: number;
  list: ReviewTicket[];
  targets: ReviewTarget[];
  plannedDays: number;
  frozenDays: number;
  rate: number | null;
  /** The fixed factor valid for the sprint; null = the measured rate is used. */
  factor?: number | null;
  products: ReviewProduct[];
  productsOn: boolean;
  productionOn: boolean;
  production: number;
  tag: string;
}

export interface ReviewInput {
  notDone: number;
  additionalDone: number;
  restNext: number;
  /** Taken only where the sprint has no commitment recorded. */
  commitment: number | null;
  list: ReviewTicket[];
  frozenDays: number;
  products: ReviewProduct[];
  production: number;
  /** Names the state with the Review at the next Save; "" = no tag. */
  tag: string;
}

export interface ReviewClosed {
  review: SprintReview;
  minutes: string;
  tag: string;
}

export interface MinutesRow {
  sprint: string;
  kind: 'vorplanung' | 'planning' | 'review';
  at: string;
  file: string;
  obsolete: boolean;
}

export interface MinutesText {
  text: string;
  path: string;
}

export interface ReviewApi {
  SprintReview(team: string, sprint: string): Promise<SprintReview>;
  CloseReview(team: string, sprint: string, input: ReviewInput): Promise<ReviewClosed>;
  ReopenReview(team: string, sprint: string): Promise<ReviewClosed>;
  /** The minutes of a sprint, newest first; "" = of all sprints. */
  SprintMinutes(team: string, sprint: string): Promise<MinutesRow[]>;
  MinutesText(team: string, file: string): Promise<MinutesText>;
}
