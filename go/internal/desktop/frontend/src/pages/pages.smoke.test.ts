// First UI test approach: every page of the route table is rendered once against the browser
// mock (the same answers the window gets in development) and must show content without
// throwing. This catches pages that crash on data shapes (e.g. a null list) before the window does.
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { selectTeam, start } from '../lib/app.svelte';
import { pages } from '../lib/routes';

let host: HTMLElement | undefined;
let cmp: ReturnType<typeof mount> | undefined;

beforeAll(async () => {
  await start();
  await selectTeam('atlas');
});

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  vi.restoreAllMocks();
});

// Parameters for routes with an address part.
const params: Record<string, string> = { id: 'p1' };

describe('pages', () => {
  for (const def of pages) {
    it(`renders ${def.path}`, async () => {
      const errors: unknown[] = [];
      vi.spyOn(console, 'error').mockImplementation((...a) => void errors.push(a));
      const unhandled = (e: PromiseRejectionEvent) => errors.push(e.reason);
      const thrown = (e: ErrorEvent) => errors.push(e.error ?? e.message);
      window.addEventListener('unhandledrejection', unhandled);
      window.addEventListener('error', thrown);

      const mod = await def.load();
      const p: Record<string, string> = {};
      for (const name of def.path.matchAll(/:(\w+)/g)) p[name[1]!] = params[name[1]!] ?? '1';
      host = document.createElement('div');
      document.body.append(host);
      cmp = mount(mod.default, { target: host, props: { params: p } });
      // The mock answers after a dynamic import: give the page time to load its data.
      await vi.waitFor(() => expect((host!.textContent ?? '').trim().length).toBeGreaterThan(0), { timeout: 4000 });
      await new Promise((r) => setTimeout(r, 100));
      await tick();

      window.removeEventListener('unhandledrejection', unhandled);
      window.removeEventListener('error', thrown);
      expect(errors).toEqual([]);
      expect((host.textContent ?? '').trim().length).toBeGreaterThan(0);
    });
  }
});
