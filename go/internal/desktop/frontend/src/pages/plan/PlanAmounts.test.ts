// Plan page without tickets (mock "none"): the team types an amount per product and a commitment.
// Invalid or empty entries must not change anything and the field shows the stored value again.
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../../lib/mock';
import { app } from '../../lib/app.svelte';
import { resetPlanMock } from '../../lib/mock/plan';
import Plan from './Plan.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;

beforeEach(() => {
  resetPlanMock();
  app.toasts = [];
  history.replaceState(null, '', '/?mock=none');
});

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
  history.replaceState(null, '', '/');
  vi.restoreAllMocks();
});

async function show(): Promise<void> {
  app.team = 'atlas';
  app.sprint = '2026.21';
  host = document.createElement('div');
  document.body.append(host);
  cmp = mount(Plan, { target: host, props: { params: {} } });
  await vi.waitFor(() => expect(host.querySelector('#commit')).not.toBeNull(), { timeout: 3000 });
  await tick();
}

const commitInput = () => host.querySelector<HTMLInputElement>('#commit')!;
const amountInputs = () => [...host.querySelectorAll<HTMLInputElement>('input[aria-label^="Amount "]')];

function type(el: HTMLInputElement, text: string): void {
  el.value = text;
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('Plan page without tickets', () => {
  it('has no lanes, an amount field per product and a commitment that follows their sum', async () => {
    await show();
    expect(host.querySelector('#lanes')).toBeNull();
    const inputs = amountInputs();
    expect(inputs.length).toBeGreaterThan(0);
    const sum = inputs.reduce((a, e) => a + Number(e.value), 0);
    expect(Number(commitInput().value)).toBe(sum);
  });

  it('a typed amount (comma or dot) is taken and moves the commitment', async () => {
    await show();
    const first = amountInputs()[0]!;
    const others = amountInputs().slice(1).reduce((a, e) => a + Number(e.value), 0);
    type(first, '7,5');
    await tick();
    expect(first.value).toBe('7.5');
    expect(Number(commitInput().value)).toBe(7.5 + others);
  });

  it('a dot is taken like a comma, and a different spelling of the stored value is tidied up', async () => {
    await show();
    const first = amountInputs()[0]!;
    type(first, '4.5');
    await tick();
    expect(first.value).toBe('4.5');
    type(first, ' 4,50 ');
    await tick();
    expect(first.value).toBe('4.5');
  });

  it('an invalid amount is rejected and the field shows the stored value again', async () => {
    await show();
    const first = amountInputs()[0]!;
    const stored = first.value;
    const commitBefore = commitInput().value;
    type(first, 'abc');
    await tick();
    expect(first.value).toBe(stored);
    type(first, '-3');
    await tick();
    expect(first.value).toBe(stored);
    expect(commitInput().value).toBe(commitBefore);
  });

  it('an empty amount keeps the stored value', async () => {
    await show();
    const first = amountInputs()[0]!;
    const stored = first.value;
    type(first, '  ');
    await tick();
    expect(first.value).toBe(stored);
  });

  it('a typed commitment overrides the sum; an invalid one is rejected and restored', async () => {
    await show();
    type(commitInput(), '21');
    await tick();
    expect(commitInput().value).toBe('21');
    type(commitInput(), 'viel');
    await tick();
    expect(commitInput().value).toBe('21');
  });

  it('an empty commitment goes back to the sum of the amounts', async () => {
    await show();
    const sum = amountInputs().reduce((a, e) => a + Number(e.value), 0);
    type(commitInput(), '99');
    await tick();
    type(commitInput(), '');
    await tick();
    expect(commitInput().value).toBe(String(sum));
  });

  it('freezing records the typed amounts and commitment, and then locks the fields', async () => {
    await show();
    const freeze = vi.spyOn(mockApi, 'FreezePlan');
    type(commitInput(), '30');
    await tick();
    host.querySelector<HTMLButtonElement>('#freeze')!.click();
    await vi.waitFor(() => expect(host.querySelector('#frozen')).not.toBeNull(), { timeout: 3000 });
    expect(freeze).toHaveBeenCalledWith('atlas', '2026.21', expect.objectContaining({ tickets: [], commitment: 30 }));
    expect(commitInput().disabled).toBe(true);
    expect(amountInputs().every((e) => e.disabled)).toBe(true);
  });
});
