<script lang="ts">
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { fmt, pct, shortDate } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { ForecastView, WhatIfRow, WhenDoneView } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import ForecastChart from './ForecastChart.svelte';

  let { params }: PageProps = $props();
  void params;

  let view = $state<ForecastView>();
  let problem = $state('');

  $effect(() => {
    const team = app.team;
    let stale = false;
    view = undefined;
    problem = '';
    if (!team) return;
    api
      .Forecast(team)
      .then((v) => {
        if (!stale) view = v;
      })
      .catch((e) => {
        if (!stale) problem = String(e);
      });
    return () => {
      stale = true;
    };
  });

  // What if: fewer person days and a different focus; nothing is saved.
  let extraDays = $state(0);
  let focus = $state(100);
  let whatIf = $state<WhatIfRow[]>([]);
  const changed = $derived(extraDays !== 0 || focus !== 100);
  $effect(() => {
    const team = app.team;
    const days = extraDays;
    const f = focus;
    if (!team || !view || (days === 0 && f === 100)) {
      whatIf = [];
      return;
    }
    let stale = false;
    const timer = setTimeout(() => {
      api
        .ForecastWhatIf(team, days, f)
        .then((rows) => {
          if (!stale) whatIf = rows;
        })
        .catch(() => {
          if (!stale) whatIf = [];
        });
    }, 150);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  });
  const whatIfById = $derived(new Map(whatIf.map((r) => [r.id, r])));

  // When is it done?
  let remaining = $state(60);
  let share = $state(50);
  let done = $state<WhenDoneView>();
  let doneProblem = $state('');
  let asked = 0;
  async function ask(): Promise<void> {
    const team = app.team;
    const id = ++asked;
    doneProblem = '';
    try {
      const result = await api.ForecastWhenDone(team, remaining, share);
      if (id === asked && team === app.team) done = result;
    } catch (e) {
      if (id === asked && team === app.team) doneProblem = String(e);
    }
  }
  $effect(() => {
    void app.team;
    asked++;
    done = undefined;
    doneProblem = '';
  });

  const next = $derived(view?.upcoming.find((r) => r.plan !== null));
  function capSource(source: string): string {
    switch (source) {
      case 'recorded': return t('recorded');
      case 'people list': return t('people list');
      case 'Trend': return t('Trend');
      case 'Calendar, absences unknown': return t('calendar, absences unknown');
      case 'expected absences': return t('expected absences');
      case 'announced absences': return t('announced absences');
      default: return source || '–';
    }
  }
  const sum = (rows: (number | null)[]): number => rows.reduce<number>((a, v) => a + (v ?? 0), 0);
  function totalRange(rows: { low: number | null; high: number | null }[], digits: number): string {
    const lo = total(rows.map((r) => r.low), digits);
    return lo === '–' ? lo : `${lo} – ${total(rows.map((r) => r.high), digits)}`;
  }
  /** The sum of a column, or "–" if a row has no value (a partial sum would mislead). */
  const total = (rows: (number | null)[], digits: number): string =>
    rows.length > 0 && rows.every((v) => v !== null) ? fmt(sum(rows), digits) : '–';
</script>

<PageHead title={t('Forecast')} lead={t('How many points the coming sprints can take, with a range.')} />

