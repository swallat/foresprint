// Browser answers for the area Data: the invented demo team "Team Atlas" with a small storage
// that can be put into every state of the status chip. In the browser the state is switched with
// `window.__sim('incoming' | 'conflict' | 'offline' | 'mr' | 'saved' | 'findings')`, for screenshots
// and tests; the program has no such switch.

import type { Result, Status } from '../types';
import type {
  Branch,
  ChipState,
  Conflict,
  DataApi,
  DataStatus,
  Decision,
  Done,
  Label,
  LostFile,
  Problem,
  StorageSettings,
  Version,
} from '../types.data';

type Sim = 'saved' | 'incoming' | 'conflict' | 'offline' | 'mr' | 'findings';

const s = {
  sim: 'incoming' as Sim,
  unsaved: ['teams/atlas/people.yaml', 'teams/atlas/sprints/2026.22.yaml'] as string[],
  pending: 0,
  decided: {} as Record<string, 'ours' | 'theirs'>,
  token: true,
  name: 'Kim Berger',
  email: 'kim.berger@atlas.example',
  branch: 'main',
  share: 'direct' as 'direct' | 'merge_request',
  server: 'https://git.example.com/planning/atlas-data',
};

const incoming = [
  { who: 'Lea Hoffmann', day: 'today 09:10', summary: 'Absence of Paula Neumann, 2026.22: 0 to 5 days' },
  { who: 'Ben Roth', day: 'yesterday', summary: 'Milestone Beta for pilot customers: 13 Nov to 20 Nov' },
];

const conflicts = (): Conflict[] =>
  [
    {
      file: 'teams/atlas/absences.yaml',
      whole: false,
      mineDeleted: false,
      theirsDeleted: false,
      entries: [
        { path: ['jonas', '2026.22'], label: 'Absence Jonas Weber, sprint 2026.22', mine: '3', theirs: '4', before: '2', hasBefore: true, mineMissing: false, theirsMissing: false },
        { path: ['jonas', '2026.23'], label: 'Absence Jonas Weber, sprint 2026.23', mine: '0', theirs: '', before: '', hasBefore: false, mineMissing: false, theirsMissing: true },
      ],
    },
  ].filter(() => s.sim === 'conflict');

const history: Version[] = [
  { id: 'a41f9c2', short: 'a41f9c2', who: 'You', day: 'today 09:42', summary: 'Reserve ATL-415 for sprint 2026.22', files: ['teams/atlas/tickets.yaml'], merge: false, tags: [] },
  { id: '7be03d1', short: '7be03d1', who: 'Lea Hoffmann', day: 'today 09:10', summary: 'Absence of Paula Neumann, 2026.22: 0 to 5 days', files: ['teams/atlas/absences.yaml'], merge: false, tags: [] },
  { id: 'c58a2e7', short: 'c58a2e7', who: 'Kim Berger', day: 'yesterday 16:48', summary: 'Project Self-Service 2.0: contingent 50 to 60 PD', files: ['teams/atlas/projects.yaml'], merge: false, tags: [] },
  { id: '19d7f40', short: '19d7f40', who: 'You', day: 'yesterday 11:20', summary: 'FTE Felix Braun: 0.6 to 0.5', files: ['teams/atlas/people.yaml'], merge: false, tags: [] },
  { id: 'e2c61b8', short: 'e2c61b8', who: 'Lea Hoffmann', day: '19 Oct 14:05', summary: 'Sprint 2026.21: plan frozen', files: ['teams/atlas/sprints/2026.21.yaml'], merge: true, tags: [] },
  { id: 'b9441de', short: 'b9441de', who: 'You', day: '13 Oct 17:30', summary: 'Review 2026.20: velocity 37', files: ['teams/atlas/sprints/2026.20.yaml'], merge: false, tags: ['2026.20'] },
];

const labels: Label[] = [
  { name: '2026.20', target: 'b9441de', day: '13 Oct', summary: 'Review 2026.20', onServer: true, differs: false },
  { name: '2026.19', target: '8a30c15', day: '29 Sep', summary: 'Review 2026.19', onServer: true, differs: false },
  { name: '2026.18', target: 'd70be29', day: '15 Sep', summary: 'Review 2026.18', onServer: false, differs: false },
];

const chip = (): DataStatus['chip'] => {
  const n = s.unsaved.length;
  const pick = (state: ChipState, text: string, link?: string) => ({ state, text, link });
  switch (s.sim) {
    case 'conflict':
      return pick('conflict', '1 file needs your decision');
    case 'offline':
      return pick('offline', 'Offline: saving works, sharing waits');
    case 'mr':
      return pick('waiting_for_review', 'Waiting for review', 'https://git.example.com/planning/atlas-data/-/merge_requests/17');
    case 'incoming':
      return pick('incoming', `${incoming.length} new changes from Lea and Ben`);
    default:
      if (n > 0) return pick('unsaved', n === 1 ? '1 unsaved change' : `${n} unsaved changes`);
      if (s.pending > 0) return pick('pending', `${s.pending} saves not shared yet`);
      return pick('ok', 'Up to date');
  }
};

