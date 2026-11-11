// Undo and redo of the changes the window made to the data (Ctrl+Z, Ctrl+Y). The Go core keeps
// the steps (internal/app/api_history.go); api.ts reports every change of the list here.

import { api, setHistoryListener } from './api';
import { app, refreshSprints, refreshStatus, toast } from './app.svelte';
import { t } from './i18n.svelte';
import type { HistoryState } from './types.history';

export const history = $state({ canUndo: false, canRedo: false });

function take(s: HistoryState): void {
  history.canUndo = s.canUndo;
  history.canRedo = s.canRedo;
}

setHistoryListener(take);

let running = false;

async function move(undo: boolean): Promise<void> {
  if (running || app.busy) return;
  if (undo ? !history.canUndo : !history.canRedo) return;
  running = true;
  try {
    const r = await (undo ? api.HistoryUndo() : api.HistoryRedo());
    take(r.state);
    if (!r.ok) {
      if (r.message) toast(r.message, 'bad');
      return;
    }
    // Every page reads its data anew, as after a change of the other view.
    app.changed++;
    void refreshStatus();
    try {
      app.teams = await api.Teams();
      await refreshSprints();
    } catch {
      /* the page shows its own error */
    }
    toast(undo ? t('Undone.') : t('Redone.'), 'ok', {
      label: undo ? t('Redo') : t('Undo'),
      run: () => void move(!undo),
    });
  } catch (e) {
    toast(String(e), 'bad');
  } finally {
    running = false;
  }
}

export const undo = (): Promise<void> => move(true);
export const redo = (): Promise<void> => move(false);

/** True for a field where the keys belong to the field's own undo. */
export function isEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
}
