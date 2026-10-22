// Browser answers of the Review and the minutes for the demo team "Team Atlas" (invented
// people and products). The same rules as go/internal/app/api_review.go: velocity = commitment -
// not done + additionally done; the Review of the latest reviewed sprint can be reopened; the
// minutes of a reopened Review stay as obsolete files.

import type { SprintInfo } from './types';
import type {
  MinutesRow,
  MinutesText,
  ReviewApi,
  ReviewClosed,
  ReviewInput,
  ReviewProduct,
  ReviewTicket,
  SprintReview,
} from './types.review';

const products = [
  { id: 'portal', name: 'Portal', share: 0.34 },
  { id: 'billing', name: 'Billing', share: 0.22 },
  { id: 'mobile', name: 'Mobile app', share: 0.26 },
  { id: 'platform', name: 'Platform', share: 0.18 },
];

const tickets: [string, string, number][] = [
  ['ATL-101', 'Single sign-on for the portal', 5],
  ['ATL-102', 'Invoice export as CSV', 3],
  ['ATL-103', 'Push notification settings', 8],
  ['ATL-104', 'Rate limits on the public API', 5],
  ['ATL-105', 'Dark theme for the mobile app', 3],
];

export interface ReviewMockOptions {
  /** The team commits to tickets (the Review lists them) instead of typed amounts. */
  tickets?: boolean;
}

const pad = (n: number) => String(n).padStart(2, '0');
const stamp = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;