export function dataStatus(): DataStatus {
  const c = chip();
  return {
    kind: 'git',
    location: s.server,
    configured: true,
    writable: true,
    connected: s.sim !== 'offline',
    unsaved: s.unsaved.length,
    pending: s.pending,
    incoming: s.sim === 'incoming' ? incoming.length : 0,
    incomingFrom: s.sim === 'incoming' ? ['Lea Hoffmann', 'Ben Roth'] : [],
    conflicts: s.sim === 'conflict' ? 1 : 0,
    link: c.link,
    chip: c,
    capabilities: { offlineWrite: true, tags: true, branches: true, snapshots: false },
  };
}

const storageOf: Record<string, Status['storage']> = {
  ok: 'saved', unsaved: 'dirty', incoming: 'incoming', conflict: 'conflict', decided: 'decided', offline: 'offline',
  waiting_for_review: 'mr', pending: 'pending', local: 'local', problem: 'problem',
};

export function status(): Status {
  const d = dataStatus();
  return {
    storage: storageOf[d.chip.state] ?? 'saved',
    detail: d.chip.text,
    link: d.chip.link,
    incoming: d.incoming,
    findings: 1,
    tracker: { enabled: true, name: 'Jira', last: new Date(Date.now() - 4 * 60000).toISOString(), syncing: false, failed: '' },
    data: d,
  };
}

const result = (r: Partial<Result> & { ok: boolean; message: string }): Result => r;

function save(anyway: boolean): Result {
  if (s.sim === 'conflict') return result({ ok: false, message: '1 file needs your decision.', outcome: 'conflict', conflicts: 1 });
  if (s.sim === 'findings' && !anyway)
    return result({ ok: false, message: 'The data has errors. Fix them or save anyway.', outcome: 'findings', findings: ['Sprint 2026.22: the plan is higher than the capacity', 'Person Felix Braun: the share is 1.2'] });
  if (s.unsaved.length === 0) return result({ ok: true, message: 'Nothing to save.', outcome: 'nothing' });
  s.unsaved = [];
  if (s.sim === 'findings') s.sim = 'saved';
  if (s.sim === 'offline') {
    s.pending += 1;
    return result({ ok: true, message: 'Saved on this computer. It is shared when the connection is back.', outcome: 'offline' });
  }
  if (s.sim === 'mr') return result({ ok: true, message: 'Saved. Your changes wait for review on the server.', outcome: 'waiting_for_review', link: chip().link });
  return result({ ok: true, message: 'Saved.', outcome: 'saved' });
}

const done = (version = 'f00ba42'): Done => ({ version, status: dataStatus() });
const problemOf = (message: string): Problem => ({ kind: 'error', title: '', message });

