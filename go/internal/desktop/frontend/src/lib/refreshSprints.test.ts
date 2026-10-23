import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { app, refreshSprints } from './app.svelte';
import type { SprintInfo } from './types';

vi.mock('./api', () => ({ api: { Sprints: vi.fn() } }));

const info = (id: string, start: string, state: string): SprintInfo => ({ id, start, end: start, state }) as SprintInfo;

describe('refreshSprints', () => {
  beforeEach(() => {
    app.team = 'demo';
    app.sprints = [];
    app.sprint = '';
  });

  it('follows a renamed sprint by its start date', async () => {
    app.team = 'demo';
    app.sprints = [info('2026.21', '2026-10-19', 'current'), info('2026.22', '2026-11-02', 'future')];
    app.sprint = '2026.22';
    vi.mocked(api.Sprints).mockResolvedValue([info('2026.21', '2026-10-19', 'current'), info('ACCSEC - 2026.22', '2026-11-02', 'future')]);
    await refreshSprints();
    expect(app.sprints.map((s) => s.id)).toContain('ACCSEC - 2026.22');
    expect(app.sprint).toBe('ACCSEC - 2026.22');
  });

  it('keeps the selection when the sprint is still there', async () => {
    app.sprints = [info('2026.21', '2026-10-19', 'current')];
    app.sprint = '2026.21';
    vi.mocked(api.Sprints).mockResolvedValue([info('2026.21', '2026-10-19', 'current')]);
    await refreshSprints();
    expect(app.sprint).toBe('2026.21');
  });

  it('ignores a list that arrives after the team was switched', async () => {
    app.sprints = [info('2026.21', '2026-10-19', 'current')];
    app.sprint = '2026.21';
    vi.mocked(api.Sprints).mockImplementationOnce(async () => {
      app.team = 'other';
      return [info('X', '2026-10-19', 'current')];
    });
    await refreshSprints();
    expect(app.sprints.map((s) => s.id)).toEqual(['2026.21']);
  });
});
