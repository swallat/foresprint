import { describe, expect, it } from 'vitest';
import { mockApi } from '../mock';
import { withLists } from './model.svelte';
import type { PlanSprint } from '../types.plan';

describe('withLists', () => {
  it('turns the null lists of an answer into arrays', async () => {
    const d = await mockApi.PlanSprint('atlas', (await mockApi.Sprints('atlas'))[8]!.id, null);
    const nulls = {
      ...d, removed: null, tickets: null, candidates: null, projects: null, products: null, notes: null,
      assumptions: [{ label: 'A', commitment: null, carry: null, notDone: null, extra: null, restNext: null }],
      prod: d.prod ? { ...d.prod, people: null } : null,
    } as unknown as PlanSprint;
    const fixed = withLists(nulls);
    expect(fixed.tickets).toEqual([]);
    expect(fixed.removed).toEqual([]);
    expect(fixed.assumptions[0]!.carry).toEqual([]);
    if (fixed.prod) expect(fixed.prod.people).toEqual([]);
  });
});
