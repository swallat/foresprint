// Small pure helpers of the area Data (tested in util.test.ts).

import type { Conflict, ConflictEntry, Decision } from '../../lib/types.data';

/** A file of the history relative to the team folder: "teams/atlas/sprints/2026.22.yaml" -> "sprints/2026.22.yaml". */
export function shortFile(file: string, team: string): string {
  const parts = file.split('/');
  const i = team ? parts.indexOf(team) : -1;
  return i >= 0 ? parts.slice(i + 1).join('/') : file;
}

/** The word for the state of an unsaved file as git status writes it (M, D, A, ??, R). */
export function fileState(status: string): 'changed' | 'deleted' | 'new' | 'renamed' {
  const s = status.trim();
  if (s.startsWith('D')) return 'deleted';
  if (s.startsWith('A') || s === '??') return 'new';
  if (s.startsWith('R')) return 'renamed';
  return 'changed';
}

/** Identifies one value of a conflict, for the choices kept by the page. */
export function entryKey(file: string, entry: Pick<ConflictEntry, 'path'>): string {
  return [file, ...entry.path].join('\u0000');
}

/** All entries of all conflicts, in order. */
export function allEntries(conflicts: Conflict[]): { file: string; entry: ConflictEntry }[] {
  return conflicts.flatMap((c) => c.entries.map((entry) => ({ file: c.file, entry })));
}

/** How many entries still lack a decision. */
export function openCount(conflicts: Conflict[], choices: Record<string, 'ours' | 'theirs'>): number {
  return allEntries(conflicts).filter(({ file, entry }) => !choices[entryKey(file, entry)]).length;
}

/** The decisions to send, one per decided entry. */
export function decisionsOf(conflicts: Conflict[], choices: Record<string, 'ours' | 'theirs'>): Decision[] {
  const out: Decision[] = [];
  for (const { file, entry } of allEntries(conflicts)) {
    const choice = choices[entryKey(file, entry)];
    if (choice) out.push({ file, path: entry.path, choice });
  }
  return out;
}
