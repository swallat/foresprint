// Types of the sprint workspace (go/internal/app/types_sprints.go).

export type AbsenceState = 'unknown' | 'announced' | 'confirmed';

export interface AbsenceColumn {
  id: string;
  name: string;
  start: string; // YYYY-MM-DD
  end: string; // last day, YYYY-MM-DD
  state: AbsenceState;
  workdays: number;
  entries: number;
  absent: number;
  capacity: number;
  plan: number | null;
  past: boolean;
}

export type CellState = 'confirmed' | 'announced' | 'empty';

export interface AbsenceCell {
  days: number;
  /** Closed lock (confirmed), open lock (announced) or nothing entered. */
  state: CellState;
  max: number;
  active: boolean;
}

export interface AbsenceRow {
  person: string;
  name: string;
  fte: number;
  cells: AbsenceCell[];
}

export interface AbsenceGrid {
  columns: AbsenceColumn[];
  rows: AbsenceRow[];
}

export type ReadyKind = 'absences' | 'refinement' | 'preplan';

export interface ReadyItem {
  kind: ReadyKind;
  state: 'done' | 'open' | 'na';
  count: number;
  names: string[];
}

export interface SprintPrepare {
  sprint: AbsenceColumn;
  capacityBase: number;
  planBase: number | null;
  preplanned: number;
  unit: 'SP' | 'PT';
  ready: ReadyItem[];
}

export interface SprintsApi {
  /** Absences of `count` consecutive sprints from sprint `from` ("" = running or next). */
  AbsenceGrid(team: string, from: string, count: number): Promise<AbsenceGrid>;
  /** Sets the days of one person (half days; 0 removes); typing keeps a confirmed cell confirmed. */
  SetAbsence(team: string, sprint: string, person: string, days: number): Promise<AbsenceColumn>;
  /** Locks (confirmed) or unlocks (announced) one cell; a frozen sprint keeps all cells confirmed. */
  SetAbsenceConfirmed(team: string, sprint: string, person: string, confirmed: boolean): Promise<AbsenceColumn>;
  FreezeAbsences(team: string, sprint: string): Promise<AbsenceColumn>;
  UnfreezeAbsences(team: string, sprint: string): Promise<AbsenceColumn>;
  SprintPrepare(team: string, sprint: string): Promise<SprintPrepare>;
}
