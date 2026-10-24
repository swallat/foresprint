// Types of the first-start wizard (go/internal/app/api_setup.go and datasvc).

import type { TeamSummary } from './types';
import type { TicketSource } from './types.today';

export interface Problem {
  kind: string;
  title: string;
  message: string;
  hint?: string;
}

export interface ServerCheck {
  ok: boolean;
  address: string;
  empty: boolean;
  branchMissing: boolean;
  heads: string[];
  problem?: Problem | null;
}

export interface Opened {
  folder: string;
  problem?: Problem | null;
}

export interface SignInGuide {
  kind: string;
  username: string;
  steps: string;
}

export interface SetupState {
  dataDir: string;
  teams: TeamSummary[];
  name: string;
  email: string;
  suggestedHelper: string;
}

export interface Region {
  country: string;
  name: string;
  regions: string[];
}

export interface NewTeam {
  name: string;
  country: string;
  region: string;
  firstSprintId: string;
  firstStart: string;
  lengthDays: number;
  source: TicketSource;
  trackerUrl: string;
  trackerQuery: string;
}

export type SetupKind = 'clone' | 'open' | 'new';

export interface SetupApi {
  SetupState(): Promise<SetupState>;
  SetupCheckServer(address: string): Promise<ServerCheck>;
  SetupStorage(kind: SetupKind, address: string, folder: string): Promise<Opened>;
  SetupGuide(address: string): Promise<SignInGuide>;
  SetupSignIn(address: string, username: string, token: string): Promise<Problem | null>;
  SetupEnableHelper(name: string): Promise<Problem | null>;
  SetupIdentity(name: string, email: string): Promise<Problem | null>;
  SetupRegions(): Promise<Region[]>;
  SetupCreateTeam(req: NewTeam): Promise<TeamSummary>;
  /** Moves the folder of the team to the archive; confirm is the name of the team. Nothing is deleted. */
  ArchiveTeam(team: string, confirm: string): Promise<void>;
  ArchivedTeams(): Promise<TeamSummary[]>;
  RestoreTeam(team: string): Promise<void>;
}
