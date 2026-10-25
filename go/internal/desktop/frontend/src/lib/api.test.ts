import { afterEach, describe, expect, it } from 'vitest';
import { api, isDemo, setDemo } from './api';

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
