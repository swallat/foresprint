import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Products from './Products.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
});

describe('Product shares', () => {
  it('keeps every share typed in quick succession (German comma, "%" and whole numbers)', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(Products, { target: host, props: { params: {} } });
    const inputs = () => [...host.querySelectorAll<HTMLInputElement>('input.share')];
    await vi.waitFor(() => expect(inputs().length).toBeGreaterThan(1), { timeout: 3000 });
    const typed = ['40', '30 %', '20,0', '10'];
    const fields = inputs().slice(0, typed.length);
    // One change event per field right after the other, as when tabbing through the column.
    fields.forEach((field, i) => {
      field.value = typed[i]!;
      field.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await vi.waitFor(() => expect(inputs().slice(0, fields.length).map((f) => f.value)).toEqual(['40', '30', '20', '10'].slice(0, fields.length)), { timeout: 3000 });
  });

  it('refuses a share above 100 and shows the stored value again', async () => {
    host = document.createElement('div');
    document.body.append(host);
    cmp = mount(Products, { target: host, props: { params: {} } });
    const inputs = () => [...host.querySelectorAll<HTMLInputElement>('input.share')];
    await vi.waitFor(() => expect(inputs().length).toBeGreaterThan(0), { timeout: 3000 });
    const first = inputs()[0]!;
    const before = first.value;
    first.value = '250';
    first.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    await vi.waitFor(() => expect(first.value).toBe(before), { timeout: 3000 });
  });
});
