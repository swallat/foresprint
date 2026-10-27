<script lang="ts">
  import { shortNames } from '../../lib/axis';
  import { fmt, fmtVal } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import type { ForecastRow, WhatIfRow } from '../../lib/types.forecast';

  interface Props {
    past: ForecastRow[];
    upcoming: ForecastRow[];
    whatIf?: WhatIfRow[];
    /** How many completed sprints to show. */
    shown?: number;
    /** Decimals of the plan numbers (the team's rounding). */
    digits?: number;
  }
  let { past, upcoming, whatIf = [], shown = 10, digits = 0 }: Props = $props();

  // Normalized velocity (history and trend) can be switched off.
  let showNv = $state(true);

  const W = 760;
  const H = 300;
  const M0 = { l: 44, r: 52, t: 24, b: 44 };

  // Space between two axis labels and the width of one character (12px data font).
  const CHAR = 7.4;
  const ROW = 15;

  const history = $derived(past.slice(-shown));
  const all = $derived([...history, ...upcoming]);
  const wi = $derived(new Map(whatIf.map((r) => [r.id, r])));

  // Names that share a prefix ("Team Sprint 41", "Team Sprint 42") drop it on the axis; the tooltip keeps the full name.
  const axisNames = $derived(shortNames(all.map((r) => r.id)));
  const slot = $derived((W - M0.l - M0.r) / Math.max(1, all.length));
  const needed = $derived(Math.max(0, ...axisNames.map((n) => n.length)) * CHAR + 6);
  // Labels that would touch alternate between two rows; if even that is too tight, every other one is skipped.
  const rows = $derived(needed > slot ? 2 : 1);
  const showEvery = $derived(needed > slot * rows ? Math.ceil(needed / (slot * rows)) : 1);
  const M = $derived({ ...M0, b: M0.b + (rows - 1) * ROW });

  const top = $derived.by(() => {
    let max = 0;
    for (const r of history) max = Math.max(max, r.velocity ?? 0, showNv ? (r.normalizedVelocity ?? 0) : 0);
    for (const r of upcoming) max = Math.max(max, r.plan ?? 0, r.high ?? 0, wi.get(r.id)?.forecast ?? 0, showNv ? (r.trend ?? 0) : 0);
    const step = max > 60 ? 20 : max > 30 ? 10 : 5;
    return Math.max(step, Math.ceil(max / step) * step);
  });
  const ticks = $derived.by(() => {
    const step = top > 60 ? 20 : top > 30 ? 10 : 5;
    return Array.from({ length: Math.floor(top / step) + 1 }, (_, i) => i * step);
  });
  const x = (i: number) => M.l + ((W - M.l - M.r) * (i + 0.5)) / Math.max(1, all.length);
  const y = (v: number) => M.t + (H - M.t - M.b) * (1 - v / top);

  const line = (pts: { x: number; y: number }[]) => pts.map((p) => `${p.x},${p.y}`).join(' ');
  const velocityPts = $derived(
    history.flatMap((r, i) => (r.velocity !== null ? [{ x: x(i), y: y(r.velocity), r }] : [])),
  );
  const nvPts = $derived(
    history.flatMap((r, i) => (r.normalizedVelocity !== null ? [{ x: x(i), y: y(r.normalizedVelocity), r }] : [])),
  );
  // The trend of the normalized velocity carried on into the coming sprints (what the plan is calculated from).
  const trendPts = $derived(
    upcoming.flatMap((r, i) => (r.trend !== null ? [{ x: x(history.length + i), y: y(r.trend), r }] : [])),
  );
  const trendLine = $derived.by(() => {
    const last = nvPts.at(-1);
    return last ? [{ x: last.x, y: last.y }, ...trendPts] : trendPts;
  });
  const planPts = $derived(
    upcoming.flatMap((r, i) => (r.plan !== null ? [{ x: x(history.length + i), y: y(r.plan), r }] : [])),
  );
  const wiPts = $derived(
    upcoming.flatMap((r, i) => {
      const w = wi.get(r.id);
      return w ? [{ x: x(history.length + i), y: y(w.forecast), w }] : [];
    }),
  );
  // The dashed forecast line starts at the last completed sprint so the eye connects them.
  const planLine = $derived.by(() => {
    const last = velocityPts.at(-1);
    return last ? [{ x: last.x, y: last.y }, ...planPts] : planPts;
  });
  // Labels in the plot are rounded to one decimal so they stay short; tooltips keep the team's rounding.
  const label = (v: number | null) => fmt(v, 1);

  const diamond = (cx: number, cy: number, r: number) => `${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`;
</script>

<label class="nv-switch small"><input type="checkbox" bind:checked={showNv} />{t('Show normalized velocity and its trend')}</label>

