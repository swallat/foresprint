import { beforeEach, describe, expect, it, vi } from 'vitest';
import { app, refresh, save, syncTracker } from './app.svelte';

vi.mock('./api', () => ({
  inProgram: false,
  setDemo: vi.fn(),
  ownCallRecent: vi.fn(() => false),
  api: {
    SyncTracker: vi.fn(async () => ({ ok: true, outcome: 'ok', message: 'ok' })),
    Refresh: vi.fn(async () => ({ ok: true, outcome: 'ok', message: 'ok' })),
    Save: vi.fn(async () => ({ ok: true, outcome: 'ok', message: 'ok' })),
    Status: vi.fn(async () => ({ storage: 'saved', tracker: { syncing: false } })),
    TrackerInfo: vi.fn(async () => ({ syncing: false })),
    PendingTags: vi.fn(async () => []),
    Sprints: vi.fn(async () => []),
  },
}));

describe('new data from the tracker or from others', () => {
  beforeEach(() => {
    app.team = 'demo';
    app.busy = '';
  });

  it('shows the open page anew after a sync and after a fetch, but not after a save', async () => {
    const before = app.changed;
    await syncTracker();
    expect(app.changed).toBe(before + 1);
    await refresh();
    expect(app.changed).toBe(before + 2);
    await save();
    expect(app.changed).toBe(before + 2);
  });
});
