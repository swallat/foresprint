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
    expect(host.querySelector('input[aria-label="Entry"]')).toBeNull();
    await vi.waitFor(() => expect(host.textContent).toMatch(/2020/), { timeout: 3000 });
    window.removeEventListener('error', onerror);
    window.removeEventListener('unhandledrejection', unhandled);
    expect(errors).toEqual([]);
  });
});

describe('All absences', () => {
  it('lists every period of the team and deletes one', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(People, { target: host, props: { params: {} } });
    const rows = () => host.querySelectorAll('section[aria-labelledby="all-h"] tbody tr');
    await vi.waitFor(() => expect(rows().length).toBeGreaterThan(0), { timeout: 3000 });
    const before = rows().length;
    host.querySelector<HTMLButtonElement>('section[aria-labelledby="all-h"] button[aria-label^="Delete absence"]:not([disabled])')!.click();
    await vi.waitFor(() => expect(rows().length).toBe(before - 1), { timeout: 3000 });
  });

  it('filters the list by person', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(People, { target: host, props: { params: {} } });
    const rows = () => host.querySelectorAll('section[aria-labelledby="all-h"] tbody tr');
    await vi.waitFor(() => expect(rows().length).toBeGreaterThan(1), { timeout: 3000 });
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="Show person"]')!;
    select.value = [...select.options].find((o) => o.textContent === 'Mira Schulz')!.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(rows().length).toBeGreaterThan(0);
    expect([...rows()].every((r) => r.textContent!.startsWith('Mira Schulz'))).toBe(true);
  });

  it('opens a dialog from the timeline and deletes the period there', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(People, { target: host, props: { params: {} } });
    await vi.waitFor(() => expect(host.querySelector('section[aria-labelledby="all-h"] button[aria-pressed]')).toBeTruthy(), { timeout: 3000 });
    [...host.querySelectorAll<HTMLButtonElement>('section[aria-labelledby="all-h"] button[aria-pressed]')].find((b) => /Timeline/.test(b.textContent ?? ''))!.click();
    await settle();
    const bars = () => host.querySelectorAll<HTMLButtonElement>('button.bar:not(.past)');
    await vi.waitFor(() => expect(bars().length).toBeGreaterThan(0), { timeout: 3000 });
    const before = bars().length;
    bars()[0]!.click();
    await settle();
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog).toBeTruthy();
    [...dialog.querySelectorAll<HTMLButtonElement>('button')].find((b) => /Delete/.test(b.textContent ?? ''))!.click();
    await vi.waitFor(() => expect(bars().length).toBe(before - 1), { timeout: 3000 });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('shows the absences of a person in the times panel', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(People, { target: host, props: { params: {} } });
    await vi.waitFor(() => expect(host.querySelectorAll('button[aria-label^="Times and leaving"]').length).toBeGreaterThan(0), { timeout: 3000 });
    host.querySelector<HTMLButtonElement>('button[aria-label^="Times and leaving"]')!.click();
    await settle();
    const panel = host.querySelector('aside')!;
    expect(panel.textContent).toMatch(/Absence periods/);
    expect(panel.querySelector('button.btn')).toBeTruthy();
  });
});
