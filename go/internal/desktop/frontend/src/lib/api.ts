// The bridge to the Go core. In the program, Wails injects window.go.app.API (the methods of
// go/internal/app.API); in a browser (npm run dev, tests) a mock with the demo team answers.
//
// To add a method: add it to the Go struct (internal/app/api_<area>.go), add its signature to
// the interface of its area (types.<area>.ts) and an answer to the mock of the area
// (mock/<area>.ts).

import type { BacklogApi } from './types.backlog';
import type { ForecastApi } from './types.forecast';
import type { HelpApi } from './types.help';
import type { SettingsApi } from './types.settings';
import type { TeamApi } from './types.team';
import type { Info, Prefs, Result, SprintInfo, Status, TeamSummary } from './types';
import type { PlanApi } from './types.plan';
import type { DataApi } from './types.data';
import type { ProjectsApi } from './types.projects';
import type { ReviewApi } from './types.review';
import type { SetupApi } from './types.setup';
import type { SprintsApi } from './types.sprints';
import type { TodayApi } from './types.today';

// One interface per area (types.<area>.ts); only the methods of the shell are listed here.
export interface Api
  extends BacklogApi, DataApi, ForecastApi, HelpApi, PlanApi, ProjectsApi, ReviewApi, SettingsApi, SetupApi, SprintsApi, TeamApi, TodayApi {
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
  /** Writes Team Atlas into a throwaway folder and works on it until LeaveDemo; returns its key. */
  EnterDemo(lang: string): Promise<string>;
  LeaveDemo(): Promise<void>;
  InDemo(): Promise<boolean>;
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
const personal = new Set(['Info', 'Prefs', 'UpdateStatus', 'CheckUpdate', 'InstallUpdate', 'SetUpdateMode', 'SetLanguage', 'SetTheme', 'Texts', 'PickFolder', 'PickDataDir']);

/**
 * Calls the wizard makes while the demo is on: they are only pretended (the mock answers), so
 * that nothing is cloned or remembered. Everything else about the demo team goes to the core.
 */
const pretended = /^Setup/;

/**
 * Marks the demo as on. In the program the core serves Team Atlas from a throwaway folder
 * (EnterDemo); in a browser the mock answers every call about team data. Nothing reaches the
 * data folder while it is on.
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
  if (demo && !personal.has(method) && (!inProgram || pretended.test(method))) return loadMock();
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
