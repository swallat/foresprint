// The report for the project lead as Markdown (copied to the clipboard). Texts come from the
// window's language; amounts converted from points are marked as estimates.

import { t } from '../../lib/i18n.svelte';
import type { MilestoneView, ProjectDetail } from '../../lib/types.projects';
import { date, num } from './format';

const lightText = (m: MilestoneView) =>
  m.light === 'ok' ? t('on track') : m.light === 'warn' ? t('tight') : m.light === 'bad' ? t('at risk') : t('no light');

export function reportMarkdown(d: ProjectDetail): string {
  const p = d.project;
  const est = d.unit === 'SP' ? '≈ ' : '';
  const cell = (v: number | null) => (v === null ? '–' : `${est}${num(v, 1)}`);
  const out: string[] = [`# ${t('Report: {name}', { name: p.name })}`, ''];
  out.push(
    t('As of {date}: {done} of {booked} PD done, another {planned} PD planned (estimate).', {
      date: date(d.today),
      done: cell(p.done),
      booked: p.booked === null ? '–' : num(p.booked, 1),
      planned: cell(p.planned),
    }),
    '',
  );
  if (p.milestones.length > 0) {
    out.push(`| ${t('Milestone')} | ${t('Date')} | ${t('Traffic light')} |`, '| --- | --- | --- |');
    for (const m of p.milestones) out.push(`| ${m.name} | ${date(m.date)} | ${lightText(m)} |`);
    out.push('');
  }
  if (d.report.length > 0) {
    out.push(`| ${t('Sprint')} | ${t('booked (PD)')} | ${t('planned (PD)')} | ${t('done (PD)')} |`, '| --- | ---: | ---: | ---: |');
    for (const r of d.report) out.push(`| ${r.sprint} | ${num(r.booked, 1)} | ${cell(r.planned)} | ${cell(r.done)} |`);
    out.push('');
  }
  if (est) out.push(t('Values with ≈ are estimates: points divided by the team rate.'), '');
  return out.join('\n');
}
