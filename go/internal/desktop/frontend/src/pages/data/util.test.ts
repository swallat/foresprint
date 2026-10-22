import { describe, expect, it } from 'vitest';
import type { Conflict } from '../../lib/types.data';
import { decisionsOf, entryKey, fileState, openCount, shortFile } from './util';

const entry = (path: string[]) => ({ path, label: path.join('/'), mine: '1', theirs: '2', mineMissing: false, theirsMissing: false, before: '0', hasBefore: true });
const conflicts: Conflict[] = [
  { file: 'teams/atlas/absences.yaml', whole: false, mineDeleted: false, theirsDeleted: false, entries: [entry(['a']), entry(['b'])] },
  { file: 'teams/atlas/team.yaml', whole: true, mineDeleted: false, theirsDeleted: false, entries: [entry([])] },
];

describe('data helpers', () => {
  it('shortens files to the team folder', () => {
    expect(shortFile('teams/atlas/sprints/2026.22.yaml', 'atlas')).toBe('sprints/2026.22.yaml');
    expect(shortFile('atlas/people.yaml', 'atlas')).toBe('people.yaml');
    expect(shortFile('teams/other/people.yaml', 'atlas')).toBe('teams/other/people.yaml');
    expect(shortFile('teams/atlas2/people.yaml', 'atlas')).toBe('teams/atlas2/people.yaml');
    expect(shortFile('x.yaml', '')).toBe('x.yaml');
  });

  it('names the state of an unsaved file', () => {
    expect(fileState(' M')).toBe('changed');
    expect(fileState('??')).toBe('new');
    expect(fileState('A')).toBe('new');
    expect(fileState('D')).toBe('deleted');
    expect(fileState('R')).toBe('renamed');
  });

  it('counts open entries and builds the decisions', () => {
    const choices: Record<string, 'ours' | 'theirs'> = {};
    expect(openCount(conflicts, choices)).toBe(3);
    choices[entryKey('teams/atlas/absences.yaml', { path: ['a'] })] = 'ours';
    choices[entryKey('teams/atlas/team.yaml', { path: [] })] = 'theirs';
    expect(openCount(conflicts, choices)).toBe(1);
    expect(decisionsOf(conflicts, choices)).toEqual([
      { file: 'teams/atlas/absences.yaml', path: ['a'], choice: 'ours' },
      { file: 'teams/atlas/team.yaml', path: [], choice: 'theirs' },
    ]);
  });
});