<div class="legend small" aria-hidden="true">
  <span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" class="s vel" /><circle cx="9" cy="6" r="4" class="f vel" /></svg>{t('Velocity')}</span>
  {#if showNv}
    <span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" class="s nv" /><rect x="5" y="2" width="8" height="8" class="f nv" /></svg>{t('Normalized velocity')}</span>
    <span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" class="s nv dash" /></svg>{t('Trend of the normalized velocity')}</span>
  {/if}
  <span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" class="s fc dash" /><polygon points={diamond(9, 6, 5)} class="o fc" /></svg>{t('Forecast PLAN')}</span>
  <span><svg width="18" height="12"><line x1="9" x2="9" y1="0" y2="12" class="s fc" /><line x1="4" x2="14" y1="1" y2="1" class="s fc" /><line x1="4" x2="14" y1="11" y2="11" class="s fc" /></svg>{t('Range')}</span>
  {#if whatIf.length > 0}
    <span><svg width="18" height="12"><line x1="0" x2="18" y1="6" y2="6" class="s wif dash" /><polygon points={diamond(9, 6, 5)} class="f wif" /></svg>{t('What if')}</span>
  {/if}
</div>

<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label={t('Chart of velocity and Forecast PLAN per sprint; the same numbers are in the tables below.')}>
  {#each ticks as v (v)}
    <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} class="grid" />
    <text x={M.l - 8} y={y(v) + 4} text-anchor="end" class="axis">{v}</text>
  {/each}

  {#if history.length > 0 && upcoming.length > 0}
    <rect x={x(history.length) - (W - M.l - M.r) / all.length / 2} y={M.t} width={(W - M.l - M.r) * upcoming.length / all.length} height={H - M.t - M.b} class="future" />
  {/if}

  {#each all as r, i (r.id)}
    {#if i % showEvery === 0}
      <text x={x(i)} y={H - M.b + 18 + (rows > 1 ? ((i / showEvery) % 2) * ROW : 0)} text-anchor="middle" class="axis"><title>{r.id}</title>{axisNames[i]}</text>
    {/if}
  {/each}

  {#if showNv && trendLine.length > 1}<polyline points={line(trendLine)} class="s nv dash" fill="none" />{/if}
  {#if showNv && nvPts.length > 1}<polyline points={line(nvPts)} class="s nv" fill="none" />{/if}
  {#if velocityPts.length > 1}<polyline points={line(velocityPts)} class="s vel" fill="none" />{/if}
  {#if planLine.length > 1}<polyline points={line(planLine)} class="s fc dash" fill="none" />{/if}

  {#if showNv}
    {#each trendPts as p (p.r.id)}
      <circle cx={p.x} cy={p.y} r="3.5" class="o nv"><title>{t('{id}: trend of the normalized velocity {n}', { id: p.r.id, n: fmtVal(p.r.trend) })}</title></circle>
    {/each}
  {/if}
  {#each showNv ? nvPts : [] as p (p.r.id)}
    <rect x={p.x - 4} y={p.y - 4} width="8" height="8" class="f nv"><title>{t('{id}: normalized velocity {n}', { id: p.r.id, n: fmtVal(p.r.normalizedVelocity) })}</title></rect>
  {/each}
  {#each velocityPts as p (p.r.id)}
    <circle cx={p.x} cy={p.y} r="5" class="f vel"><title>{t('{id}: velocity {n}', { id: p.r.id, n: fmtVal(p.r.velocity) })}</title></circle>
  {/each}

  {#each planPts as p (p.r.id)}
    {#if p.r.low !== null && p.r.high !== null}
      <line x1={p.x} x2={p.x} y1={y(p.r.high)} y2={y(p.r.low)} class="s fc" />
      <line x1={p.x - 5} x2={p.x + 5} y1={y(p.r.high)} y2={y(p.r.high)} class="s fc" />
      <line x1={p.x - 5} x2={p.x + 5} y1={y(p.r.low)} y2={y(p.r.low)} class="s fc" />
    {/if}
    <polygon points={diamond(p.x, p.y, 7)} class="o fc">
      <title>{p.r.low !== null
        ? t('{id}: Forecast PLAN {plan}, range {low} – {high}', { id: p.r.id, plan: fmt(p.r.plan, digits), low: fmt(p.r.low, digits), high: fmt(p.r.high, digits) })
        : t('{id}: Forecast PLAN {plan}', { id: p.r.id, plan: fmt(p.r.plan, digits) })}</title>
    </polygon>
    <text x={p.x} y={(p.r.high !== null ? y(p.r.high) : p.y - 7) - 7} text-anchor="middle" class="value">{label(p.r.plan)}</text>
  {/each}

  {#each wiPts as p (p.w.id)}
    <polygon points={diamond(p.x, p.y, 5)} class="f wif"><title>{t('{id}: what if {n}', { id: p.w.id, n: fmt(p.w.forecast, digits) })}</title></polygon>
    <text x={p.x + 11} y={p.y + 4} class="value wiftext">{label(p.w.forecast)}</text>
  {/each}
</svg>

<style>
  .legend {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 8px;
    color: var(--text);
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .nv-switch {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-bottom: 8px;
  }
  .chart {
    width: 100%;
    height: auto;
    display: block;
    overflow: visible;
  }
  .grid {
    stroke: var(--border);
    stroke-width: 1;
  }
  .axis {
    fill: var(--text-muted);
    font: 12px var(--font-data);
  }
  .value {
    fill: var(--text);
    font: 600 12px var(--font-data);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 4px;
    stroke-linejoin: round;
  }
  .future {
    fill: var(--forecast-weak);
    opacity: 0.5;
  }
  .s {
    stroke-width: 2;
  }
  .dash {
    stroke-dasharray: 6 4;
  }
  .vel { stroke: var(--c-vel); }
  .nv { stroke: var(--c-nv); }
  .fc { stroke: var(--c-fc); }
  .wif { stroke: var(--c-wif); }
  .f.vel { fill: var(--c-vel); stroke: var(--surface); stroke-width: 1.5; }
  .f.nv { fill: var(--c-nv); stroke: var(--surface); stroke-width: 1.5; }
  .f.wif { fill: var(--c-wif); stroke: var(--surface); stroke-width: 1.5; }
  .o { fill: var(--surface); stroke-width: 2.5; }
  .value.wiftext { fill: var(--c-wif); }
</style>
