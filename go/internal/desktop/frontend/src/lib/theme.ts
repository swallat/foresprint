// The theme: "system" follows the operating system (prefers-color-scheme in tokens.css), "light"
// and "dark" set data-theme on <html>.

export type Theme = 'system' | 'light' | 'dark';

export function applyTheme(theme: string): void {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') root.dataset.theme = theme;
  else delete root.dataset.theme;
}
