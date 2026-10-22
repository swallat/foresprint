import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AbsenceGrid from './AbsenceGrid.svelte';
import { days, parseDays } from './format';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

// The mock answers after a dynamic import, so wait on the result instead of counting ticks.
async function settle() {
  await new Promise((r) => setTimeout(r, 30));
  await tick();
}

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
});

async function open(props: Record<string, unknown> = {}) {
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(AbsenceGrid, { target: host, props: { team: 'atlas', count: 3, ...props } });
  await vi.waitFor(() => expect(inputs().length).toBeGreaterThan(0), { timeout: 3000 });
}

const inputs = () => [...host.querySelectorAll<HTMLInputElement>('input[data-abs-col]')];

describe('format', () => {
  it('reads comma and point, empty is zero', () => {
    expect(parseDays('2,5')).toBe(2.5);
    expect(parseDays(' 3 ')).toBe(3);
    expect(parseDays('')).toBe(0);
    expect(Number.isNaN(parseDays('abc'))).toBe(true);
    expect(days(2.5)).toMatch(/2[.,]5/);
  });
});

describe('AbsenceGrid', () => {
  it('shows a row per person and a column per sprint with the states', async () => {
    await open();
    expect(host.querySelectorAll('tbody tr').length).toBeGreaterThan(6);
    expect(inputs().length).toBe(18); // 6 people, 3 sprints
    expect(host.textContent).toMatch(/Announced/); // the mock has announced absences
  });

  it('announces typed days and keeps a cleared value for undo', async () => {
    await open();
    const cell = inputs().find((i) => i.value === '')!;
    cell.value = '2,3';
    cell.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(cell.value).toMatch(/2[.,]5/); // half days
    expect(cell.closest('.cell')!.classList.contains('a')).toBe(true);

    cell.value = '';
    cell.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(cell.closest('.cell')!.classList.contains('g')).toBe(true);
    const undo = cell.closest('.cell')!.querySelector<HTMLButtonElement>('button')!;
    undo.click();
    await settle();
    expect(cell.value).toMatch(/2[.,]5/);
  });

  it('freezing confirms the sprint and shows the frozen state', async () => {
    await open();
    const idx = [...host.querySelectorAll('thead th.sc')].findIndex((th) => th.textContent!.includes(column));
    host.querySelectorAll<HTMLButtonElement>('tbody tr:last-child button')[idx]!.click();
    await settle();
    await settle();
    expect(cell.value).toMatch(/3/);
    expect(cell.closest('.cell')!.classList.contains('c')).toBe(true);
  });

  it('stays out of reach for a finished sprint', async () => {
    await open({ from: '2026.12', count: 1 });
    expect(inputs().every((i) => i.disabled)).toBe(true);
  });
});
