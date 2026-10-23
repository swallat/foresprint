/** Drops the prefix all names share ("Team Sprint 41", "Team Sprint 42" -> "41", "42"), cutting only after a separator. */
export function shortNames(ids: string[]): string[] {
  const first = ids[0];
  if (first === undefined || ids.length < 2) return ids;
  let n = 0;
  while (n < first.length && ids.every((id) => id[n] === first[n])) n++;
  let cut = 0;
  for (let i = 0; i < n; i++) if (/[\s\-_.:/]/.test(first[i] ?? '')) cut = i + 1;
  return ids.map((id) => (id.length > cut ? id.slice(cut) : id));
}
