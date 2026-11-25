import { afterEach, describe, expect, it } from 'vitest';
import { api, coreError, isDemo, setDemo } from './api';

afterEach(() => setDemo(false));

describe('demo mode', () => {
  it('answers team data from the invented demo team', async () => {
    setDemo(true);
    expect(isDemo()).toBe(true);
    const teams = await api.Teams();
    expect(teams.map((t) => t.name)).toEqual(['Team Atlas']);
    expect((await api.Today('atlas')).name).toBe('Team Atlas');
  });
  it('is off by default', () => {
    expect(isDemo()).toBe(false);
  });
});

describe('errors of the core', () => {
  it('arrive as plain text, so that String(e) shows no "Error: " prefix', () => {
    // Wails 2.13 rejects a failed call with an Error object.
    const e = coreError(new Error('the folder is locked'), true);
    expect(e).toBe('the folder is locked');
    expect(String(e)).toBe('the folder is locked');
  });
  it('stay as they are for plain text, for the mock and for errors of the shell', () => {
    expect(coreError('already text', true)).toBe('already text');
    const own = new Error('api: unknown method X');
    expect(coreError(own, false)).toBe(own);
  });
});
