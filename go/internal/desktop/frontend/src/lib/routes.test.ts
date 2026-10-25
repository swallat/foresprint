import { describe, expect, it } from 'vitest';
import { match } from './router.svelte';
import { nav, pages } from './routes';

describe('route table', () => {
  it('has unique paths', () => {
    const paths = pages.map((p) => p.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
  it('has a page for every navigation entry', () => {
    for (const group of nav) {
      for (const item of group.items) {
        expect(pages.some((p) => match(p.path, item.path) !== undefined), item.path).toBe(true);
      }
    }
  });
  it('points nav to existing entries', () => {
    const navPaths = new Set(nav.flatMap((g) => g.items.map((i) => i.path)));
    for (const p of pages) if (p.nav) expect(navPaths.has(p.nav), p.path).toBe(true);
  });
});