{#if problem}
  <Banner tone="bad">{problem}</Banner>
{:else if !view}
  <p class="muted">{t('Loading…')}</p>
{:else}
  {#if view.past.length === 0}
    <Banner tone="info">{t('There is no completed sprint yet. The forecast appears after the first Review.')}</Banner>
  {:else if view.fewSamples}
    <Banner tone="warn">
      {t('The range rests on only {n} sprints with a velocity. Treat it as a rough hint until there are at least 5.', { n: view.samples })}
    </Banner>
  {/if}

  <div class="stack-lg">
    <section class="card" aria-labelledby="fc-chart">
      <h2 id="fc-chart">{t('Velocity and Forecast PLAN')}</h2>
      <ForecastChart past={view.past} upcoming={view.upcoming} {whatIf} digits={view.rounding} />
      {#if view.rate !== null}
        <p class="small muted rate">
          {t('Team rate: {rate} points per person day (estimate from the last sprints).', { rate: fmt(view.rate, 2) })}
          <a href="#/help/calculations?topic=rate">{t('How the rate is measured')}</a>
        </p>
      {/if}
    </section>

    <section aria-labelledby="fc-next">
      <h2 id="fc-next">{t('Coming sprints')}</h2>
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th>{t('Sprint')}</th>
              <th class="num">{t('Capacity (PD)')}</th>
              <th>{t('Capacity from')}</th>
              <th class="num">{t('Trend')}</th>
              <th class="num">{t('Forecast PLAN')}</th>
              <th class="num">{t('Range')}</th>
              <th class="num">{t('Plannable')}</th>
              <th class="num">{t('Small items')}</th>
              {#if whatIf.length > 0}<th class="num">{t('What if')}</th>{/if}
              <th><span class="sr-only">{t('Calculation')}</span></th>
            </tr>
          </thead>
          <tbody>
            {#each view.upcoming as r (r.id)}
              {@const w = whatIfById.get(r.id)}
              <tr>
                <td>
                  <span class="data">{r.id}</span>
                  <span class="small muted data">{shortDate(r.start)} – {shortDate(r.end)}</span>
                  {#if r.state === 'current'}<span class="chip ok">{t('running')}</span>{/if}
                </td>
                <td class="num">{fmt(r.capacity)}</td>
                <td>
                  {capSource(r.capacitySource)}
                  {#if r.unsure}<span class="chip warn">{t('unsure')}</span>{/if}
                </td>
                <td class="num">{fmt(r.trend)}</td>
                <td class="num"><strong>{fmt(r.plan, view.rounding)}</strong></td>
                <td class="num">{r.low !== null ? `${fmt(r.low, view.rounding)} – ${fmt(r.high, view.rounding)}` : '–'}</td>
                <td class="num">{fmt(r.plannable, view.rounding)}</td>
                <td class="num">{fmt(r.small, view.rounding)}</td>
                {#if whatIf.length > 0}
                  <td class="num">
                    {#if w}
                      <strong class="wif">{fmt(w.forecast, view.rounding)}</strong>
                      <span class="small" class:neg={w.delta < 0}>({w.delta > 0 ? '+' : ''}{fmt(w.delta, view.rounding)})</span>
                    {:else}–{/if}
                  </td>
                {/if}
                <td class="calc-cell">
                  {#if r.plan !== null}
                    <Calc label={t('Forecast PLAN of {id}', { id: r.id })} topic="forecast">
                      {#if r.planSource === 'projection' && r.trend !== null && r.capacity !== null}
                        <div class="data">
                          {fmt(r.trend)} ÷ {fmt(view.referenceCapacity, 0)} × {fmt(r.capacity)} = {fmt((r.trend / view.referenceCapacity) * r.capacity, 2)}
                          → {fmt(r.plan, view.rounding)}
                        </div>
                        <div class="muted">
                          {t('Trend of the normalized velocity ÷ reference capacity × capacity of the sprint, rounded down.')}
                        </div>
                        {#if r.low !== null}
                          <div class="muted">{t('Range: lowest and highest normalized velocity of the last {n} sprints, same calculation.', { n: view.samples })}</div>
                        {/if}
                        <div class="muted">{t('Plannable: {share} of the plan.', { share: pct(view.roadmapShare) })}</div>
                      {:else}
                        <div class="muted">{t('The recorded commitment of the sprint, rounded down.')}</div>
                      {/if}
                    </Calc>
                  {/if}
                </td>
              </tr>
            {/each}
            {#if view.upcoming.length > 1}
              <tr class="sum">
                <td>{t('Sum of {n} sprints', { n: view.upcoming.length })}</td>
                <td class="num">{fmt(sum(view.upcoming.map((r) => r.capacity)))}</td>
                <td></td>
                <td></td>
                <td class="num">{total(view.upcoming.map((r) => r.plan), view.rounding)}</td>
                <td class="num">{totalRange(view.upcoming, view.rounding)}</td>
                <td class="num">{total(view.upcoming.map((r) => r.plannable), view.rounding)}</td>
                <td class="num">{total(view.upcoming.map((r) => r.small), view.rounding)}</td>
                {#if whatIf.length > 0}<td class="num">{fmt(sum(whatIf.map((r) => r.forecast)), view.rounding)}</td>{/if}
                <td></td>
              </tr>
            {/if}
          </tbody>
        </table>
      </div>
    </section>

    <div class="grid cols-2">
      <section class="card stack" aria-labelledby="fc-wif">
        <h2 id="fc-wif">{t('What if')}</h2>
        <p class="small muted">{t('Try other assumptions. Nothing is saved; the chart and the table show the result.')}</p>
        <div class="row">
          <div class="field">
            <label for="wi-days">{t('Additional days off per sprint (PD)')}</label>
            <input id="wi-days" class="input" type="number" min="0" step="0.5" bind:value={extraDays} />
          </div>
          <div class="field">
            <label for="wi-focus">{t('Focus (100 % = as measured)')}</label>
            <input id="wi-focus" class="input" type="number" min="0" max="200" step="5" bind:value={focus} />
          </div>
          <button class="btn" type="button" disabled={!changed} onclick={() => ((extraDays = 0), (focus = 100))}>{t('Reset')}</button>
        </div>
        {#if changed && whatIf.length > 0 && next}
          <p>
            {t('Over {n} sprints the forecast changes from {a} to {b} points.', {
              n: whatIf.length,
              a: fmt(sum(whatIf.map((r) => r.base)), view.rounding),
              b: fmt(sum(whatIf.map((r) => r.forecast)), view.rounding),
            })}
          </p>
        {/if}
      </section>

      <section class="card stack" aria-labelledby="fc-done">
        <h2 id="fc-done">{t('When is it done?')}</h2>
        <p class="small muted">{t('Simulates the coming sprints from the velocities so far. A likelihood, not a promise.')}</p>
        <form
          class="row"
          onsubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <div class="field">
            <label for="wd-rest">{t('Remaining work (points)')}</label>
            <input id="wd-rest" class="input" type="number" min="1" step="1" bind:value={remaining} />
          </div>
          <div class="field">
            <label for="wd-share">{t('Share of the forecast for it (%)')}</label>
            <input id="wd-share" class="input" type="number" min="1" max="100" step="any" bind:value={share} />
          </div>
          <button class="btn primary" type="submit">{t('Calculate')}</button>
        </form>
        <div aria-live="polite">
        {#if doneProblem}
          <Banner tone="bad">{doneProblem}</Banner>
        {:else if done && !done.available}
          <Banner tone="info">
            {#if done.remaining <= 0 || done.share <= 0}
              {t('Enter the remaining work and a share above 0 to simulate.')}
            {:else}
              {t('There are too few sprints with a velocity to simulate. At least 2 are needed.')}
            {/if}
          </Banner>
        {:else if done}
          <div>
            <p>
              {#if done.p50 && done.p85}
                {t('Done in sprint {p50} in half of the runs, in sprint {p85} in 85 % of them.', { p50: done.p50, p85: done.p85 })}
              {:else if done.p50}
                {t('Done in sprint {p50} in half of the runs; in 85 % of them not within the simulated period.', { p50: done.p50 })}
              {:else}
                {t('Not done within the simulated period.')}
              {/if}
            </p>
            <div class="tw">
              <table class="t">
                <thead>
                  <tr><th>{t('Sprint')}</th><th class="num">{t('Done by then')}</th><th><span class="sr-only">{t('Bar')}</span></th></tr>
                </thead>
                <tbody>
                  {#each done.sprints.slice(0, 10) as id, i (id)}
                    {@const c = done.cumulative[i] ?? 0}
                    <tr>
                      <td class="data">{id}</td>
                      <td class="num">{pct(c)}</td>
                      <td class="barcell"><span class="bar" style:width="{c * 100}%"></span></td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
            {#if done.trendCapacity.length > 0}
              <p class="small muted">{t('From sprint {id} on there is no people list; the average capacity of the last sprints is used.', { id: done.trendCapacity[0] ?? '' })}</p>
            {/if}
            <p class="small muted">
              {t('Expected per sprint: {n} points ({runs} runs, {samples} sprints as basis).', { n: fmt(done.perSprint), runs: fmt(done.runs, 0), samples: done.samples })}
              <Calc label={t('When is it done?')} topic="whendone">
                <div class="muted">{t('For each coming sprint a normalized velocity of the last sprints is drawn at random, scaled to the sprint capacity and multiplied by the share. The sprint in which the sum reaches the remaining work is counted over all runs.')}</div>
              </Calc>
            </p>
          </div>
        {/if}
        </div>
      </section>
    </div>

    <section aria-labelledby="fc-hist">
      <h2 id="fc-hist">{t('Completed sprints')}</h2>
      {#if view.past.length === 0}
        <p class="muted">{t('No completed sprints yet.')}</p>
      {:else}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{t('Sprint')}</th>
                <th class="num">{t('Capacity (PD)')}</th>
                <th class="num">{t('Commitment')}</th>
                <th class="num">{t('Velocity')}</th>
                <th class="num">{t('Fulfillment')}</th>
                <th class="num">{t('Normalized velocity')}</th>
                <th class="num">{t('Trend')}</th>
              </tr>
            </thead>
            <tbody>
              {#each [...view.past].reverse() as r (r.id)}
                <tr>
                  <td><span class="data">{r.id}</span> <span class="small muted data">{shortDate(r.start)} – {shortDate(r.end)}</span></td>
                  <td class="num">{fmt(r.capacity)}</td>
                  <td class="num">{fmt(r.commitment)}</td>
                  <td class="num">{fmt(r.velocity)}</td>
                  <td class="num">{pct(r.fulfillment)}</td>
                  <td class="num">{fmt(r.normalizedVelocity)}</td>
                  <td class="num">{fmt(r.trend)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>
  </div>
{/if}

<style>
  .stack-lg {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .cols-2 {
    grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr));
    align-items: start;
  }
  .rate {
    margin: 8px 0 0;
  }
  .wif {
    color: var(--c-wif);
  }
  .neg {
    color: var(--bad);
  }
  .calc-cell {
    white-space: normal;
    min-width: 36px;
  }
  .barcell {
    width: 40%;
    min-width: 120px;
  }
  .bar {
    display: block;
    height: 10px;
    border-radius: 5px;
    background: var(--c-fc);
    min-width: 2px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .stack p {
    margin: 0;
  }
</style>
