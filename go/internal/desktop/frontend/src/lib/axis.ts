/** Drops the prefix all names share ("Team Sprint 41", "Team Sprint 42" -> "41", "42"), cutting only after a separator. */
export function shortNames(ids: string[]): string[] {
  const first = ids[0];
  if (first === undefined || ids.length < 2) return ids;
  let n = 0;
  while (n < first.length && ids.every((id) => id[n] === first[n])) n++;
  let cut = 0;
  for (let i = 0; i < n; i++) if (/[\s\-_.:/]/.test(first[i] ?? '')) cut = i + 1;
  const trimmed = ids.map((id) => (id.length > cut ? id.slice(cut) : id));
  // Some names carry the prefix and some do not ("2026.10" next to "Team Sprint 2026.22"): fall back to the last word.
  const last = trimmed.map((id) => id.split(/\s+/).at(-1) ?? id);
  return trimmed.some((id) => /\s/.test(id)) && new Set(last).size === last.length ? last : trimmed;
}
