// Plan page, operated like a user: tickets are moved with the button, the keyboard and by
// dragging, and the capacity bar, the sums and the lanes must follow. Runs against the browser
// mock (sprint 2026.21 has 6 free tickets in the sprint and 6 candidates, estimates in points).
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../../lib/mock';
import { app } from '../../lib/app.svelte';
import { resetPlanMock } from '../../lib/mock/plan';
import Plan from './Plan.svelte';

const SPRINT = '2026.21';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

beforeEach(() => {
  resetPlanMock();
  app.toasts = [];
});

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  vi.restoreAllMocks();
});

async function show(): Promise<void> {
  app.team = 'atlas';
  app.sprint = SPRINT;
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(Plan, { target: host, props: { params: {} } });
  await vi.waitFor(() => expect(host.querySelector('#lanes')).not.toBeNull(), { timeout: 3000 });
  await tick();
}

const lane = (name: 'Candidates' | 'Sprint') =>
  host.querySelector<HTMLElement>(name === 'Candidates' ? '[role="group"][aria-label="Candidates"]' : `[role="group"][aria-label="Sprint ${SPRINT}"]`)!;
const keys = (name: 'Candidates' | 'Sprint') => [...lane(name).querySelectorAll<HTMLElement>('[data-key]')].map((e) => e.dataset.key);
const row = (key: string) => host.querySelector<HTMLElement>(`[data-key="${key}"]`)!;
/** The text of the capacity bar of the sprint lane, e.g. "31 of 37 SP, range 33 to 43". */
const bar = () => lane('Sprint').querySelector('[role="img"]')!.getAttribute('aria-label')!;
const used = () => Number(/^(\d+(?:[.,]\d+)?) of/.exec(bar())![1]!.replace(',', '.'));
const moveButton = (key: string) => row(key).querySelector<HTMLButtonElement>('button[aria-label^="Take"]')!;

/** Waits until the page has reloaded after a move (the mock answers asynchronously). */
async function settled(check: () => void): Promise<void> {
  await vi.waitFor(check, { timeout: 3000 });
  await tick();
}

/** A drag event with the pointer height; jsdom has no DragEvent, a MouseEvent carries the same fields. */
function drag(type: string, clientY = 0): MouseEvent {
  return new MouseEvent(type, { bubbles: true, cancelable: true, clientY });
}

