// The timeline range is a personal choice that is kept for the next start (this machine only).

import type { Range } from './timeline';

const KEY = 'foresprint.projects.range';

export function loadRange(): { range: Range; customTo: string } {
  try {
    const [range, to = ''] = (localStorage.getItem(KEY) ?? '').split('|');
    if (range === '2' || range === '3' || range === '6' || range === 'all' || range === 'custom') return { range, customTo: to };
  } catch {
    /* blocked storage: use the default */
  }
  return { range: 'all', customTo: '' };
}

export function saveRange(range: Range, customTo: string): void {
  try {
    localStorage.setItem(KEY, `${range}|${customTo}`);
  } catch {
    /* blocked storage: the choice is not remembered */
  }
}
