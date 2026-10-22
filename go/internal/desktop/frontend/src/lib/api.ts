// The bridge to the Go core. In the program, Wails injects window.go.app.API (the methods of
// go/internal/app.API); in a browser (npm run dev, tests) a mock with the demo team answers.
//
// To add a method: add it to the Go struct (internal/app/api_<area>.go), add its signature to
// `Api` below (or to an area interface that extends it) and an answer to the mock.

import type { BacklogApi } from './types.backlog';
import type { ForecastApi } from './types.forecast';
import type { Info, Prefs, Result, SprintInfo, Status, TeamSummary } from './types';
import type { DataApi } from './types.data';
import type { TodayApi } from './types.today';

export interface Api extends BacklogApi, DataApi, TodayApi, ForecastApi {
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

async function resolve(): Promise<Api> {
  if (!impl) {
    // The mock is part of the bundle only in development and in the "mock" build (screenshots,
    // tests); in the program the bridge always exists.
    if (!(import.meta.env.DEV || import.meta.env.MODE === 'mock')) throw new Error('api: no connection to the program');
    impl = (await import('./mock')).mockApi;
  }
  return impl;
}

/** Calls through to the core; every method is async because Wails calls are. */
export const api: Api = new Proxy({} as Api, {
  get:
    (_, method: string) =>
    async (...args: unknown[]) => {
      const target = (await resolve()) as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>;
      const fn = target[method];
      if (!fn) throw new Error(`api: unknown method ${method}`);
      return fn.apply(target, args);
    },
});
