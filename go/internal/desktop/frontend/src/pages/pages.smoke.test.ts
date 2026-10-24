// First UI test approach: every page of the route table is rendered once against the browser
// mock (the same answers the window gets in development) and must finish loading without a
// crash and without an error banner. This catches pages that break on a data shape (for example
// a null list) before the window does.
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { selectTeam, start } from '../lib/app.svelte';
import { pages } from '../lib/routes';

let host: HTMLElement | undefined;
let cmp: ReturnType<typeof mount> | undefined;
let crashes: unknown[] = [];

// An error thrown after the mount (in an effect or a timer) is not a rejected promise: it ends up
// as an uncaught exception, which vitest would only report for the whole run.
const onCrash = (e: unknown) => void crashes.push(e);

// Route parameters that exist in the mock.
const params: Record<string, string> = { id: 'self-service' };

beforeAll(async () => {
  await start();
  await selectTeam('atlas');
});

beforeEach(() => {
  crashes = [];
  process.on('uncaughtException', onCrash);
  process.on('unhandledRejection', onCrash);
  vi.spyOn(console, 'error').mockImplementation((...a) => void crashes.push(a));
});

afterEach(() => {
  process.off('uncaughtException', onCrash);
  process.off('unhandledRejection', onCrash);
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  vi.restoreAllMocks();
});

const loading = (el: HTMLElement) => [...el.querySelectorAll('.muted')].some((n) => /^Loading/.test(n.textContent?.trim() ?? ''));

describe('pages', () => {
  for (const def of pages) {
    it(`renders ${def.path}`, { timeout: 10000 }, async () => {
      const mod = await def.load();
      const p: Record<string, string> = {};
      for (const name of def.path.matchAll(/:(\w+)/g)) p[name[1]!] = params[name[1]!] ?? '1';
      host = document.createElement('div');
      document.body.append(host);
      cmp = mount(mod.default, { target: host, props: { params: p } });
      // The heading is there at once; wait until the data has arrived (no "Loading" left).
      await vi.waitFor(() => expect(loading(host!)).toBe(false), { timeout: 6000 });
      await new Promise((r) => setTimeout(r, 50));
      await tick();

      expect(crashes).toEqual([]);
      expect(host.querySelector('[role="alert"]')?.textContent ?? null).toBeNull();
      expect((host.textContent ?? '').trim().length).toBeGreaterThan(0);
    });
  }
});
