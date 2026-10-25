import { describe, expect, it } from 'vitest';
import { link, match, parseHash } from './router.svelte';

describe('router', () => {
  it('parses path and query', () => {
    expect(parseHash('#/projects/atlas?tab=milestones')).toEqual({
      path: '/projects/atlas',
      query: { tab: 'milestones' },
    });
    expect(parseHash('')).toEqual({ path: '/', query: {} });
  });
  it('matches parameters', () => {
    expect(match('/projects/:id', '/projects/a%20b')).toEqual({ id: 'a b' });
    expect(match('/projects/:id', '/projects')).toBeUndefined();
    expect(match('/data', '/data')).toEqual({});
  });
  it('builds links', () => {
    expect(link('/projects/:id', { id: 'a b' }, { tab: 'x' })).toBe('#/projects/a%20b?tab=x');
  });
});
