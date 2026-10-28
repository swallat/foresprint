// The start of a sprint: shown for a sprint that is not started, with a start day that cannot be
// before the planned first day or after today; a running sprint can move or take back its start.
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../mock';
import { app } from '../app.svelte';
import StartSprint from './StartSprint.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  vi.restoreAllMocks();
});

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const day = (offset: number) => iso(new Date(Date.now() + offset * 86400000));

interface Shown {
  sprint: string;
  start: string;
  end: string;
  startedOn: string;
  due: boolean;
  running: boolean;
}

function show(props: Partial<Shown> = {}): void {
  app.team = 'atlas';
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(StartSprint, {
    target: host,
    props: { sprint: '2026.21', start: day(-2), end: day(12), startedOn: '', due: true, running: false, ...props },
  });
}

const button = (label: string) => [...host.querySelectorAll('button')].find((b) => b.textContent?.includes(label));

describe('StartSprint', () => {
  it('shows nothing for a sprint that is neither due nor running', async () => {
    show({ due: false });
    await tick();
    expect(host.querySelector('.banner')).toBeNull();
  });

  it('starts from the planned first day by default and may name a later day up to today', async () => {
    const start = vi.spyOn(mockApi, 'StartSprint');
    show();
    await tick();
    button('Start sprint')!.click();
    await tick();
    const input = host.querySelector<HTMLInputElement>('input[type="date"]')!;
    expect(input.value).toBe(day(-2));
    expect(input.min).toBe(day(-2));
    expect(input.max).toBe(day(0));
    input.value = day(-1);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    button('Start sprint')!.click();
    await vi.waitFor(() => expect(start).toHaveBeenCalledWith('atlas', '2026.21', day(-1)));
  });

  it('refuses a day outside the sprint start and today', async () => {
    show();
    await tick();
    button('Start sprint')!.click();
    await tick();
    const input = host.querySelector<HTMLInputElement>('input[type="date"]')!;
    input.value = day(-5);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    const go = host.querySelector<HTMLButtonElement>('.row button.primary')!;
    expect(go.disabled).toBe(true);
  });

  it('lets a running sprint move or take back its start, but not once its last day is over', async () => {
    const back = vi.spyOn(mockApi, 'WithdrawSprintStart');
    show({ due: false, running: true, startedOn: day(-2) });
    await tick();
    expect(button('Change start day')).toBeDefined();
    button('Take start back')!.click();
    await vi.waitFor(() => expect(back).toHaveBeenCalledWith('atlas', '2026.21'));
    unmount(cmp!);
    host.remove();
    show({ due: false, running: true, startedOn: day(-20), end: day(-1) });
    await tick();
    expect(button('Take start back')).toBeUndefined();
  });
});
