import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import People from './People.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
});

async function settle() {
  await new Promise((r) => setTimeout(r, 30));
  await tick();
}

describe('People times panel', () => {
  it('closes the panel after saving the times without failing', async () => {
    const errors: unknown[] = [];
    const onerror = (e: ErrorEvent) => errors.push(e.error ?? e.message);
    window.addEventListener('error', onerror);
    const unhandled = (e: PromiseRejectionEvent) => errors.push(e.reason);
    window.addEventListener('unhandledrejection', unhandled);
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(People, { target: host, props: { params: {} } });
    await vi.waitFor(() => expect(host.querySelectorAll('button[aria-label^="Times and leaving"]').length).toBeGreaterThan(0), { timeout: 3000 });
    const open = host.querySelector<HTMLButtonElement>('button[aria-label^="Times and leaving"]')!;
    open.click();
    await settle();
    const date = host.querySelector<HTMLInputElement>('input[aria-label="Entry"]')!;
    expect(date).toBeTruthy();
    date.value = '2020-01-01';
    date.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    const save = [...host.querySelectorAll<HTMLButtonElement>('button.primary')].find((b) => /Apply|Save/.test(b.textContent ?? ''))!;
    save.click();
    await settle();
    window.removeEventListener('error', onerror);
    window.removeEventListener('unhandledrejection', unhandled);
    expect(errors).toEqual([]);
    expect(host.querySelector('input[aria-label="Entry"]')).toBeNull();
  });
});
