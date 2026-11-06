// The chart series can be switched on and off in the legend; the choice is kept.
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mockApi } from '../../lib/mock';
import type { ForecastView } from '../../lib/types.forecast';
import ForecastChart from './ForecastChart.svelte';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;
let view: ForecastView;

beforeEach(async () => {
  localStorage.clear();
  view = await mockApi.Forecast('atlas');
  host = document.createElement('div');
  document.body.append(host);
});

afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host.remove();
  localStorage.clear();
});

const show = async () => {
  cmp = mount(ForecastChart, { target: host, props: { past: view.past, upcoming: view.upcoming } });
  await tick();
};
const button = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('button.lg')].find((b) => b.textContent?.includes(name))!;
const polylines = (cls: string) => host.querySelectorAll(`polyline.${cls}`).length;

// The formulas are drawn as MathML; the plain text is the aria-label of each one.
const labels = () => [...document.querySelectorAll('.paths .formula')].map((e) => e.getAttribute('aria-label') ?? e.textContent).join('\n');

describe('ForecastChart legend', () => {
  it('shows fulfillment only after it is switched on, on its own axis', async () => {
    await show();
    expect(button('Fulfillment').getAttribute('aria-pressed')).toBe('false');
    expect(polylines('ful')).toBe(0);
    button('Fulfillment').click();
    await tick();
    expect(button('Fulfillment').getAttribute('aria-pressed')).toBe('true');
    expect(polylines('ful')).toBe(1);
    expect(host.textContent).toContain('100 %');
  });

  it('shows the commitment line only after it is switched on, on the point axis', async () => {
    await show();
    expect(polylines('com')).toBe(0);
    button('Commitment').click();
    await tick();
    expect(polylines('com')).toBe(1);
    expect(host.querySelectorAll('circle.o.com').length).toBeGreaterThan(1);
  });

  it('switches a series off and back on', async () => {
    await show();
    expect(polylines('vel')).toBe(1);
    button('Velocity').click();
    await tick();
    expect(polylines('vel')).toBe(0);
    expect(button('Velocity').getAttribute('aria-pressed')).toBe('false');
    button('Velocity').click();
    await tick();
    expect(polylines('vel')).toBe(1);
  });

  it('keeps the choice for the next visit', async () => {
    await show();
    button('Fulfillment').click();
    await tick();
    unmount(cmp!);
    cmp = undefined;
    host.replaceChildren();
    await show();
    expect(button('Fulfillment').getAttribute('aria-pressed')).toBe('true');
  });
});

describe('ForecastChart calculation paths', () => {
  const names = () => [...host.querySelectorAll('.paths dt')].map((e) => e.textContent?.trim());
  it('lists the symbolic path of every series that is shown', async () => {
    await show();
    expect(host.querySelector('.paths')).not.toBeNull();
    expect(names().length).toBe(5);
    expect(labels()).not.toContain("P'");
    expect(labels()).toContain('P = ⌊ T ÷ Ref × Cap ⌋');
    expect(labels()).not.toContain('F = V ÷ C');
  });
  it('follows the legend', async () => {
    await show();
    button('Fulfillment').click();
    await tick();
    expect(labels()).toContain('F = V ÷ C');
    button('Forecast PLAN').click();
    await tick();
    expect(labels()).not.toContain('P = ⌊ T ÷ Ref × Cap ⌋');
  });
  it('disappears when every series is off', async () => {
    await show();
    for (const b of host.querySelectorAll<HTMLButtonElement>('button.lg[aria-pressed="true"]')) b.click();
    await tick();
    expect(host.querySelector('.paths')).toBeNull();
  });
});