describe('Plan page', () => {
  it('shows the sprint tickets in one lane, the candidates in the other, and the sum in the bar', async () => {
    await show();
    expect(keys('Sprint')).toEqual(['ATL-412', 'ATL-415', 'ATL-417', 'ATL-420', 'ATL-421', 'ATL-423']);
    expect(keys('Candidates')).toContain('ATL-424');
    expect(used()).toBe(34);
  });

  it('hides the running sprint and filters the candidates', async () => {
    await show();
    expect(keys('Candidates')).not.toContain('ATL-401');
    expect(keys('Candidates')).toContain('ATL-433');
    const box = (label: string) =>
      [...lane('Candidates').querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent!.includes(label))!.querySelector('input')!;
    box('Running sprint too').click();
    await tick();
    expect(keys('Candidates')).toContain('ATL-401');
    box('Refined only').click();
    await tick();
    expect(keys('Candidates')).not.toContain('ATL-433');
    expect(keys('Candidates')).toContain('ATL-424');
  });

  it('taking a ticket out with the button lowers the bar by its estimate and puts it into the candidates', async () => {
    await show();
    const before = used();
    moveButton('ATL-415').click();
    await settled(() => expect(keys('Candidates')).toContain('ATL-415'));
    expect(keys('Sprint')).not.toContain('ATL-415');
    expect(used()).toBe(before - 8);
    expect(app.toasts.map((x) => x.text)).toContain('ATL-415 taken out of the sprint.');
  });

  it('taking a candidate in raises the bar by its estimate and the toast can undo it', async () => {
    await show();
    const before = used();
    moveButton('ATL-436').click();
    await settled(() => expect(keys('Sprint')).toContain('ATL-436'));
    expect(used()).toBe(before + 13);
    // 34 + 13 = 47 is above the range of 43: the page says so in words, not only by colour.
    expect(lane('Sprint').textContent).toMatch(/over the range/);

    const undo = app.toasts.find((x) => x.text === 'ATL-436 taken into the sprint.')?.action;
    expect(undo?.label).toBe('Undo');
    undo!.run();
    await settled(() => expect(keys('Sprint')).not.toContain('ATL-436'));
    expect(used()).toBe(before);
  });

  it('the right-click menu moves a ticket between the lanes and to the top or bottom of its list', async () => {
    await show();
    const menu = (key: string) => {
      row(key).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 10 }));
      return tick();
    };
    const item = (label: string) => [...document.querySelectorAll<HTMLButtonElement>('.ctx [role="menuitem"]')].find((b) => b.textContent!.includes(label))!;
    await menu('ATL-415');
    expect(item(`Sprint ${SPRINT}`).disabled).toBe(true);
    item('Candidates').click();
    await settled(() => expect(keys('Candidates')).toContain('ATL-415'));
    expect(keys('Sprint')).not.toContain('ATL-415');

    // The mock does not re-order; the call to the rank order is what counts.
    const sort = vi.spyOn(mockApi, 'MoveTicketByRank');
    const first = keys('Sprint')[0]!;
    const last = keys('Sprint').at(-1)!;
    await menu('ATL-423');
    item('Top of the list').click();
    await settled(() => expect(sort).toHaveBeenCalledWith('atlas', 'ATL-423', first, false));
    await menu('ATL-412');
    item('Bottom of the list').click();
    await settled(() => expect(sort).toHaveBeenCalledWith('atlas', 'ATL-412', last, true));
  });

  it('Alt+arrow moves the ticket under the focus between the lanes', async () => {
    await show();
    const before = used();
    row('ATL-420').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', altKey: true, bubbles: true, cancelable: true }));
    await settled(() => expect(keys('Candidates')).toContain('ATL-420'));
    expect(used()).toBe(before - 3);

    row('ATL-420').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', altKey: true, bubbles: true, cancelable: true }));
    await settled(() => expect(keys('Sprint')).toContain('ATL-420'));
    expect(used()).toBe(before);
  });

  it('a key without Alt does not move anything', async () => {
    await show();
    const spy = vi.spyOn(mockApi, 'EarmarkTicket');
    row('ATL-420').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }));
    await tick();
    expect(spy).not.toHaveBeenCalled();
    expect(keys('Sprint')).toContain('ATL-420');
  });

  it('dragging a candidate onto the sprint lane takes it in', async () => {
    await show();
    const before = used();
    row('ATL-426').dispatchEvent(drag('dragstart'));
    lane('Sprint').dispatchEvent(drag('dragover'));
    lane('Sprint').dispatchEvent(drag('drop'));
    await settled(() => expect(keys('Sprint')).toContain('ATL-426'));
    expect(used()).toBe(before + 2);
  });

  it('dragging a sprint ticket onto the candidate lane takes it out', async () => {
    await show();
    const before = used();
    row('ATL-421').dispatchEvent(drag('dragstart'));
    lane('Candidates').dispatchEvent(drag('drop'));
    await settled(() => expect(keys('Candidates')).toContain('ATL-421'));
    expect(used()).toBe(before - 8);
  });

  describe('dragging inside one lane (re-sorting)', () => {
    it('dropping on a ticket of the same lane re-sorts and does not take the ticket in or out', async () => {
      await show();
      const earmark = vi.spyOn(mockApi, 'EarmarkTicket');
      const sort = vi.spyOn(mockApi, 'MoveWorkPackage');
      const before = used();
      row('ATL-412').dispatchEvent(drag('dragstart'));
      // getBoundingClientRect is all zeros in jsdom, so a pointer below 0 is the lower half: "after".
      row('ATL-420').parentElement!.dispatchEvent(drag('dragover', 5));
      row('ATL-420').parentElement!.dispatchEvent(drag('drop', 5));
      await settled(() => expect(sort).toHaveBeenCalledTimes(1));
      expect(sort).toHaveBeenCalledWith('atlas', 'ATL-412', 'ATL-420', true);
      expect(earmark).not.toHaveBeenCalled();
      expect(used()).toBe(before);
      expect(keys('Sprint')).toContain('ATL-412');
    });

    it('the upper half of the target puts the ticket before it', async () => {
      await show();
      const sort = vi.spyOn(mockApi, 'MoveWorkPackage');
      row('ATL-423').dispatchEvent(drag('dragstart'));
      row('ATL-415').parentElement!.dispatchEvent(drag('dragover', -5));
      row('ATL-415').parentElement!.dispatchEvent(drag('drop', -5));
      await settled(() => expect(sort).toHaveBeenCalledTimes(1));
      expect(sort).toHaveBeenCalledWith('atlas', 'ATL-423', 'ATL-415', false);
    });

    it('re-sorts the candidates the same way', async () => {
      await show();
      const sort = vi.spyOn(mockApi, 'MoveWorkPackage');
      const earmark = vi.spyOn(mockApi, 'EarmarkTicket');
      row('ATL-433').dispatchEvent(drag('dragstart'));
      row('ATL-424').parentElement!.dispatchEvent(drag('dragover', -5));
      row('ATL-424').parentElement!.dispatchEvent(drag('drop', -5));
      await settled(() => expect(sort).toHaveBeenCalledTimes(1));
      expect(sort).toHaveBeenCalledWith('atlas', 'ATL-433', 'ATL-424', false);
      expect(earmark).not.toHaveBeenCalled();
    });

    it('dropping a ticket on the empty part of its own lane changes nothing', async () => {
      await show();
      const earmark = vi.spyOn(mockApi, 'EarmarkTicket');
      const sort = vi.spyOn(mockApi, 'MoveWorkPackage');
      const before = used();
      row('ATL-412').dispatchEvent(drag('dragstart'));
      lane('Sprint').dispatchEvent(drag('drop'));
      await tick();
      expect(earmark).not.toHaveBeenCalled();
      expect(sort).not.toHaveBeenCalled();
      expect(used()).toBe(before);
      expect(app.toasts).toEqual([]);
    });

    it('a ticket dragged from the other lane onto a ticket is not re-sorted: the lane drop takes it in', async () => {
      await show();
      const sort = vi.spyOn(mockApi, 'MoveWorkPackage');
      const before = used();
      row('ATL-424').dispatchEvent(drag('dragstart'));
      // The row ignores the foreign ticket, the event reaches the lane, which moves it.
      row('ATL-412').parentElement!.dispatchEvent(drag('dragover', 5));
      row('ATL-412').parentElement!.dispatchEvent(drag('drop', 5));
      await settled(() => expect(keys('Sprint')).toContain('ATL-424'));
      expect(sort).not.toHaveBeenCalled();
      expect(used()).toBe(before + 3);
    });
  });

  it('freezing the plan records the sprint tickets and then locks the lanes', async () => {
    await show();
    const freeze = vi.spyOn(mockApi, 'FreezePlan');
    host.querySelector<HTMLButtonElement>('#freeze')!.click();
    await settled(() => expect(host.querySelector('#frozen')).not.toBeNull());
    expect(freeze).toHaveBeenCalledWith('atlas', SPRINT, expect.objectContaining({ tickets: ['ATL-412', 'ATL-415', 'ATL-417', 'ATL-420', 'ATL-421', 'ATL-423'] }));
    expect(host.querySelector('#frozen')!.textContent).toContain('34');
    expect(host.querySelector('button[aria-label^="Take"]')).toBeNull();
    expect(row('ATL-412').getAttribute('draggable')).toBe('false');

    // A drop on a frozen plan is ignored.
    const earmark = vi.spyOn(mockApi, 'EarmarkTicket');
    row('ATL-424').dispatchEvent(drag('dragstart'));
    lane('Sprint').dispatchEvent(drag('drop'));
    await tick();
    expect(earmark).not.toHaveBeenCalled();
    expect(keys('Sprint')).not.toContain('ATL-424');
  });
});
