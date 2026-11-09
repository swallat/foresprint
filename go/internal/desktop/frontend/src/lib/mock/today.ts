// Browser answers for the start page (Today) of the demo team.

import type { Api } from '../api';
import type { TodayData, TodaySprint } from '../types.today';
import type { SprintInfo } from '../types';
import { sprints } from './shared';

const muted = new Set<string>();

function today(): TodayData {
  const day = new Date().toISOString().slice(0, 10);
  const at = Math.max(0, sprints.findIndex((s) => s.state === 'current'));
  const left = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.end) - Date.now()) / 86400000));
  const toStart = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.start) - Date.now()) / 86400000));
  const [cur, nxt, later] = [sprints[at], sprints[at + 1], sprints[at + 2]];
  const out: TodaySprint[] = [];
  if (cur) out.push({ ...cur, state: 'running', daysLeft: left(cur), daysToStart: 0, startDue: false, steps: [{ key: 'review', state: 'open', detail: '' }] });
  if (nxt)
    out.push({
      ...nxt,
      state: 'next',
      daysLeft: 0,
      daysToStart: toStart(nxt),
      startDue: false,
      steps: [
        { key: 'absences', state: 'open', detail: 'announced only (3 people)' },
        { key: 'preplan', state: 'open', detail: '2 of 4 products' },
        { key: 'plan', state: 'open', detail: '' },
      ],
    });
  if (later)
    out.push({
      ...later,
      state: 'later',
      daysLeft: 0,
      daysToStart: toStart(later),
      startDue: false,
      steps: [
        { key: 'absences', state: 'open', detail: 'not entered yet' },
        { key: 'preplan', state: 'open', detail: '' },
        { key: 'plan', state: 'open', detail: '' },
      ],
    });
  const all: TodayData['findings'] = [
    { level: 'notice', where: 'sprints/2026.22.yaml', message: 'Absences are announced only.', route: '/sprint/prepare', key: 'sprints/2026.22.yaml|Absences are announced only.' },
    { level: 'notice', where: 'products.yaml: platform', message: 'The product has no share in the sprint.', route: '/team/products', key: 'products.yaml: platform|no-share' },
    { level: 'notice', where: 'projects.yaml: self-service', message: 'Project Self-Service is at risk: the contingent is nearly used up (4.0 of 40.0 PD left).', route: '/projects', key: 'projects.yaml: self-service|at-risk' },
    { level: 'notice', where: 'tickets', message: '2 refined tickets have no estimate.', route: '/backlog', key: 'tickets|no-estimate' },
  ];
  const findings = all.filter((f) => !muted.has(f.key));
  return {
    date: day,
    team: 'atlas',
    name: 'Team Atlas',
    source: 'tracker',
    sprints: out,
    errors: 0,
    notices: findings.length,
    findings,
    muted: all.filter((f) => muted.has(f.key)),
  };
}

const todayMock: Partial<Api> = {
  async Today() {
    return today();
  },
  async MuteFinding(_team, key) {
    muted.add(key);
  },
  async UnmuteFinding(_team, key) {
    muted.delete(key);
  },
};

export default todayMock;
