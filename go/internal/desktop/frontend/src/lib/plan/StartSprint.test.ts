// The start of a sprint: it freezes the plan from the Plan page, takes a start day between the
// planned first day and today, and a running sprint can move or take back its start.
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../mock';
import { app } from '../app.svelte';
import type { FreezeInput, Stage } from '../types.plan';
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
const input: FreezeInput = { tickets: ['ATL-1'], commitment: null, amounts: {}, removed: [] };

interface Shown {
  sprint: string;
  start: string;
  end: string;
  startedOn: string;
  due: boolean;
  stage: Stage;
  plan?: () => FreezeInput;
}

function show(props: Partial<Shown> = {}): void {
  app.team = 'atlas';
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(StartSprint, {
    target: host,
    props: { sprint: '2026.21', start: day(-2), end: day(12), startedOn: '', due: true, stage: 'open', plan: () => input, ...props },
  });
}

const button = (label: string) => [...host.querySelectorAll('button, a')].find((b) => b.textContent?.includes(label)) as HTMLElement | undefined;

describe('StartSprint', () => {
  it('only explains when the first day has not come, and shows nothing for a finished sprint', async () => {
    show({ due: false, start: day(3), end: day(17) });
    await tick();
    expect(host.querySelector('.banner.info')).not.toBeNull();
    expect(button('Start sprint')).toBeUndefined();
    unmount(cmp!);
    host.remove();
    show({ due: false, stage: 'past' });
    await tick();
    expect(host.querySelector('.banner')).toBeNull();
  });

  it('on a page without the plan it points to the Plan page', async () => {
    show({ plan: undefined });
    await tick();
    expect(button('Start sprint')).toBeUndefined();
    expect(button('Go to Plan')!.getAttribute('href')).toBe('#/sprint/plan');
  });

  it('freezes the plan with the start and may name a later day up to today', async () => {
    const start = vi.spyOn(mockApi, 'StartSprintWithPlan');
    show();
    await tick();
    button('Start sprint')!.click();
    await tick();
    const field = host.querySelector<HTMLInputElement>('input[type="date"]')!;
    expect(field.value).toBe(day(-2));
    expect(field.min).toBe(day(-2));
    expect(field.max).toBe(day(0));
    field.value = day(-1);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    host.querySelector<HTMLButtonElement>('.row button.primary')!.click();
    await vi.waitFor(() => expect(start).toHaveBeenCalledWith('atlas', '2026.21', day(-1), input));
  });

  it('starts a plan that is frozen already without a new plan', async () => {
    const only = vi.spyOn(mockApi, 'StartSprint');
    show({ stage: 'planned' });
    await tick();
    button('Start sprint')!.click();
    await tick();
    host.querySelector<HTMLButtonElement>('.row button.primary')!.click();
    await vi.waitFor(() => expect(only).toHaveBeenCalledWith('atlas', '2026.21', day(-2)));
  });

  it('refuses a day outside the sprint start and today', async () => {
    show();
    await tick();
    button('Start sprint')!.click();
    await tick();
    const field = host.querySelector<HTMLInputElement>('input[type="date"]')!;
    field.value = day(-5);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    expect(host.querySelector<HTMLButtonElement>('.row button.primary')!.disabled).toBe(true);
  });

  it('lets a running sprint move or take back its start, but not once its last day is over', async () => {
    const back = vi.spyOn(mockApi, 'WithdrawSprintStart');
    show({ due: false, stage: 'current', startedOn: day(-2) });
    await tick();
    expect(button('Change start day')).toBeDefined();
    button('Take start back')!.click();
    await vi.waitFor(() => expect(back).toHaveBeenCalledWith('atlas', '2026.21'));
    unmount(cmp!);
    host.remove();
    show({ due: false, stage: 'current', startedOn: day(-20), end: day(-1) });
    await tick();
    expect(button('Take start back')).toBeUndefined();
  });
});
