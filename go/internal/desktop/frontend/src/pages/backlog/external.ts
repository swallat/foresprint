// Opens an address outside the window (the ticket in the tracker). In the program Wails'
// runtime opens the system browser; in a browser (development) a new tab opens.

interface WailsRuntime {
  BrowserOpenURL?: (url: string) => void;
}

export function openExternal(url: string): void {
  const runtime = (window as unknown as { runtime?: WailsRuntime }).runtime;
  if (runtime?.BrowserOpenURL) runtime.BrowserOpenURL(url);
  else window.open(url, '_blank', 'noopener');
}