export function createReviewMock(sprints: SprintInfo[], options: ReviewMockOptions = {}): ReviewApi {
  const COMMITMENT = 36;
  const DAYS = 49;
  const closed = new Map<string, ReviewInput>();
  const files: { row: MinutesRow; text: string }[] = [];
  const list = (): ReviewTicket[] => tickets.map(([key, title, estimate]) => ({ key, title, estimate, done: false, rest: estimate, target: '' }));
  const targetsOf = (id: string) => {
    const later = sprints.filter((s) => s.start > (sprints.find((x) => x.id === id)?.start ?? ''));
    return [
      ...later.slice(0, 4).map((s, i) => ({ id: i === 0 ? '' : s.id, name: s.id })),
      { id: 'backlog', name: 'backlog' },
    ];
  };
  const known = (id: string) => {
    const s = sprints.find((x) => x.id === id);
    if (!s) throw new Error(`Sprint ${id} does not exist.`);
    return s;
  };
  const latestReviewed = () => [...sprints].reverse().find((s) => closed.has(s.id))?.id;
  // The finished sprints of the demo are reviewed; the newest finished one is reopenable.
  const pastIds = sprints.filter((s) => s.state === 'past').map((s) => s.id);
  pastIds.forEach((id, i) =>
    closed.set(id, {
      notDone: i % 3 === 0 ? 2 : 0,
      additionalDone: i % 2 === 0 ? 1 : 0,
      restNext: i % 3 === 0 ? 1 : 0,
      list: [],
      frozenDays: DAYS,
      products: [],
      production: 0,
      tag: '',
    }),
  );

  const view = (id: string): SprintReview => {
    const s = known(id);
    const input = closed.get(id);
    const rows: ReviewTicket[] = options.tickets
      ? list().map((r) => {
          const kept = input?.list.find((x) => x.key === r.key);
          return input ? { ...r, ...(kept ?? { done: true, rest: 0, target: '' }) } : r;
        })
      : [];
    const notDone = options.tickets ? rows.filter((r) => !r.done).reduce((n, r) => n + r.estimate, 0) : (input?.notDone ?? 0);
    const commitment = options.tickets ? tickets.reduce((n, t) => n + t[2], 0) : COMMITMENT;
    const additional = input?.additionalDone ?? 0;
    const velocity = commitment - notDone + additional;
    const frozen = input?.frozenDays ?? DAYS;
    const items: ReviewProduct[] = products.map((p) => {
      const got = input?.products.find((x) => x.id === p.id);
      const planned = Math.round(commitment * p.share);
      return { id: p.id, name: p.name, planned, done: got?.done ?? 0, prodDone: got?.prodDone ?? 0 };
    });
    return {
      sprint: {
        id,
        name: id,
        start: s.start,
        end: s.end,
        state: s.state === 'future' ? 'unknown' : 'confirmed',
        workdays: 10,
        entries: 0,
        absent: 0,
        capacity: DAYS,
        plan: null,
        past: s.state === 'past',
      },
      unit: 'PT',
      started: s.state !== 'future',
      reviewed: input !== undefined,
      reopenable: input !== undefined && latestReviewed() === id,
      tickets: options.tickets === true,
      commitment,
      notDone,
      additionalDone: additional,
      restNext: input?.restNext ?? 0,
      velocity,
      list: rows,
      targets: targetsOf(id),
      plannedDays: DAYS,
      frozenDays: frozen,
      rate: frozen > 0 ? velocity / frozen : null,
      products: items,
      productsOn: true,
      productionOn: true,
      production: 0,
      tag: `atlas/${id}`,
    };
  };

  const minutesText = (r: SprintReview) =>
    [
      `# Sprint Review Team Atlas – Sprint ${r.sprint.id}`,
      '',
      `- Commitment: ${r.commitment} ${r.unit}`,
      `- Not done: ${r.notDone}`,
      `- Done in addition: ${r.additionalDone}`,
      `- Velocity: ${r.velocity} ${r.unit}`,
      `- Person days (frozen): ${r.frozenDays}`,
      '',
      '## Per product',
      '',
      '| Product | Planning | Done |',
      '|---|---|---|',
      ...r.products.map((p) => `| ${p.name} | ${p.planned} | ${p.done} |`),
      '',
    ].join('\n');

  // The finished sprints already have their Review minutes (the newest two, for the demo).
  pastIds.slice(-2).forEach((id, i) => {
    const row: MinutesRow = { sprint: id, kind: 'review', at: stamp(new Date(Date.now() - (2 - i) * 14 * 86400000)), file: `protokolle/${id}-review-seed.md`, obsolete: false };
    files.push({ row, text: minutesText(view(id)) });
  });

  const nonNegative = (...values: number[]) => {
    if (values.some((v) => !(v >= 0))) throw new Error('Numbers in the Review must not be negative.');
  };

  return {
    async SprintReview(_team, sprint) {
      return view(sprint);
    },
    async CloseReview(_team, sprint, input): Promise<ReviewClosed> {
      const s = known(sprint);
      if (s.state === 'future') throw new Error(`Sprint ${sprint} has not begun; it cannot be reviewed yet.`);
      nonNegative(input.notDone, input.additionalDone, input.restNext, input.frozenDays, input.production);
      const before = view(sprint);
      if (!options.tickets && input.notDone > before.commitment) throw new Error('Not done cannot be more than the commitment.');
      if (!options.tickets && input.restNext > input.notDone) throw new Error('The rest that continues cannot be more than what was not done.');
      closed.set(sprint, { ...input, frozenDays: input.frozenDays || DAYS, list: input.list.filter((r) => !r.done) });
      const review = view(sprint);
      const name = `protokolle/${sprint}-review-${files.length + 1}.md`;
      const text = minutesText(review);
      const same = files.find((f) => f.row.sprint === sprint && f.row.kind === 'review' && !f.row.obsolete && f.text === text);
      if (!same) files.unshift({ row: { sprint, kind: 'review', at: stamp(new Date()), file: name, obsolete: false }, text });
      return { review, minutes: (same ?? files[0])?.row.file ?? '', tag: input.tag };
    },
    async ReopenReview(_team, sprint): Promise<ReviewClosed> {
      if (view(sprint).reopenable !== true) throw new Error('Only the latest reviewed sprint can be reopened.');
      closed.delete(sprint);
      for (const f of files) if (f.row.sprint === sprint && f.row.kind === 'review') f.row.obsolete = true;
      return { review: view(sprint), minutes: '', tag: '' };
    },
    async SprintMinutes(_team, sprint): Promise<MinutesRow[]> {
      return files.filter((f) => sprint === '' || f.row.sprint === sprint).map((f) => ({ ...f.row }));
    },
    async MinutesText(_team, file): Promise<MinutesText> {
      const f = files.find((x) => x.row.file === file);
      if (!f) throw new Error('This is not a minutes file.');
      return { text: f.text, path: `/data/atlas/${f.row.file}` };
    },
  };
}
