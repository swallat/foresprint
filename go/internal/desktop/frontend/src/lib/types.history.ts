// Types of the undo and redo of the window (go/internal/app/api_history.go).

export interface HistoryState {
  canUndo: boolean;
  canRedo: boolean;
}

export interface HistoryResult {
  ok: boolean;
  message: string;
  files: number;
  state: HistoryState;
}

export interface HistoryApi {
  HistoryBegin(): Promise<void>;
  HistoryEnd(): Promise<HistoryState>;
  HistoryClear(): Promise<HistoryState>;
  HistoryInfo(): Promise<HistoryState>;
  HistoryUndo(): Promise<HistoryResult>;
  HistoryRedo(): Promise<HistoryResult>;
}
