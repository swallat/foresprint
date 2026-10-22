// The bridge to the Go core. In the program, Wails injects window.go.app.API (the methods of
// go/internal/app.API); in a browser (npm run dev, tests) a mock with the demo team answers.
//
// To add a method: add it to the Go struct (internal/app/api_<area>.go), add its signature to
// `Api` below (or to an area interface that extends it) and an answer to the mock.

import type { Info, Prefs, Result, SprintInfo, Status, TeamSummary } from './types';
import type { SetupApi } from './types.setup';
import type { TodayApi } from './types.today';

export interface Api extends TodayApi, SetupApi {
  Info(): Promise<Info>;
  Prefs(): Promise<Prefs>;
  SetLanguage(code: string): Promise<void>;
  SetTheme(code: string): Promise<void>;
  Texts(lang: string): Promise<Record<string, string>>;
  SetDataDir(path: string): Promise<void>;
  PickDataDir(): Promise<string>;
  Teams(): Promise<TeamSummary[]>;
  Sprints(team: string): Promise<SprintInfo[]>;
  Status(): Promise<Status>;
  Save(): Promise<Result>;
  Refresh(): Promise<Result>;
  SyncTracker(): Promise<Result>;
}

interface WailsWindow {
  go?: { app?: { API?: Api } };
}

const bridge = (window as unknown as WailsWindow).go?.app?.API;

/** True inside the program, false in a browser with the mock. */
export const inProgram = bridge !== undefined;

let impl: Api | undefined = bridge;
let mock: Api | undefined;
let demo = false;

/** Methods about this person and this machine: they never go to the demo team. */
const personal = new Set(['Info', 'Prefs', 'SetLanguage', 'SetTheme', 'Texts', 'PickFolder', 'PickDataDir']);

/**
 * Switches every call about team data to the invented demo team (Team Atlas) that the mock
 * answers, in the program too. Nothing reaches the data folder while it is on.
 */
export function setDemo(on: boolean): void {
  demo = on;
}

export function isDemo(): boolean {
  return demo;
}

async function loadMock(): Promise<Api> {
  mock ??= (await import('./mock')).mockApi;
  return mock;
}

async function resolve(method: string): Promise<Api> {
  if (demo && !personal.has(method)) return loadMock();
  if (!impl) {
    // The mock is part of the bundle for the demo team and for the browser (npm run dev, tests);
    // in the program the bridge always exists.
    if (!(import.meta.env.DEV || import.meta.env.MODE === 'mock')) throw new Error('api: no connection to the program');
    impl = await loadMock();
  }
  return impl;
}

/** Calls through to the core; every method is async because Wails calls are. */
export const api: Api = new Proxy({} as Api, {
  get:
    (_, method: string) =>
    async (...args: unknown[]) => {
      const target = (await resolve(method)) as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>;
      const fn = target[method];
      if (!fn) throw new Error(`api: unknown method ${method}`);
      return fn.apply(target, args);
    },
});
