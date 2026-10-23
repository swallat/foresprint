import { describe, expect, it } from 'vitest';
import { match } from '../router.svelte';
import { pages } from '../routes';
import { flowById, flows } from './flows';
import { pickSprint } from './tour.svelte';

const sprints = [
  { id: 'a', state: 'past' },
  { id: 'b', state: 'current' },
  { id: 'c', state: 'future' },
  { id: 'd', state: 'future' },
];

describe('flows', () => {
  it('have unique ids and at least one step', () => {
    expect(new Set(flows.map((f) => f.id)).size).toBe(flows.length);
    for (const f of flows) expect(f.steps.length, f.id).toBeGreaterThan(0);
  });
  it('lead to existing pages', () => {
    for (const f of flows) {
      for (const s of f.steps) expect(pages.some((p) => match(p.path, s.route) !== undefined), `${f.id} ${s.route}`).toBe(true);
    }
  });
  it('keep a walk-through for a team without a tracker', () => {
    for (const f of flows) {
      const rest = f.withoutTracker ?? f.steps.filter((s) => !s.trackerOnly);
      expect(rest.length, f.id).toBeGreaterThan(0);
      for (const s of rest) expect(pages.some((p) => match(p.path, s.route) !== undefined), `${f.id} ${s.route}`).toBe(true);
    }
  });
  it('give queries as plain text pairs', () => {
    for (const f of flows) {
      for (const s of [...f.steps, ...(f.withoutTracker ?? [])]) {
        for (const [k, v] of Object.entries(s.query ?? {})) expect(`${k}=${v}`, f.id).toMatch(/^[a-z]+=[a-z0-9-]+$/);
      }
    }
    expect(flows.some((f) => f.steps.some((s) => s.query?.tab === 'when'))).toBe(true);
  });
  it('mark elements by data-tour name', () => {
    for (const f of flows) {
      for (const s of f.steps) if (s.target) expect(s.target, f.id).toMatch(/^\[data-tour="[a-z0-9-]+"\]$/);
    }
  });
  it('are found by id', () => {
    expect(flowById('F4')?.id).toBe('F4');
    expect(flowById('nope')).toBeUndefined();
  });
});

describe('pickSprint', () => {
  it('takes the running sprint and the next one', () => {
    expect(pickSprint('running', sprints)).toBe('b');
    expect(pickSprint('next', sprints)).toBe('c');
  });
  it('returns "" if there is none', () => {
    expect(pickSprint('running', [])).toBe('');
  });
});
