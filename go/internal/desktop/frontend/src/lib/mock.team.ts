// Mock answers of the Team area for a browser without the program (demo team "Atlas").

import type { RuleOwner, RulePreview, TeamApi } from './types.team';

const fields = ['epic', 'component', 'label', 'status', 'issue_type', 'priority', 'in_sprint'];

interface DemoTicket {
  key: string;
  estimate: number;
  facts: Record<string, string[]>;
}

const tickets: DemoTicket[] = [
  { key: 'ATL-412', estimate: 5, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-415', estimate: 8, facts: { component: ['Portal'], label: ['self-service'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-417', estimate: 5, facts: { component: ['Mobile App'], epic: ['Self-Service 2.0'] } },
  { key: 'ATL-421', estimate: 8, facts: { component: ['Platform'], label: ['login', 'security'], epic: ['Login switch'] } },
  { key: 'ATL-423', estimate: 5, facts: { component: ['Billing'], label: ['xrechnung'], epic: ['E-Invoice'] } },
  { key: 'ATL-426', estimate: 2, facts: { component: ['Portal'] } },
];

// A small reader for the rule language: field = "value", field ~ "part", AND, OR. The real
// parser is in Go; this is enough to make the editor testable in a browser.
function evaluate(text: string, facts: Record<string, string[]>): boolean {
  const ors = text.split(/\s+OR\s+/i);
  return ors.some((part) =>
    part.split(/\s+AND\s+/i).every((cond) => {
      const m = /^\s*\(*\s*(\w+)\s*(=|!=|~|!~)\s*"?([^")]*)"?\s*\)*\s*$/.exec(cond);
      if (!m) return false;
      const [, field = '', op = '=', value = ''] = m;
      const have = (facts[field] ?? []).map((v) => v.toLowerCase());
      const want = value.toLowerCase();
      const hit = op.endsWith('~') ? have.some((v) => v.includes(want)) : have.includes(want);
      return op.startsWith('!') ? !hit : hit;
    }),
  );
}

export const teamMock: TeamApi = {
  async RuleFields() {
    return fields;
  },
  async CheckRule(_team: string, text: string, _owner: RuleOwner): Promise<RulePreview> {
    const base = { fields, pos: -1, sample: [] as string[], clash: 0, moved: 0, matches: 0, points: 0 };
    if (!text.trim()) return { ...base, valid: false, error: 'The expression is empty', pos: 0 };
    const first = (/^\s*\(*\s*(\w+)/.exec(text)?.[1] ?? '').toLowerCase();
    if (!fields.includes(first)) {
      return { ...base, valid: false, error: `Unknown field '${first}'`, pos: 0 };
    }
    const hit = tickets.filter((t) => evaluate(text, t.facts));
    return {
      ...base,
      valid: true,
      normalized: text.trim(),
      matches: hit.length,
      points: hit.reduce((n, t) => n + t.estimate, 0),
      sample: hit.slice(0, 5).map((t) => t.key),
    };
  },
};
