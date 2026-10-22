import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../lib/api';
import { app } from '../../lib/app.svelte';
import { mockApi } from '../../lib/mock';
import Minutes from './Minutes.svelte';
import Review from './Review.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
});

async function show(page: typeof Review, sprint: string) {
  app.team = 'atlas';
  app.sprint = sprint;
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(page, { target: host, props: { params: {} } });
  await vi.waitFor(() => expect(host.querySelector('h1')).not.toBeNull(), { timeout: 3000 });
  await new Promise((r) => setTimeout(r, 30));
  await tick();
}

const field = (id: string) => host.querySelector<HTMLInputElement>(`#${id}`)!;
const button = (label: RegExp) => [...host.querySelectorAll('button')].find((b) => label.test(b.textContent ?? ''))!;

async function type(el: HTMLInputElement, value: string) {
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
}

describe('Review page', () => {
  let past: string;
  let running: string;
  let future: string;
  beforeEach(async () => {
    const list = await mockApi.Sprints('atlas');
    past = [...list].reverse().find((s) => s.state === 'past')!.id;
    running = list.find((s) => s.state === 'current')!.id;
    future = list.find((s) => s.state === 'future')!.id;
    await api.ReopenReview('atlas', past).catch(() => undefined);
  });

  it('calculates the velocity and the rate while typing', async () => {
    await show(Review, running);
    const before = Number(host.querySelector('[data-testid="velocity"]')!.textContent!.replace(',', '.'));
    await type(field('rv-notdone'), '4');
    await type(field('rv-extra'), '2');
    const now = Number(host.querySelector('[data-testid="velocity"]')!.textContent!.replace(',', '.'));
    expect(now).toBe(before - 4 + 2);
    await type(field('rv-days'), '40');
    expect(host.querySelector('[data-testid="rate"]')!.textContent).toMatch(/\d/);
  });

  it('refuses a rest larger than what was not done', async () => {
    await show(Review, running);
    await type(field('rv-notdone'), '1');
    await type(field('rv-rest'), '3');
    expect(host.querySelector('[role="alert"]')?.textContent).toMatch(/rest|Rest/);
    expect(button(/Close sprint|Sprint abschließen/).disabled).toBe(true);
  });

  it('says a sprint that has not begun cannot be reviewed', async () => {
    await show(Review, future);
    expect(host.textContent).toMatch(/has not begun|noch nicht begonnen/);
    expect(button(/Close sprint|Sprint abschließen/).disabled).toBe(true);
  });

  it('closes the latest finished sprint, writes minutes and reopens it', async () => {
    await show(Review, past);
    expect(host.querySelector('[data-testid="done"]')).not.toBeNull(); // the demo team has products
    await type(field('rv-notdone'), '2');
    button(/Close sprint|Sprint abschließen/).click();
    await vi.waitFor(() => expect(host.textContent).toMatch(/closed|abgeschlossen/), { timeout: 3000 });
    expect(field('rv-notdone').disabled).toBe(true);
    const files = await api.SprintMinutes('atlas', past);
    expect(files.some((f) => f.kind === 'review' && !f.obsolete)).toBe(true);

    button(/Reopen review|Review wieder öffnen/).click();
    await vi.waitFor(() => expect(field('rv-notdone').disabled).toBe(false), { timeout: 3000 });
    expect((await api.SprintMinutes('atlas', past)).every((f) => f.obsolete)).toBe(true);
  });
});

describe('Minutes page', () => {
  it('lists the files of the sprint, marks superseded ones and shows the text', async () => {
    const list = await mockApi.Sprints('atlas');
    const past = [...list].reverse().find((s) => s.state === 'past')!.id;
    await api.ReopenReview('atlas', past).catch(() => undefined);
    await api.CloseReview('atlas', past, { notDone: 1, additionalDone: 0, restNext: 0, list: [], frozenDays: 45, products: [], production: 0, tag: '' });
    await api.ReopenReview('atlas', past);
    await api.CloseReview('atlas', past, { notDone: 3, additionalDone: 0, restNext: 0, list: [], frozenDays: 45, products: [], production: 0, tag: '' });

    await show(Minutes, past);
    await vi.waitFor(() => expect(host.querySelectorAll('tbody tr').length).toBeGreaterThanOrEqual(2), { timeout: 3000 });
    expect(host.querySelectorAll('tr.old').length).toBeGreaterThanOrEqual(1);
    const open = [...host.querySelectorAll('button')].find((b) => /^(Show|Anzeigen)$/.test((b.textContent ?? '').trim()))!;
    open.click();
    await vi.waitFor(() => expect(host.querySelector('.md')).not.toBeNull(), { timeout: 3000 });
    expect(host.querySelector('.md table')).not.toBeNull();
    expect(host.querySelector('.md strong, .md h3')).not.toBeNull();
  });
});
