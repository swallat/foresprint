import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TimesPanel from './TimesPanel.svelte';
import type { Person } from '../../lib/types.team';

let host: HTMLElement;
let cmp: ReturnType<typeof mount> | undefined;
afterEach(() => {
  if (cmp) unmount(cmp);
  cmp = undefined;
  host?.remove();
});

const person = {
  id: 'paul',
  name: 'Paul',
  kind: 'member',
  production: false,
  country: '',
  region: '',
  used: true,
  memberships: [
    { from: '2024-12-11', to: '2026-04-28', fte: 1 },
    { from: '2026-04-29', to: '', fte: 0.4 },
  ],
} as unknown as Person;

describe('TimesPanel share', () => {
  it('applies a changed share typed with a decimal comma', async () => {
    host = document.createElement('div');
    document.body.append(host);
    const onsave = vi.fn();
    cmp = mount(TimesPanel, {
      target: host,
      props: { person, today: '2026-11-10', teamCountry: 'DE', absences: [], openFrom: '2026-01-01', onabsences: () => {}, onclose: () => {}, onsave, onremove: () => {} },
    });
    await tick();
    const fte = host.querySelector<HTMLInputElement>('input[aria-label="FTE of period 2"]')!;
    fte.value = '0';
    fte.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    const apply = [...host.querySelectorAll<HTMLButtonElement>('button.primary')].find((b) => /Apply/.test(b.textContent ?? ''))!;
    expect(apply.disabled).toBe(false);
    apply.click();
    expect(onsave).toHaveBeenCalled();
    expect(onsave.mock.calls[0]![0].memberships[1].fte).toBe(0);
  });
});
