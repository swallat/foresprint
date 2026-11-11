// Browser answers for undo and redo (npm run dev, tests): the mock keeps no steps.

import type { Api } from '../api';

const none = { canUndo: false, canRedo: false };

const historyMock: Partial<Api> = {
  async HistoryBegin() {
    return 0;
  },
  async HistoryEnd() {
    return none;
  },
  async HistoryClear() {
    return none;
  },
  async HistoryInfo() {
    return none;
  },
  async HistoryUndo() {
    return { ok: false, message: '', files: 0, state: none };
  },
  async HistoryRedo() {
    return { ok: false, message: '', files: 0, state: none };
  },
};

export default historyMock;
