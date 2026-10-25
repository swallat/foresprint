// The theme: "system" follows the operating system (prefers-color-scheme in tokens.css), "light"
// and "dark" set data-theme on <html>.

export type Theme = 'system' | 'light' | 'dark';

export function applyTheme(theme: string): void {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') root.dataset.theme = theme;
  else delete root.dataset.theme;
}

let densityStyle: HTMLStyleElement | undefined;

/** Row height of tables and lists: "compact", "normal" or "roomy" (personal setting). */
export function applyDensity(density: string): void {
  const height = { compact: 26, normal: 32, roomy: 40 }[density] ?? 32;
  densityStyle ??= document.head.appendChild(document.createElement('style'));
  densityStyle.textContent = `table.t th, table.t td { height: ${height}px; } .ticket { min-height: ${height + 4}px; }`;
}

interface FeatureFlags {
  source: string;
  products: boolean;
  po: boolean;
  production: boolean;
}

/** Sets the attributes that hide what a team does not use (see base.css: data-trk, data-prodshare,
 * data-multiprod, data-multipo). Without features everything stays visible. */
export function applyFeatures(features: FeatureFlags | undefined): void {
  const root = document.documentElement;
  if (!features) {
    for (const k of ['trk', 'prodshare', 'multiprod', 'multipo']) delete root.dataset[k];
    return;
  }
  root.dataset.trk = { tracker: 'jira', packages: 'local', none: 'none' }[features.source] ?? 'jira';
  root.dataset.prodshare = features.production ? 'on' : 'off';
  root.dataset.multiprod = features.products ? 'on' : 'off';
  root.dataset.multipo = features.po ? 'on' : 'off';
}
