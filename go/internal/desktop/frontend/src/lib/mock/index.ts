// Answers for a browser without the program (npm run dev, tests) and for the demo team: the
// invented demo team "Team Atlas" (no real data, no real names). Same methods as the Go API.
//
// One file per area; this file only collects them (add a file here only for a new area).

import type { Api } from '../api';
import backlog from './backlog';
import core from './core';
import data from './data';
import forecast from './forecast';
import help from './help';
import plan from './plan';
import projects from './projects';
import review from './review';
import settings from './settings';
import setup from './setup';
import sprints from './sprints';
import team from './team';
import today from './today';

export const mockApi = {
  ...backlog,
  ...core,
  ...data,
  ...forecast,
  ...help,
  ...plan,
  ...projects,
  ...review,
  ...settings,
  ...setup,
  ...sprints,
  ...team,
  ...today,
} as Api;