export const dataMock: DataApi = {
  async SaveAnyway() {
    return save(true);
  },
  async DataIncoming() {
    return s.sim === 'incoming' ? incoming : [];
  },
  async CheckForChanges() {
    return status();
  },
  async AbortSync() {
    return false;
  },
  async Conflicts() {
    return conflicts();
  },
  async ResolveConflicts(decisions: Decision[]) {
    for (const d of decisions) s.decided[`${d.file}/${d.path.join('/')}`] = d.choice;
    const open = conflicts().flatMap((c) => c.entries.map((e) => `${c.file}/${e.path.join('/')}`)).filter((k) => !s.decided[k]);
    if (open.length > 0) return result({ ok: false, message: '1 file needs your decision.', outcome: 'conflict', conflicts: 1 });
    s.sim = 'saved';
    s.decided = {};
    return result({ ok: true, message: 'All decided. Save finishes the merge.', outcome: 'decided' });
  },
  async TakeTheirs() {
    s.sim = 'saved';
    s.unsaved = [];
    return result({ ok: true, message: 'All decided. Save finishes the merge.', outcome: 'decided' });
  },
  async AbortMerge() {
    s.sim = 'saved';
    return status();
  },
  async History(scope: string) {
    return history.filter((v) => !scope || v.files.some((f) => f.includes(scope)));
  },
  async Restore() {
    s.unsaved = ['teams/atlas/people.yaml'];
    return done();
  },
  async Revert() {
    s.unsaved = ['teams/atlas/tickets.yaml'];
    return done();
  },
  async Discard(files: string[]) {
    s.unsaved = files.length === 0 ? [] : s.unsaved.filter((f) => !files.includes(f));
    return { ...done(), warning: 'What was discarded is kept in /demo/.foresprint-trash.' };
  },
  async Lost(files: string[]) {
    const list: LostFile[] = s.unsaved.filter((f) => files.length === 0 || files.includes(f)).map((file, i) => ({ status: 'M', file, added: 2 + i, removed: 1 }));
    return list;
  },
  async Labels() {
    return labels;
  },
  async SetLabel(name: string) {
    labels.unshift({ name, target: 'f00ba42', day: 'today', summary: '', onServer: false, differs: false });
    return done();
  },
  async ShareLabel(name: string) {
    const l = labels.find((x) => x.name === name);
    if (l) l.onServer = true;
    return done();
  },
  async DeleteLabel(name: string) {
    const i = labels.findIndex((x) => x.name === name);
    if (i >= 0) labels.splice(i, 1);
    return done();
  },
  async Storage(): Promise<StorageSettings> {
    return {
      kind: 'git',
      folder: '/demo/teams',
      ready: true,
      server: s.server,
      hasSecret: false,
      branch: s.branch,
      share: s.share,
      autoMerge: false,
      host: '',
      detectedHost: 'gitlab',
      hosts: ['github', 'gitlab', 'other'],
      name: s.name,
      email: s.email,
      helper: s.token ? 'manager' : '',
      suggestedHelper: 'manager',
      setup: [
        { key: 'git', ok: true, detail: 'Git 2.45 found' },
        { key: 'identity', ok: s.name !== '', detail: s.name !== '' ? `${s.name} <${s.email}>` : 'Name and e-mail are missing' },
        { key: 'helper', ok: s.token, detail: s.token ? 'Credential helper: manager' : 'No credential helper set up', page: '' },
      ],
      guide: { kind: 'gitlab', username: 'oauth2', steps: 'Open your profile at the server, then Access tokens. Create a token with the scopes read_repository and write_repository and paste it here.' },
    };
  },
  async CheckServer(address: string) {
    if (!address.startsWith('http')) return { ok: false, address: '', empty: false, branchMissing: false, heads: [], problem: problemOf('The address does not look like a server address.') };
    return { ok: true, address, empty: false, branchMissing: false, heads: ['main'] };
  },
  async SaveServer(address: string) {
    s.server = address;
    return { address, verified: true };
  },
  async SetShare(mode: string) {
    s.share = mode === 'merge_request' ? 'merge_request' : 'direct';
    return null;
  },
  async SetHost() {
    return null;
  },
  async SetAutoMerge() {
    return null;
  },
  async SetIdentity(name: string, email: string) {
    s.name = name;
    s.email = email;
    return null;
  },
  async EnableHelper() {
    s.token = true;
    return null;
  },
  async SignInGuide() {
    return (await dataMock.Storage()).guide;
  },
  async SignIn() {
    s.token = true;
    return null;
  },
  async ForgetSignIn() {
    s.token = false;
    return null;
  },
  async Branches(): Promise<Branch[]> {
    return ['main', 'foresprint/kberger', 'release-2026'].map((name) => ({ name, local: true, remote: name === 'main', current: name === s.branch }));
  },
  async SwitchBranch(name: string) {
    if (s.unsaved.length > 0) return { ...done(), problem: problemOf('Save or discard your changes first.') };
    s.branch = name;
    return done();
  },
  async Reattach() {
    return { branch: 'main', rescue: '', commits: false, changes: false };
  },
  async CloneFrom(_address: string, folder: string) {
    return { folder };
  },
  async CreateFolder(folder: string) {
    return { folder };
  },
  async OpenFolder(folder: string) {
    return { folder };
  },
  async PickFolder() {
    return '';
  },
};

/** Takes over what others did (Refresh) in the mock. */
export function refreshMock(): Result {
  if (s.sim === 'offline') return result({ ok: false, message: 'No connection. You keep working with the last state.', outcome: 'offline' });
  if (s.sim === 'conflict') return result({ ok: false, message: '1 file needs your decision.', outcome: 'conflict', conflicts: 1 });
  if (s.sim === 'mr') return result({ ok: true, message: 'Up to date.', outcome: 'nothing' });
  const n = s.sim === 'incoming' ? incoming.length : 0;
  s.sim = 'saved';
  return n > 0 ? result({ ok: true, message: `Done. Took over ${n} changes from others.`, outcome: 'saved', taken: incoming }) : result({ ok: true, message: 'Up to date.', outcome: 'nothing' });
}

export { save as saveMock };

(window as unknown as { __sim: (state: Sim) => void }).__sim = (state) => {
  s.sim = state;
  if (state === 'saved') s.unsaved = [];
  if (state === 'findings' && s.unsaved.length === 0) s.unsaved = ['teams/atlas/people.yaml'];
};

export default dataMock;
