// Browser answers for the first-start setup (storage, sign-in, new team) of the demo team.

import type { Api } from '../api';
import type { NewTeam, Opened, Problem, Region, ServerCheck, SetupKind, SetupState, SignInGuide } from '../types.setup';
import { demo, sprints } from './shared';

const noProblem = (): Problem | null => null;

const regions: Region[] = [
  { country: 'DE', name: 'Germany', regions: ['BW', 'BY', 'BE', 'HH', 'HE', 'NI', 'NW', 'SN'] },
  { country: 'AT', name: 'Austria', regions: ['1', '3', '9'] },
  { country: 'CH', name: 'Switzerland', regions: ['ZH', 'BE', 'GE'] },
];

const setupMock: Partial<Api> = {
  async SetupState(): Promise<SetupState> {
    return { dataDir: demo.prefs.dataDir, teams: [demo.team], name: '', email: '', suggestedHelper: '' };
  },
  async PickFolder() {
    return '/demo/folder';
  },
  async SetupCheckServer(address: string): Promise<ServerCheck> {
    if (!address.startsWith('https://')) {
      return { ok: false, address: '', empty: false, branchMissing: false, heads: [], problem: { kind: 'url', title: 'Not an address', message: 'The address must start with https://.' } };
    }
    return { ok: true, address, empty: false, branchMissing: false, heads: ['main'] };
  },
  async SetupStorage(_kind: SetupKind, _address: string, folder: string): Promise<Opened> {
    return { folder };
  },
  async SetupGuide(): Promise<SignInGuide> {
    return { kind: 'gitlab', username: 'oauth2', steps: 'Create an access token with read and write access to the repository and paste it here.' };
  },
  async SetupSignIn(_address: string, _user: string, token: string) {
    return token ? noProblem() : { kind: 'auth', title: 'No token', message: 'Paste a token first.' };
  },
  async SetupEnableHelper() {
    return noProblem();
  },
  async SetupIdentity() {
    return noProblem();
  },
  async SetupRegions() {
    return regions;
  },
  async SetupCreateTeam(req: NewTeam) {
    demo.team = { key: req.name.toLowerCase().replace(/\W+/g, '-'), name: req.name, people: 0, sprints: 3, tickets: req.source !== 'none', products: 0 };
    return demo.team;
  },
};

export default setupMock;
