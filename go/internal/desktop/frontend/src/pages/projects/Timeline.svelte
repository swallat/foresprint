<script lang="ts">
  import { t } from '../../lib/i18n.svelte';
  import { link } from '../../lib/router.svelte';
  import type { Light, ProjectsView } from '../../lib/types.projects';
  import { date, month, productColor } from './format';
  import { buildTimeline, type Range } from './timeline';

  interface Props {
    view: ProjectsView;
    range: Range;
    customTo: string;
  }
  let { view, range, customTo }: Props = $props();

  const tl = $derived(
    buildTimeline({
      today: view.today,
      projects: view.projects,
      products: view.products,
      sprints: view.sprints,
      sprintDays: view.sprintDays,
      range,
      customTo,
      monthName: month,
    }),
  );
  const colorOf = (id: string) => productColor(view.products.findIndex((p) => p.id === id));
  const lightText = (l: Light) => (l === 'ok' ? t('on track') : l === 'warn' ? t('tight') : l === 'bad' ? t('at risk') : t('no light'));
</script>

<!-- Hand-drawn SVG with theme tokens only. The glyph in each diamond repeats the light. -->
<svg
  viewBox="0 0 {tl.W} {tl.H}"
  role="img"
  aria-label={t('Timeline of the projects from {from} to {to} with milestones and lights', { from: date(tl.window.from), to: date(tl.window.to) })}
>
  {#each tl.bands as b (b.band.id)}
    <rect x={b.x0} y={tl.T - 6} width={Math.max(0, b.x1 - b.x0)} height={tl.H - tl.T + 2} class={b.shaded ? 'band' : 'band off'} />
    {#if b.label}
      <text class="data muted" x={(b.x0 + b.x1) / 2} y="16" font-size="11" text-anchor="middle" font-style={b.band.ext ? 'italic' : 'normal'}>{b.band.id}</text>
    {/if}
  {/each}

  <text class="muted" x={tl.L + 4} y="36" font-size="11">{tl.firstMonth}</text>
  {#each tl.months as m (m.x)}
    <line x1={m.x} x2={m.x} y1="22" y2={tl.H - 8} class="grid" />
    {#if m.show}<text class="muted" x={m.x + 4} y="36" font-size="11">{m.label}</text>{/if}
  {/each}

  {#each tl.rows as r (r.project.id)}
    {@const yc = r.y + 20}
    <a class="row" href={link('/projects/:id', { id: r.project.id })} aria-label={t('Open project {name}', { name: r.project.name })}>
      <title>{r.project.name}: {t('ends {date}', { date: date(r.project.end) })}</title>
      <rect class="hit" x="0" y={r.y} width={tl.W} height={r.h} />
      <line x1="8" x2={tl.W - tl.R} y1={r.y + r.h - 6} y2={r.y + r.h - 6} class="grid" />
      {#each r.name as line, k (k)}
        <text x="8" y={yc - 2 + k * 16} font-size="13" font-weight="600">{line}</text>
      {/each}
      {#each r.products as line, k (k)}
        <text class="muted" x="8" y={yc + 14 + (r.name.length - 1) * 16 + k * 14} font-size="11">
          {#each line as pr, i (pr.id)}<tspan fill={colorOf(pr.id)}>●</tspan><tspan> {pr.name}{i < line.length - 1 ? '  ' : ''}</tspan>{/each}
        </text>
      {/each}
      <rect class="bar" x={tl.L} y={yc - 7} width={Math.max(0, r.barEnd - tl.L)} height="14" rx="3" />
      {#if r.cut}
        <path d="M{r.barEnd - 2} {yc - 9}l8 9l-8 9" class="arrow" />
      {:else}
        <line x1={r.barEnd} x2={r.barEnd} y1={yc - 11} y2={yc + 11} class="endline" />
      {/if}
      {#if r.later > 0 || r.cut}
        <text class="muted halo" font-size="11" x={tl.W - tl.R} y={yc - 14} text-anchor="end">
          {r.cut ? t('Ends {date}', { date: date(r.project.end) }) : ''}{r.cut && r.later > 0 ? ', ' : ''}{r.later === 1
            ? t('1 milestone later')
            : r.later > 1
              ? t('{n} milestones later', { n: r.later })
              : ''}
        </text>
      {/if}
      {#each r.marks as mk (mk.m.id)}
        {@const x = mk.x}
        <g>
          <title>{mk.m.name}, {date(mk.m.date)}: {lightText(mk.m.light)}</title>
          <path d="M{x} {yc - 9}L{x + 9} {yc}L{x} {yc + 9}L{x - 9} {yc}Z" class="dia {mk.m.light}" />
          <g class="glyph">
            {#if mk.m.light === 'ok'}
              <path d="M{x - 3.5} {yc + 0.5}l2.5 2.5l5-5" />
            {:else if mk.m.light === 'warn'}
              <path d="M{x} {yc - 3.5}v4" /><circle cx={x} cy={yc + 3.4} r=".6" />
            {:else if mk.m.light === 'bad'}
              <path d="M{x - 3} {yc - 3}l6 6M{x + 3} {yc - 3}l-6 6" />
            {/if}
          </g>
          <text font-size="11" x={mk.anchor === 'end' ? x + 9 : x} y={yc + 27 + mk.line * 14} text-anchor={mk.anchor}>
            {mk.label} <tspan class="data muted">{date(mk.m.date)}</tspan>
          </text>
        </g>
      {/each}
    </a>
  {/each}

  {#if tl.todayX !== null}
    <line x1={tl.todayX} x2={tl.todayX} y1="40" y2={tl.H - 8} class="today" />
    <text class="data halo" x={tl.todayX + 5} y={tl.T + 2} font-size="11" font-weight="600">{t('today')} {date(view.today).slice(0, 5)}</text>
  {/if}
</svg>

<style>
  svg {
    display: block;
    width: 100%;
    height: auto;
    min-width: 760px;
  }
  text {
    font-family: var(--font-ui);
    fill: var(--text);
  }
  text.data {
    font-family: var(--font-data);
  }
  tspan.data {
    font-family: var(--font-data);
  }
  .muted,
  text.muted {
    fill: var(--text-muted);
  }
  .halo {
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 3px;
  }
  .band {
    fill: var(--surface-2);
  }
  .band.off {
    fill: transparent;
  }
  .grid {
    stroke: var(--border);
  }
  .hit {
    fill: transparent;
  }
  .row {
    cursor: pointer;
    outline: none;
  }
  .row:hover .bar,
  .row:focus-visible .bar {
    fill-opacity: 0.28;
  }
  .row:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }
  .bar {
    fill: var(--primary-weak);
    stroke: var(--primary);
    stroke-width: 1.5;
  }
  .arrow {
    fill: none;
    stroke: var(--primary);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .endline {
    stroke: var(--primary);
    stroke-width: 2.5;
  }
  .today {
    stroke: var(--highlight);
    stroke-width: 2.5;
  }
  .dia {
    stroke: var(--surface);
    stroke-width: 1.5;
    fill: var(--text-muted);
  }
  .dia.ok {
    fill: var(--ok);
  }
  .dia.warn {
    fill: var(--warn);
  }
  .dia.bad {
    fill: var(--bad);
  }
  .glyph {
    stroke: var(--surface);
    stroke-width: 1.8;
    fill: var(--surface);
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .glyph path {
    fill: none;
  }
</style>
