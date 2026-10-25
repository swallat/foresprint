// Browser answers for the start page (Today) of the demo team.

import type { Api } from '../api';
import type { TodayData, TodaySprint } from '../types.today';
import type { SprintInfo } from '../types';
import { sprints } from './shared';

function today(): TodayData {
  const day = new Date().toISOString().slice(0, 10);
  const at = Math.max(0, sprints.findIndex((s) => s.state === 'current'));
  const left = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.end) - Date.now()) / 86400000));
  const toStart = (s: SprintInfo) => Math.max(0, Math.round((Date.parse(s.start) - Date.now()) / 86400000));
  const [cur, nxt, later] = [sprints[at], sprints[at + 1], sprints[at + 2]];
  const out: TodaySprint[] = [];
  if (cur) out.push({ ...cur, state: 'running', daysLeft: left(cur), daysToStart: 0, steps: [{ key: 'review', state: 'open', detail: '' }] });
  if (nxt)
    out.push({
      ...nxt,
      state: 'next',
      daysLeft: 0,
      daysToStart: toStart(nxt),
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
      steps: [
        { key: 'absences', state: 'open', detail: 'not entered yet' },
        { key: 'preplan', state: 'open', detail: '' },
        { key: 'plan', state: 'open', detail: '' },
      ],
    });
  return {
    date: day,
    team: 'atlas',
    name: 'Team Atlas',
    source: 'tracker',
    sprints: out,
    errors: 0,
    notices: 4,
    findings: [
      { level: 'notice', where: 'sprints/2026.22.yaml', message: 'Absences are announced only.', route: '/sprint/prepare' },
      { level: 'notice', where: 'products.yaml: platform', message: 'The product has no share in the sprint.', route: '/team/products' },
      { level: 'notice', where: 'projects.yaml: self-service', message: 'Project Self-Service is at risk: the contingent is nearly used up (4.0 of 40.0 PD left).', route: '/projects' },
      { level: 'notice', where: 'tickets', message: '2 open tickets have no estimate.', route: '/backlog' },
    ],
  };
}

const todayMock: Partial<Api> = {
  async Today() {
    return today();
  },
};

export default todayMock;
