import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../lib/api';
import { app } from '../../lib/app.svelte';
import { mockApi } from '../../lib/mock';
import { createReviewMock } from '../../lib/mock/review';
import { sprints as demoSprints } from '../../lib/mock/shared';
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

  it('keeps a typed rest that is not a number from being saved', async () => {
    await show(Review, running);
    await type(field('rv-notdone'), '1');
    await type(field('rv-rest'), 'abc');
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
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
    await api.CloseReview('atlas', past, { commitment: null, notDone: 1, additionalDone: 0, restNext: 0, list: [], frozenDays: 45, products: [], production: 0, tag: '' });
    await api.ReopenReview('atlas', past);
    await api.CloseReview('atlas', past, { commitment: null, notDone: 3, additionalDone: 0, restNext: 0, list: [], frozenDays: 45, products: [], production: 0, tag: '' });

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

// A team that commits to tickets: the table lists them, and "will finish" / "carry-over" per
// ticket decides the numbers (the typed fields are replaced by figures that follow the table).
describe('Review page with tickets', () => {
  let tickets = createReviewMock(demoSprints, { tickets: true });
  let running: string;
  beforeEach(async () => {
    tickets = createReviewMock(demoSprints, { tickets: true }); // a fresh, open review per test
    app.toasts = [];
    running = (await mockApi.Sprints('atlas')).find((s) => s.state === 'current')!.id;
    vi.spyOn(mockApi, 'SprintReview').mockImplementation((t, s) => tickets.SprintReview(t, s));
    vi.spyOn(mockApi, 'CloseReview').mockImplementation((t, s, i) => tickets.CloseReview(t, s, i));
    vi.spyOn(mockApi, 'ReopenReview').mockImplementation((t, s) => tickets.ReopenReview(t, s));
  });
  afterEach(() => vi.restoreAllMocks());

  const num = (id: string) => Number(host.querySelector(`[data-testid="${id}"]`)!.textContent!.replace(',', '.'));
  const rowOf = (key: string) => [...host.querySelectorAll('tbody tr')].find((tr) => tr.querySelector('.key')?.textContent === key)!;
  const expectation = (key: string, label: RegExp) => [...rowOf(key).querySelectorAll('button')].find((b) => label.test(b.textContent ?? ''))!;
  const restField = (key: string) => host.querySelector<HTMLInputElement>(`input[aria-label="Rest of ${key}"]`)!;
  const target = (key: string) => host.querySelector<HTMLSelectElement>(`select[aria-label="Where ${key} continues"]`)!;

  it('takes the numbers from the table instead of typed fields', async () => {
    await show(Review, running);
    expect(host.querySelector('#rv-notdone')).toBeNull();
    // Nothing is done yet: all five tickets (24 points) are not done, and their rest continues.
    expect(num('not-done')).toBe(24);
    expect(num('rest-next')).toBe(24);
    expect(num('velocity')).toBe(0);
  });

  it('marking a ticket "will finish" lowers Not done and the rest and raises the velocity, "carry-over" takes it back', async () => {
    await show(Review, running);
    expectation('ATL-101', /will finish/).click();
    await tick();
    expect(num('not-done')).toBe(19);
    expect(num('rest-next')).toBe(19);
    expect(num('velocity')).toBe(5);
    // A finished ticket has no rest to enter.
    expect(restField('ATL-101')).toBeNull();

    expectation('ATL-103', /will finish/).click();
    await tick();
    expect(num('not-done')).toBe(11);
    expect(num('velocity')).toBe(13);

    expectation('ATL-101', /carry-over/).click();
    await tick();
    expect(num('not-done')).toBe(16);
    expect(num('velocity')).toBe(8);
    expect(restField('ATL-101').value).toBe('5');
  });

  it('a typed rest changes only "Rest", not "Not done"', async () => {
    await show(Review, running);
    await type(restField('ATL-103'), '2');
    expect(num('rest-next')).toBe(18);
    expect(num('not-done')).toBe(24);
    await type(restField('ATL-103'), '2,5');
    expect(num('rest-next')).toBe(18.5);
  });

  it('a ticket that continues in the backlog by choice is not part of the rest', async () => {
    await show(Review, running);
    const select = target('ATL-102');
    select.value = 'backlog';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    expect(num('rest-next')).toBe(24 - 3);
    expect(num('not-done')).toBe(24);
  });

  it('refuses a rest that is not a number and keeps the sprint open', async () => {
    await show(Review, running);
    await type(restField('ATL-104'), 'abc');
    expect(host.querySelector('[role="alert"]')?.textContent).toMatch(/Enter numbers of 0 or more/);
    expect(button(/Close sprint/).disabled).toBe(true);
    await type(restField('ATL-104'), '1');
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(button(/Close sprint/).disabled).toBe(false);
  });

  it('sends the decisions of the table when the sprint is closed', async () => {
    await show(Review, running);
    expectation('ATL-101', /will finish/).click();
    await type(restField('ATL-102'), '1');
    await tick();
    button(/Close sprint/).click();
    await vi.waitFor(() => expect(mockApi.CloseReview).toHaveBeenCalledTimes(1), { timeout: 3000 });
    const input = vi.mocked(mockApi.CloseReview).mock.calls[0]![2];
    expect(input.list.find((r) => r.key === 'ATL-101')!.done).toBe(true);
    const carried = input.list.find((r) => r.key === 'ATL-102')!;
    expect(carried.done).toBe(false);
    expect(carried.rest).toBe(1);
    await vi.waitFor(() => expect(host.textContent).toMatch(/closed/), { timeout: 3000 });
    // A closed review shows what was stored: figures stay, the decisions cannot be changed any more.
    expect(num('not-done')).toBe(19);
    expect(expectation('ATL-101', /will finish/).disabled).toBe(true);
    expect(restField('ATL-102').disabled).toBe(true);
  });

  // Regression (Review ticket column): the ticket cell is a plain table cell with the key in
  // its own span and the title next to it, not a grid that tore key and title apart.
  it('shows key and title together in one table cell of the ticket column', async () => {
    await show(Review, running);
    const cell = rowOf('ATL-101').querySelector('td')!;
    expect(cell.classList.contains('tk')).toBe(true);
    expect(cell.classList.contains('ticket')).toBe(false);
    expect(cell.querySelector('.key')!.textContent).toBe('ATL-101');
    expect(cell.textContent).toContain('Single sign-on for the portal');
    expect([...host.querySelectorAll('thead th')][0]!.textContent).toBe('Ticket');
    for (const key of ['ATL-101', 'ATL-102', 'ATL-103', 'ATL-104', 'ATL-105']) {
      expect(rowOf(key).querySelector('td')!.querySelector('.key')!.textContent).toBe(key);
    }
  });
});
