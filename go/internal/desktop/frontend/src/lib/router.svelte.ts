// A small hash router: addresses look like #/projects/atlas?tab=milestones. The route table is
// routes.ts; this file only matches and navigates.

export interface Route {
  path: string;
  params: Record<string, string>;
  query: Record<string, string>;
}

export function parseHash(hash: string): { path: string; query: Record<string, string> } {
  const raw = hash.replace(/^#/, '') || '/';
  const [pathPart = '/', queryPart = ''] = raw.split('?', 2);
  const path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  const query: Record<string, string> = {};
  new URLSearchParams(queryPart).forEach((v, k) => {
    query[k] = v;
  });
  return { path: path.length > 1 ? path.replace(/\/+$/, '') : path, query };
}

/** Matches "/projects/atlas" against "/projects/:id"; undefined if it does not match. */
export function match(pattern: string, path: string): Record<string, string> | undefined {
  const p = pattern.split('/');
  const a = path.split('/');
  if (p.length !== a.length) return undefined;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    const seg = p[i] ?? '';
    const got = a[i] ?? '';
    if (seg.startsWith(':')) params[seg.slice(1)] = decodeURIComponent(got);
    else if (seg !== got) return undefined;
  }
  return params;
}

const initial = parseHash(location.hash);
export const current = $state<Route>({ path: initial.path, params: {}, query: initial.query });

window.addEventListener('hashchange', () => {
  const next = parseHash(location.hash);
  current.path = next.path;
  current.query = next.query;
});

/** The address of a page, for links: href={link('/projects/:id', { id })}. */
export function link(pattern: string, params: Record<string, string> = {}, query: Record<string, string> = {}): string {
  const path = pattern.replace(/:(\w+)/g, (_, name: string) => encodeURIComponent(params[name] ?? ''));
  const q = new URLSearchParams(query).toString();
  return `#${path}${q ? `?${q}` : ''}`;
}

export function go(pattern: string, params?: Record<string, string>, query?: Record<string, string>): void {
  location.hash = link(pattern, params, query);
}

/** True once when the page was opened with "?new=1" (the plus menu); the flag is removed from the address. */
export function takeNew(): boolean {
  if (current.query.new !== '1') return false;
  current.query = {};
  location.replace(link(current.path));
  return true;
}
