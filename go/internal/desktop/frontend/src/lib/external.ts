// Opens an address in the browser of the system. In the program that is the Wails runtime (the
// web view must not navigate away); in a browser (npm run dev) it is a new tab.

interface WailsRuntime {
  BrowserOpenURL?: (url: string) => void;
}

export function openExternal(url: string): void {
  if (!/^https?:\/\//i.test(url)) return;
  const runtime = (window as unknown as { runtime?: WailsRuntime }).runtime;
  if (runtime?.BrowserOpenURL) runtime.BrowserOpenURL(url);
  else window.open(url, '_blank', 'noopener');
}
