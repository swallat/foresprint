// The browser access (the program shown as a page of the browser): shared by the top bar menu and
// the page Settings > Browser. Not offered inside the browser page itself.

import { api } from './api';
import { toast } from './app.svelte';
import { t } from './i18n.svelte';
import type { BrowserInfo } from './types.settings';

/** True when this page already is the browser page (the bridge of the server sets it). */
export const inBrowserPage = (window as unknown as { foresprintWeb?: boolean }).foresprintWeb === true;

export const browser = $state<BrowserInfo>({ available: false, running: false, url: '' });

function take(info: BrowserInfo): void {
  Object.assign(browser, info);
}

export async function loadBrowser(): Promise<void> {
  if (inBrowserPage) return;
  try {
    take(await api.BrowserState());
  } catch {
    take({ available: false, running: false, url: '' });
  }
}

export async function openInBrowser(): Promise<void> {
  try {
    take(await api.BrowserOpen());
  } catch (e) {
    toast(String(e), 'bad');
  }
}

export async function copyBrowserLink(): Promise<void> {
  try {
    const info = await api.BrowserStart();
    take(info);
    await navigator.clipboard.writeText(info.url);
    toast(t('Link copied. It only works on this computer.'), 'ok');
  } catch (e) {
    toast(String(e), 'bad');
  }
}

export async function stopBrowser(): Promise<void> {
  try {
    take(await api.BrowserStop());
  } catch (e) {
    toast(String(e), 'bad');
  }
}
