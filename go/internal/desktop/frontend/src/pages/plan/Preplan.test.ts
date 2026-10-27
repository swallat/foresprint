// Pre-plan page, operated like a user: typing an amount per product changes the sums, the
// deviation against the earmarks and the over-capacity warning; the buttons take over the
// standard amounts and the earmarks. Runs against the browser mock (sprint 2026.22 has no
// earmarks, 2026.21 has 34 points earmarked; the upper end of the Forecast PLAN is 42 and 43).
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../../lib/mock';
import { app } from '../../lib/app.svelte';
import { resetPlanMock } from '../../lib/mock/plan';
import Preplan from './Preplan.svelte';

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

async function show(sprint: string): Promise<void> {
  app.team = 'atlas';
  app.sprint = sprint;
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(Preplan, { target: host, props: { params: {} } });
  await vi.waitFor(() => expect(host.querySelector('#product-table')).not.toBeNull(), { timeout: 3000 });
  await tick();
}

const input = (product: string) => host.querySelector<HTMLInputElement>(`input[aria-label="Pre-planned ${product}"]`)!;
const cells = (tr: Element) => [...tr.querySelectorAll('td')].map((c) => c.textContent!.trim());
const productRow = (name: string) => [...host.querySelectorAll('#product-table tbody tr')].find((tr) => tr.querySelector('td')?.textContent === name)!;
/** The "Total" row: product, standard, pre-planned, earmarks, deviation, planned, done. */
const total = () => cells(host.querySelector('#product-table tbody tr.sum:last-of-type')!);
const press = (id: string) => host.querySelector<HTMLButtonElement>(`#${id}`)!.click();

/** Types into an amount field and leaves it, like a user does (the page saves on "change"). */
async function enter(el: HTMLInputElement, text: string): Promise<void> {
  el.value = text;
  el.dispatchEvent(new Event('change', { bubbles: true }));
  await tick();
}
const settled = async (check: () => void) => {
  await vi.waitFor(check, { timeout: 3000 });
  await tick();
};

describe('Pre-plan page', () => {
  it('typing an amount for a product changes the sum and keeps the others empty', async () => {
    await show('2026.22');
    expect(total()[2]).toBe('–');
    await enter(input('Customer portal'), '12');
    await settled(() => expect(total()[2]).toBe('12'));
    expect(input('Customer portal').value).toBe('12');
    expect(input('Billing').value).toBe('');
    await enter(input('Billing'), '6,5');
    await settled(() => expect(input('Billing').value).toBe('6.5'));
    // The totals keep the decimals of the amounts: 18,5, not 19.
    expect(total()[2]).toBe('18.5');
  });

  it('the deviation is the pre-planned amount minus the earmarks', async () => {
    await show('2026.21');
    // Customer portal: 13 earmarked, Billing: 5 earmarked.
    await enter(input('Customer portal'), '10');
    await settled(() => expect(cells(productRow('Customer portal'))[4]).toBe('−3'));
    await enter(input('Billing'), '5');
    await settled(() => expect(cells(productRow('Billing'))[4]).toBe('0'));
  });

  it('an amount above the upper end of the forecast shows the warning, a lower one removes it', async () => {
    await show('2026.22');
    expect(host.querySelector('#overcap')).toBeNull();
    await enter(input('Customer portal'), '50');
    await settled(() => expect(host.querySelector('#overcap')).not.toBeNull());
    expect(host.querySelector('#overcap')!.textContent).toMatch(/upper end/);
    await enter(input('Customer portal'), '20');
    await settled(() => expect(host.querySelector('#overcap')).toBeNull());
  });

  it('clearing the field removes the pre-planned amount of the product', async () => {
    await show('2026.22');
    await enter(input('Billing'), '4');
    await settled(() => expect(total()[2]).toBe('4'));
    await enter(input('Billing'), '');
    await settled(() => expect(total()[2]).toBe('–'));
  });

  it('text that is not a number is not saved and the field shows the stored value again', async () => {
    await show('2026.22');
    const save = vi.spyOn(mockApi, 'SetPreplanned');
    await enter(input('Customer portal'), '12');
    await settled(() => expect(total()[2]).toBe('12'));
    save.mockClear();
    await enter(input('Customer portal'), 'twelve');
    await enter(input('Customer portal'), '-3');
    await tick();
    expect(save).not.toHaveBeenCalled();
    await settled(() => expect(input('Customer portal').value).toBe('12'));
    expect(total()[2]).toBe('12');
  });

  it('"Take over standard" fills every product with its standard amount', async () => {
    await show('2026.22');
    press('defaults');
    await settled(() => expect(total()[2]).toBe('36'));
    expect(input('Customer portal').value).toBe('13');
    expect(input('Billing').value).toBe('7');
    expect(input('Mobile app').value).toBe('9');
    expect(input('Platform').value).toBe('7');
    expect(app.toasts.map((x) => x.text)).toContain('Standard amounts taken over.');
  });

  it('"Take over earmarks" sets the amounts to the earmarked points and the deviation is zero', async () => {
    await show('2026.21');
    press('take');
    await settled(() => expect(input('Customer portal').value).toBe('13'));
    expect(input('Billing').value).toBe('5');
    expect(input('Mobile app').value).toBe('8');
    expect(input('Platform').value).toBe('8');
    expect(total()[2]).toBe('34');
    expect(cells(productRow('Platform'))[4]).toBe('0');
  });

  it('the earmarked tickets are listed by project with their sum', async () => {
    await show('2026.21');
    const groups = host.querySelector('#earmarks')!;
    expect(groups.textContent).toContain('ATL-412');
    expect(groups.textContent).toContain('Self-service 2.0');
  });

  it('a sprint without earmarks says so', async () => {
    await show('2026.22');
    expect(host.querySelector('#earmarks')!.textContent).toContain('Nothing earmarked for 2026.22 yet');
  });
});
