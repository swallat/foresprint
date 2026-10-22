import { describe, expect, it } from 'vitest';
import { commandsFor, registerCommands, score, type Command } from './commands';

const cmd = (label: string, extra: Partial<Command> = {}): Command => ({ id: label, label, group: 'action', run: () => {}, ...extra });

describe('score', () => {
  it('matches every word anywhere in label, words or hint', () => {
    expect(score(cmd('Save and share', { words: 'speichern' }), 'speich')).toBeGreaterThan(0);
    expect(score(cmd('Save and share'), 'share save')).toBeGreaterThan(0);
    expect(score(cmd('Save and share'), 'forecast')).toBe(0);
  });
  it('ranks exact, prefix and word-start above a plain hit', () => {
    const c = cmd('Forecast');
    expect(score(c, 'forecast')).toBeGreaterThan(score(c, 'fore'));
    expect(score(c, 'fore')).toBeGreaterThan(score(cmd('The forecast'), 'fore'));
    expect(score(cmd('The forecast'), 'fore')).toBeGreaterThan(score(cmd('Unforeseen'), 'fore'));
  });
});

describe('commandsFor', () => {
  it('lists pages and actions', () => {
    const all = commandsFor('', 100);
    expect(all.some((c) => c.group === 'page' && c.hint === '/today')).toBe(true);
    expect(all.some((c) => c.id === 'act:save')).toBe(true);
  });
  it('asks registered sources with the query and lets them be removed', () => {
    const seen: string[] = [];
    const off = registerCommands((q) => {
      seen.push(q);
      return [cmd('ATL-1 Login page', { id: 'ticket:ATL-1', group: 'ticket' })];
    });
    expect(commandsFor('login').some((c) => c.id === 'ticket:ATL-1')).toBe(true);
    expect(seen).toContain('login');
    off();
    expect(commandsFor('login').some((c) => c.id === 'ticket:ATL-1')).toBe(false);
  });
  it('keeps the limit', () => {
    expect(commandsFor('', 3)).toHaveLength(3);
  });
});
