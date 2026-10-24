// Setup wizard, operated like a user: the "new team" step reads the first sprint's start in the
// form of the language (20.10.2026 in German, 10/20/2026 in English), refuses what is not a day
// and hands the stored form (YYYY-MM-DD) to the core. The wizard opens on the team step the way
// "Create a new team" does (?add=team), against the browser mock.
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../../lib/mock';
import { useLanguage } from '../../lib/i18n.svelte';
import { current } from '../../lib/router.svelte';
import FirstRun from './FirstRun.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;
let created: Parameters<typeof mockApi.SetupCreateTeam>[0][];

beforeEach(() => {
  created = [];
  localStorage.clear();
  current.query = { add: 'team' };
  vi.spyOn(mockApi, 'SetupCreateTeam').mockImplementation(async (req) => {
    created.push(req);
    return { key: 'atlas', name: req.name, people: 0, sprints: 3, tickets: true, products: 0 };
  });
});

afterEach(async () => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  current.query = {};
  await useLanguage('en');
  vi.restoreAllMocks();
});

async function show(): Promise<void> {
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(FirstRun, { target: host, props: { params: {} } });
  await vi.waitFor(() => expect(host.querySelector('#su-sd')).not.toBeNull(), { timeout: 3000 });
  await new Promise((r) => setTimeout(r, 30));
  await tick();
}

const field = (id: string) => host.querySelector<HTMLInputElement>(`#${id}`)!;
const button = (label: RegExp) => [...host.querySelectorAll('button')].find((b) => label.test(b.textContent ?? ''))!;
const heading = () => host.querySelector('h2')!.textContent;

async function type(el: HTMLInputElement, value: string): Promise<void> {
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
}

describe('Setup wizard, new team', () => {
  it('asks for the start in the order of the English language and passes it on as YYYY-MM-DD', async () => {
    await show();
    expect(field('su-sd').placeholder).toBe('MM/DD/YYYY');
    await type(field('su-tn'), 'Team North');
    await type(field('su-sid'), '2026.21');
    await type(field('su-sd'), '10/26/2026');
    button(/^Next/).click();
    await vi.waitFor(() => expect(heading()).toMatch(/Tickets|Work/i), { timeout: 3000 });
    button(/^Next/).click();
    await vi.waitFor(() => expect(button(/Go to Today/)).toBeDefined(), { timeout: 3000 });
    button(/Go to Today/).click();
    await vi.waitFor(() => expect(created).toHaveLength(1), { timeout: 3000 });
    expect(created[0]).toMatchObject({ name: 'Team North', firstSprintId: '2026.21', firstStart: '2026-10-26' });
  });

  it('in German the start is typed as TT.MM.JJJJ and means day first', async () => {
    await useLanguage('de');
    await show();
    expect(field('su-sd').placeholder).toBe('TT.MM.JJJJ');
    await type(field('su-tn'), 'Team Nord');
    await type(field('su-sd'), '05.11.2026'); // 5 November, not 11 May
    button(/^Weiter/).click();
    await vi.waitFor(() => expect(heading()).not.toBe('Team'), { timeout: 3000 });
    button(/^Weiter/).click();
    await vi.waitFor(() => expect(button(/Zu Heute/)).toBeDefined(), { timeout: 3000 });
    button(/Zu Heute/).click();
    await vi.waitFor(() => expect(created).toHaveLength(1), { timeout: 3000 });
    expect(created[0]!.firstStart).toBe('2026-11-05');
  });

  it('the suggested start is a day in the form of the language', async () => {
    await useLanguage('de');
    await show();
    expect(field('su-sd').value).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  });

  it('refuses a start that is no day and stays on the team step without creating anything', async () => {
    await show();
    await type(field('su-tn'), 'Team North');
    for (const bad of ['02/31/2026', '26.10.2026', '10/26/26', 'soon', '']) {
      await type(field('su-sd'), bad);
      button(/^Next/).click();
      await vi.waitFor(() => expect(host.textContent).toContain('Enter the start of the first sprint as a date (MM/DD/YYYY).'), { timeout: 3000 });
      expect(heading()).toBe('Team');
    }
    expect(created).toHaveLength(0);
  });

  it('accepts the stored form YYYY-MM-DD as well', async () => {
    await show();
    await type(field('su-tn'), 'Team North');
    await type(field('su-sd'), '2026-10-26');
    button(/^Next/).click();
    await vi.waitFor(() => expect(heading()).not.toBe('Team'), { timeout: 3000 });
    expect(host.textContent).not.toContain('Enter the start of the first sprint');
  });

  it('asks for a team name and a sprint ID before it goes on', async () => {
    await show();
    button(/^Next/).click();
    await vi.waitFor(() => expect(host.textContent).toContain('Enter a name for the team.'), { timeout: 3000 });
    await type(field('su-tn'), 'Team North');
    await type(field('su-sid'), '');
    button(/^Next/).click();
    await vi.waitFor(() => expect(host.textContent).toContain('Enter the ID of the first sprint.'), { timeout: 3000 });
    expect(heading()).toBe('Team');
  });

  it('reads the naming pattern from the sprint name and the start', async () => {
    await show();
    await type(field('su-sid'), 'Team 2026.21');
    await type(field('su-sd'), '10/26/2026');
    await vi.waitFor(() => expect(host.textContent).toContain('Read from the name:'), { timeout: 3000 });
    expect(host.textContent).toMatch(/Read from the name: .*\{N\}/);
  });
});
