import { describe, expect, it } from 'vitest';
import type { BacklogTicket, BacklogView } from '../../lib/types.backlog';
import { activeView, applyView, blank, group, matches, neighbour, sum, unassigned } from './backlog';

const t = (key: string, o: Partial<BacklogTicket> = {}): BacklogTicket => ({
  key, title: `Title ${key}`, status: '', type: '', priority: '', assignee: '', url: '', size: 3, sizeSource: 'refined',
  refined: true, refinedUnclear: false, product: 'a', project: '', productSet: false, projectSet: false, earmark: '',
  trackerSprint: '', production: null, epic: '', labels: [], dependsOn: [], blocked: false, ...o,
});
const names = { product: (id: string) => (id === 'a' ? 'Alpha' : id), project: (id: string) => (id === 'p' ? 'Relaunch' : 'Daily') };
const view = { products: [{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }], projects: [{ id: 'p', name: 'Relaunch' }] } as BacklogView;

describe('filter', () => {
  it('matches words in key, title, product and project', () => {
    const f = { ...blank(), q: 'alpha title' };
    expect(matches(t('X-1'), f, names, true)).toBe(true);
    expect(matches(t('X-1', { product: 'b' }), f, names, true)).toBe(false);
  });
  it('keeps daily business apart from projects', () => {
    const f = { ...blank(), projects: [''] };
    expect(matches(t('X-1'), f, names, true)).toBe(true);
    expect(matches(t('X-2', { project: 'p' }), f, names, true)).toBe(false);
  });
  it('filters by refined state', () => {
    expect(matches(t('X-1', { refined: false }), { ...blank(), refined: 'open' }, names, true)).toBe(true);
    expect(matches(t('X-1'), { ...blank(), refined: 'open' }, names, true)).toBe(false);
  });
  it('knows unassigned tickets', () => {
    expect(unassigned(t('X-1', { ruleHint: 'none' }), true)).toBe(true);
    expect(unassigned(t('X-1', { product: '' }), true)).toBe(true);
    expect(unassigned(t('X-1', { product: '' }), false)).toBe(false);
  });
});

describe('saved views', () => {
  it('recognises the view of a filter and keeps the search text', () => {
    expect(activeView(blank())).toBe('all');
    expect(activeView(applyView('refinement', 'abc'))).toBe('refinement');
    expect(applyView('daily', 'abc').q).toBe('abc');
    expect(activeView({ ...blank(), products: ['a'] })).toBe('');
  });
});

describe('group and sum', () => {
  it('sums sizes, an unestimated ticket counts 0', () => {
    expect(sum([t('A-1'), t('A-2', { size: null }), t('A-3', { size: 5 })])).toBe(8);
  });
  it('groups by project with daily business last and drops empty groups', () => {
    const g = group([t('A-1'), t('A-2', { project: 'p' })], 'project', view);
    expect(g.map((s) => s.id)).toEqual(['p', '']);
    expect(group([t('A-1')], 'product', view).map((s) => s.id)).toEqual(['a']);
    expect(group([t('A-1')], 'none', view)).toEqual([]);
  });
});

describe('neighbour', () => {
  const lanes = ['1', '2', '3'];
  it('steps through the lanes and back to the backlog', () => {
    expect(neighbour(lanes, '', 1)).toBe('1');
    expect(neighbour(lanes, '1', 1)).toBe('2');
    expect(neighbour(lanes, '3', 1)).toBeUndefined();
    expect(neighbour(lanes, '1', -1)).toBe('');
    expect(neighbour(lanes, '', -1)).toBeUndefined();
  });
});

import { localTerms } from './terms';

describe('localTerms', () => {
  it('speaks of work packages without a tracker, in both languages', () => {
    expect(localTerms('No ticket fits. 3 tickets.', 'packages', 'en')).toBe('No work package fits. 3 work packages.');
    expect(localTerms('Kein Ticket passt. 3 Tickets.', 'packages', 'de')).toBe('Kein Arbeitspaket passt. 3 Arbeitspakete.');
  });
  it('leaves tracker teams alone', () => {
    expect(localTerms('3 tickets', 'tracker', 'en')).toBe('3 tickets');
    expect(localTerms('3 tickets', undefined, 'de')).toBe('3 tickets');
  });
});
