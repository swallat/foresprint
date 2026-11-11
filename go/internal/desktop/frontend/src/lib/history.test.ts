import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { mockApi } from './mock';

describe('undo list around writes', () => {
  afterEach(() => vi.restoreAllMocks());

  it('brackets a write with HistoryBegin and HistoryEnd', async () => {
    const order: string[] = [];
    vi.spyOn(mockApi, 'HistoryBegin').mockImplementation(async () => (order.push('begin'), 1));
    vi.spyOn(mockApi, 'HistoryEnd').mockImplementation(async () => (order.push('end'), { canUndo: true, canRedo: false }));
    vi.spyOn(mockApi, 'SetLanguage').mockImplementation(async () => void order.push('write'));
    await api.SetLanguage('de');
    expect(order).toEqual(['begin', 'write', 'end']);
  });

  it('does not bracket reads', async () => {
    const begin = vi.spyOn(mockApi, 'HistoryBegin');
    await api.Teams();
    expect(begin).not.toHaveBeenCalled();
  });

  it('clears the list after a save instead of recording a step', async () => {
    const begin = vi.spyOn(mockApi, 'HistoryBegin');
    const clear = vi.spyOn(mockApi, 'HistoryClear');
    await api.Save();
    expect(begin).not.toHaveBeenCalled();
    expect(clear).toHaveBeenCalledOnce();
  });

  it('records an edit whose name only starts like a save', async () => {
    const clear = vi.spyOn(mockApi, 'HistoryClear');
    const end = vi.spyOn(mockApi, 'HistoryEnd');
    await api.SavePeople('atlas', []).catch(() => undefined);
    expect(clear).not.toHaveBeenCalled();
    expect(end).toHaveBeenCalled();
  });
});
