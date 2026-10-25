// The window and the browser page show the same data folder. The server watches it and tells
// every change (the window gets a Wails event, the browser page a server-sent event, both
// arrive as "foresprint:data" with a fingerprint). A change that is not the own view's work
// shows the page anew, so an absence entered in the browser is in the window a moment later.

import { api, ownCallRecent } from './api';
import { app, refreshSprints, refreshStatus } from './app.svelte';

interface WailsRuntime {
  EventsOn?: (name: string, cb: (...data: unknown[]) => void) => void;
}

/** Changes this soon after a call of this view are taken as its own. */
const GRACE_MS = 1500;
const EVENT = 'foresprint:data';

let known: string | undefined;
let pending = false;
let started = false;

const typing = (): boolean => {
  const el = document.activeElement;
  return !!el && !!el.closest('#main') && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
};

let lastFocusChange = 0;
let waiting: ReturnType<typeof setInterval> | undefined;

async function apply(): Promise<void> {
  pending = false;
  app.changed++;
  void refreshStatus();
  // The team list and the sprints of the other view's work (a team added, a sprint renamed).
  try {
    app.teams = await api.Teams();
    await refreshSprints();
  } catch {
    /* the page shows its own error */
  }
}

/** A change that came while someone was typing waits until the field is left, the focus has been
 * still for a second (a click on a button right after leaving the field must still land) and no
 * write of this view is running. */
function applyWhenQuiet(): void {
  pending = true;
  waiting ??= setInterval(() => {
    if (!pending) {
      clearInterval(waiting);
      waiting = undefined;
    } else if (!typing() && Date.now() - lastFocusChange > 1000 && !ownCallRecent(GRACE_MS)) {
      clearInterval(waiting);
      waiting = undefined;
      void apply();
    }
  }, 500);
}

/** The first fingerprint is the state when the view opened (known). The browser page's stream
 * starts with it (the bridge keeps it for a page that listens late); the Wails event has no
 * such first message, so there the first event already is a change. */
function onData(fp: string): void {
  if (known === undefined || fp === known) {
    known ??= fp;
    return;
  }
  known = fp;
  // Own work (a call a moment ago, a save, a sync) is not news.
  if (ownCallRecent(GRACE_MS) || app.busy || app.status.tracker.syncing) return;
  // Do not pull the page away from under someone who is typing.
  if (typing() || pending) applyWhenQuiet();
  else void apply();
}

/** Starts listening; safe to call twice. Does nothing in a plain browser without the program. */
export function watchData(): void {
  if (started) return;
  started = true;
  known = (window as unknown as { foresprintFingerprint?: string }).foresprintFingerprint;
  window.addEventListener(EVENT, (e) => onData(String((e as CustomEvent).detail)));
  const runtime = (window as unknown as { runtime?: WailsRuntime }).runtime;
  runtime?.EventsOn?.(EVENT, (fp) => {
    known ??= ''; // no baseline in the window: whatever arrives is news
    onData(String(fp));
  });
  window.addEventListener('focusout', () => {
    lastFocusChange = Date.now();
  });
}
