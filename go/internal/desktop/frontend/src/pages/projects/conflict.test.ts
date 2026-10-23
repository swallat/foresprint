import { describe, expect, it } from 'vitest';
import type { ProjectsView } from '../../lib/types.projects';
import { noteText } from './conflict';

const none = { kind: 'none', ticket: '', project: '', projectName: '', light: 'none', points: 0 } as const;

const view = {
  unit: 'SP',
  conflictSprint: '2026.22',
  products: [
    { id: 'a', name: 'Portal' },
    { id: 'b', name: 'Billing' },
  ],
  projects: [{ id: 'x', name: 'Self-Service' }],
  fit: [{ project: 'x', remaining: 4, need: 9.5, status: 'over', missing: 5.5 }],
  conflict: [
    { product: 'a', budget: 14, demand: [{ project: 'x', points: 13 }], rest: 1, light: 'warn', suggest: none },
    { product: 'b', budget: 8, demand: [], rest: 8, light: 'ok', suggest: none },
  ],
} as unknown as ProjectsView;

describe('noteText', () => {
  it('lists only the products that are tight or full', () => {
    const text = noteText(view, 'accept');
    expect(text).toContain('Portal');
    expect(text).toContain('Self-Service 13');
    expect(text).not.toContain('Billing');
  });

  it('lists a contingent that does not last', () => {
    const text = noteText(view, 'talk');
    expect(text).toContain('Self-Service: ');
    expect(text).toMatch(/5[.,]5/);
  });

  it('names the sprint in both notes', () => {
    expect(noteText(view, 'accept')).toContain('2026.22');
    expect(noteText(view, 'talk')).toContain('2026.22');
  });
});
