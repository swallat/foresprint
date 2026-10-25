import { describe, expect, it } from 'vitest';
import { derivePattern, isDay, joinPath, needsToken, repoName, suggestedSprintId, suggestedStart } from './setup';

describe('setup helpers', () => {
  it('names the clone folder after the repository', () => {
    expect(repoName('https://git.example.com/planung/atlas-daten.git')).toBe('atlas-daten');
    expect(repoName('git@git.example.com:planung/atlas daten/')).toBe('atlas-daten');
    expect(repoName('')).toBe('foresprint-data');
  });
  it('joins with the separator of the system', () => {
    expect(joinPath('C:\\Planung\\', 'daten', 'windows')).toBe('C:\\Planung\\daten');
    expect(joinPath('/home/anna/', 'daten', 'linux')).toBe('/home/anna/daten');
  });
  it('asks for a token only for https', () => {
    expect(needsToken(' https://git.example.com/x.git')).toBe(true);
    expect(needsToken('git@git.example.com:x.git')).toBe(false);
  });
  it('suggests the Monday of the week and a sprint ID', () => {
    expect(suggestedStart(new Date(2026, 9, 22))).toBe('2026-10-19'); // Thursday
    expect(suggestedStart(new Date(2026, 9, 25))).toBe('2026-10-19'); // Sunday
    expect(suggestedSprintId('2026-10-19')).toBe('2026.21');
    expect(suggestedSprintId('2026-01-05')).toBe('2026.1');
  });
  it('checks dates', () => {
    expect(isDay('2026-02-28')).toBe(true);
    expect(isDay('2026-02-30')).toBe(false);
    expect(isDay('28.10.2026')).toBe(false);
  });
});

describe('derivePattern', () => {
  it('reads the pattern out of a free first sprint name', () => {
    expect(derivePattern('Team Sprint 2026.16', '2026-10-20')).toBe('Team Sprint {JJJJ}.{N}');
    expect(derivePattern('Sprint 2026.07', '2026-03-02')).toBe('Sprint {JJJJ}.{NN}');
    expect(derivePattern('Lauf 7', '2026-10-20')).toBe('Lauf {LFD}');
  });
  it('needs no pattern for a plain ID or a name without a number', () => {
    expect(derivePattern('2026.22', '2026-10-20')).toBe('');
    expect(derivePattern('Refinement', '2026-10-20')).toBe('');
  });
});
