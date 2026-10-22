// The icon registry: Material Symbols, outlined, flat (DESIGN.md), bundled as SVG text, so the
// window needs no icon font and no web request. One file per area; this file only collects them
// (add a file here only for a new area). Never use emojis in the UI.

import backlog from './backlog';
import core from './core';
import data from './data';
import forecast from './forecast';
import help from './help';
import plan from './plan';
import projects from './projects';
import settings from './settings';
import sprints from './sprints';
import team from './team';
import today from './today';

const icons = { ...backlog, ...core, ...data, ...forecast, ...help, ...plan, ...projects, ...settings, ...sprints, ...team, ...today };

export type IconName = keyof typeof icons;

export function iconSvg(name: IconName): string {
  return icons[name];
}
