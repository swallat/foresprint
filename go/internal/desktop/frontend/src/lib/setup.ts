// Small helpers of the first-start wizard (pages/today/FirstRun.svelte), kept apart so that they
// can be tested.

/** The folder name a repository gets when cloned: the last part of the address without ".git". */
export function repoName(address: string): string {
  const clean = address.trim().replace(/[/\\]+$/, '').replace(/\.git$/, '');
  const last = clean.split(/[/:\\]/).pop() ?? '';
  const name = last.replace(/[^\w.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
  return name || 'foresprint-data';
}

/** Joins a folder and a name with the separator of the system. */
export function joinPath(folder: string, name: string, os: string): string {
  const sep = os === 'windows' ? '\\' : '/';
  return `${folder.replace(/[/\\]+$/, '')}${sep}${name}`;
}

/** Whether an address is one a token can be used with (https). */
export function needsToken(address: string): boolean {
  return /^https:\/\//i.test(address.trim());
}

/** A start date for the first sprint: the Monday of this week as YYYY-MM-DD. */
export function suggestedStart(today = new Date()): string {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** A sprint ID for the first sprint with two-week sprints: the year and the count so far, "2026.22". */
export function suggestedSprintId(start: string): string {
  const [y = 1970, m = 1, d = 1] = start.split('-').map(Number);
  const dayOfYear = Math.floor((Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 86400000);
  return `${y}.${Math.floor(dayOfYear / 14) + 1}`;
}

/** Whether a string is a date YYYY-MM-DD that exists. */
export function isDay(text: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

/** Whether an address may be remembered in the draft: no user info, query or fragment, which could hold a secret. */
export function safeToStore(address: string): boolean {
  const a = address.trim();
  if (/[?#]/.test(a)) return false;
  const rest = a.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '');
  return !rest.split('/')[0]?.includes('@') || !/^[a-z][a-z0-9+.-]*:\/\//i.test(a);
}
