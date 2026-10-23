// The route table and the navigation (flows.md section 5). This file is the only place that
// knows which address shows which page file. A page package replaces the content of its own
// page files in src/pages/ and does not need to edit this file; a new address is one line here.
//
// Labels are English source texts; the shell translates them with t().

import type { Component } from 'svelte';
import type { IconName } from './icons';

export type Needs = 'tickets';

/** Props every page component receives. */
export interface PageProps {
  params: Record<string, string>;
}

export interface PageDef {
  path: string; // "/projects/:id"
  title: string; // source text, shown in the window title and the command palette
  load: () => Promise<{ default: Component<PageProps> }>;
  /** Path of the navigation entry that is marked while this page is open. */
  nav?: string;
  /** Full window without the rail and top bar (first-run wizard). */
  bare?: boolean;
}

export const pages: PageDef[] = [
  { path: '/today', title: 'Today', load: () => import('../pages/today/Today.svelte') },
  { path: '/setup', title: 'First start', bare: true, load: () => import('../pages/today/FirstRun.svelte') },

  { path: '/backlog', title: 'Backlog', load: () => import('../pages/backlog/Backlog.svelte') },
  { path: '/present', title: 'Presentation view', nav: '/backlog', load: () => import('../pages/backlog/Present.svelte') },

  { path: '/sprints', title: 'Sprint overview', load: () => import('../pages/sprints/Sprints.svelte') },
  { path: '/sprint/prepare', title: 'Prepare', load: () => import('../pages/sprints/Prepare.svelte') },
  { path: '/sprint/preplan', title: 'Pre-plan', load: () => import('../pages/plan/Preplan.svelte') },
  { path: '/sprint/plan', title: 'Plan', load: () => import('../pages/plan/Plan.svelte') },
  { path: '/sprint/review', title: 'Review', load: () => import('../pages/sprints/Review.svelte') },
  { path: '/sprint/minutes', title: 'Minutes', load: () => import('../pages/sprints/Minutes.svelte') },

  { path: '/projects', title: 'Projects', load: () => import('../pages/projects/Projects.svelte') },
  { path: '/projects/:id', title: 'Project', nav: '/projects', load: () => import('../pages/projects/ProjectDetail.svelte') },

  { path: '/forecast', title: 'Forecast', load: () => import('../pages/forecast/Forecast.svelte') },

  { path: '/team/people', title: 'People and absences', load: () => import('../pages/team/People.svelte') },
  { path: '/team/products', title: 'Products', load: () => import('../pages/team/Products.svelte') },
  { path: '/team/calendar', title: 'Sprint calendar', load: () => import('../pages/team/Calendar.svelte') },

  { path: '/data', title: 'Data overview', load: () => import('../pages/data/Overview.svelte') },
  { path: '/data/conflicts', title: 'Conflicts', load: () => import('../pages/data/Conflicts.svelte') },
  { path: '/data/history', title: 'History and tags', load: () => import('../pages/data/History.svelte') },

  { path: '/settings/team', title: 'Team settings', load: () => import('../pages/settings/TeamSettings.svelte') },
  { path: '/settings/tickets', title: 'Tickets and tracker', load: () => import('../pages/settings/Tickets.svelte') },
  { path: '/settings/storage', title: 'Storage', load: () => import('../pages/settings/Storage.svelte') },
  { path: '/settings/updates', title: 'Updates', load: () => import('../pages/settings/Updates.svelte') },
  { path: '/settings/personal', title: 'Personal settings', load: () => import('../pages/settings/Personal.svelte') },

  { path: '/help/calculations', title: 'Calculations', load: () => import('../pages/help/Calculations.svelte') },
  { path: '/help/guided', title: 'Guided flows', load: () => import('../pages/help/Guided.svelte') },
];

export interface NavItem {
  path: string;
  icon: IconName;
  label: string;
  /** Shown only when the team gets its work from a tracker or work packages (no "no tickets" mode). */
  needs?: Needs;
  /** Indented entry of the sprint workspace. */
  sub?: boolean;
}

export interface NavGroup {
  label?: string;
  /** Adds the id of the selected sprint behind the heading. */
  sprint?: boolean;
  items: NavItem[];
}

export const nav: NavGroup[] = [
  {
    items: [
      { path: '/today', icon: 'today', label: 'Today' },
      { path: '/backlog', icon: 'view_list', label: 'Backlog', needs: 'tickets' },
    ],
  },
  {
    label: 'Sprints',
    sprint: true,
    items: [
      { path: '/sprints', icon: 'date_range', label: 'Sprint overview' },
      { path: '/sprint/prepare', icon: 'event_available', label: 'Prepare', sub: true },
      { path: '/sprint/preplan', icon: 'low_priority', label: 'Pre-plan', sub: true },
      { path: '/sprint/plan', icon: 'checklist', label: 'Plan', sub: true },
      { path: '/sprint/review', icon: 'task_alt', label: 'Review', sub: true },
      { path: '/sprint/minutes', icon: 'description', label: 'Minutes', sub: true },
    ],
  },
  {
    items: [
      { path: '/projects', icon: 'flag', label: 'Projects' },
      { path: '/forecast', icon: 'monitoring', label: 'Forecast' },
    ],
  },
  {
    label: 'Team',
    items: [
      { path: '/team/people', icon: 'group', label: 'People and absences' },
      { path: '/team/products', icon: 'category', label: 'Products' },
      { path: '/team/calendar', icon: 'calendar_month', label: 'Sprint calendar' },
    ],
  },
  {
    label: 'Data',
    items: [
      { path: '/data', icon: 'database', label: 'Overview' },
      { path: '/data/conflicts', icon: 'call_split', label: 'Conflicts' },
      { path: '/data/history', icon: 'history', label: 'History and tags' },
    ],
  },
  {
    label: 'Settings',
    items: [
      { path: '/settings/team', icon: 'tune', label: 'Team' },
      { path: '/settings/tickets', icon: 'sync', label: 'Tickets and tracker' },
      { path: '/settings/storage', icon: 'cloud', label: 'Storage' },
      { path: '/settings/personal', icon: 'person', label: 'Personal' },
      { path: '/settings/updates', icon: 'cloud_download', label: 'Updates' },
    ],
  },
  {
    label: 'Help',
    items: [
      { path: '/help/calculations', icon: 'calculate', label: 'Calculations' },
      { path: '/help/guided', icon: 'route', label: 'Guided flows' },
    ],
  },
];
