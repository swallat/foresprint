<script lang="ts">
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { fmt, formatPeriod, pct } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { ForecastAssumption, ForecastView, WhatIfRow } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import { current, link } from '../../lib/router.svelte';
  import Icon from '../../lib/Icon.svelte';
  import ProductsOverTime from './ProductsOverTime.svelte';
  import Reports from './Reports.svelte';
  import WhenDone from './WhenDone.svelte';
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

  // What if: another sprint choice, fewer person days, a different focus and a guess for the running
  // sprint; nothing is saved unless it is saved as a prognosis.
  let wiSprint = $state('');
  let extraDays = $state(0);
  let focus = $state(100);
  let expected = $state<number | null>(null);
  let whatIf = $state<WhatIfRow[]>([]);
  let saving = $state(false);
  let pending = $state(false);
  let wiProblem = $state('');
  // a cleared number field is null
  const changed = $derived((extraDays ?? 0) !== 0 || (focus ?? 100) !== 100 || expected != null);
  const assumption = $derived<ForecastAssumption>({ sprint: wiSprint, extraAbsenceDays: extraDays ?? 0, focusPercent: focus ?? 100, expectedVelocity: expected ?? null, label: '' });
  // the choices belong to the team
  $effect(() => {
    void app.team;
    wiSprint = '';
    extraDays = 0;
    focus = 100;
    expected = null;
  });
  $effect(() => {
    const team = app.team;
    const as = assumption;
    wiProblem = '';
    if (!team || !view || !changed) {
      whatIf = [];
      pending = false;
      return;
    }
    let stale = false;
    pending = true;
    const timer = setTimeout(() => {
      api
        .ForecastWhatIf(team, as)
        .then((rows) => {
          if (!stale) (whatIf = rows), (pending = false);
        })
        .catch((e) => {
          if (!stale) (whatIf = []), (wiProblem = String(e)), (pending = false);
        });
    }, 150);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  });
  function reset(): void {
    extraDays = 0;
    focus = 100;
    expected = null;
  }
  /** Only the sprint the planning uses can be kept as a prognosis. */
  const canSave = $derived(changed && !!view && view.next !== '' && wiSprint === view.next && whatIf.length === 1 && !pending && !wiProblem);
  async function save(): Promise<void> {
    if (!app.team || saving) return;
    saving = true;
    try {
      const team = app.team;
      await api.ForecastSaveWhatIf(team, assumption);
      view = await api.Forecast(team);
      toast(t('Saved as prognosis for {id}. The planning of that sprint shows it.', { id: wiSprint }), 'ok');
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      saving = false;
    }
  }
  const whatIfById = $derived(new Map(whatIf.map((r) => [r.id, r])));

  const tabs = $derived([
    { id: 'forecast', icon: 'monitoring' as const, label: t('Forecast') },
    ...(view && view.products > 1 ? [{ id: 'products', icon: 'stacked_bar_chart' as const, label: t('Products over time') }] : []),
    { id: 'when', icon: 'event_available' as const, label: t('Analysis') },
    { id: 'reports', icon: 'ios_share' as const, label: t('Reports and export') },
  ]);
  const activeTab = $derived(tabs.some((x) => x.id === current.query.tab) ? (current.query.tab ?? 'forecast') : 'forecast');
  const next = $derived(view?.upcoming.find((r) => r.plan !== null));
  function capSource(source: string): string {
    switch (source) {
      case 'recorded': return t('recorded');
      case 'people list': return t('people list');
      case 'Trend': return t('Trend');
      case 'Calendar, absences unknown': return t('calendar, absences unknown');
      case 'expected absences': return t('absences expected');
      case 'announced absences': return t('absences announced');
      default: return source || '–';
    }
  }
  // Completed sprints: the latest few, with a filter by name and year.
  const PAST_SHORT = 6;
  let pastQuery = $state('');
  let pastYear = $state('');
  let pastAll = $state(false);
  const pastRows = $derived([...(view?.past ?? [])].reverse());
  const pastYears = $derived([...new Set(pastRows.map((r) => r.end.slice(0, 4)))].sort().reverse());
  const pastFiltered = $derived.by(() => {
    const q = pastQuery.trim().toLowerCase();
    return pastRows.filter(
      (r) => (pastYear === '' || r.end.startsWith(pastYear)) && (q === '' || r.id.toLowerCase().includes(q) || formatPeriod(r.start, r.end).toLowerCase().includes(q)),
    );
  });
  const pastFiltering = $derived(pastQuery.trim() !== '' || pastYear !== '');
  const pastShown = $derived(pastAll || pastFiltering ? pastFiltered : pastFiltered.slice(0, PAST_SHORT));
  $effect(() => {
    void app.team;
    pastQuery = '';
    pastYear = '';
    pastAll = false;
  });
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

{#if view}
  <nav class="tabs" aria-label={t('Forecast views')}>
    {#each tabs as tab (tab.id)}
      <a href={link('/forecast', {}, tab.id === 'forecast' ? {} : { tab: tab.id })} data-tour={tab.id === 'reports' ? 'forecast-reports' : undefined} class:active={activeTab === tab.id} aria-current={activeTab === tab.id ? 'page' : undefined}>
        <Icon name={tab.icon} size={18} />{tab.label}
      </a>
    {/each}
  </nav>
{/if}

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

  {#if activeTab === 'products'}
    <ProductsOverTime />
  {:else if activeTab === 'when'}
    <WhenDone roadmapShare={view.roadmapShare} />
  {:else if activeTab === 'reports'}
    <Reports />
  {:else}
  <div class="stack-lg">
    <section class="card" aria-labelledby="fc-chart" data-tour="forecast-chart">
      <h2 id="fc-chart">{t('Velocity and Forecast PLAN')}</h2>
      <ForecastChart past={view.past} upcoming={view.upcoming} {whatIf} digits={view.rounding} />
      {#if view.rate !== null}
      <p class="small muted rate">{t('The normalized velocity exists only for completed sprints. For coming sprints it is carried on as a trend; Forecast PLAN = rate × capacity of the sprint.')}</p>
        <p class="small muted rate">
          {#if view.rateFixed}
            {t('Fixed factor of the team: {rate} points per person day.', { rate: fmt(view.rate, 2) })}
          {:else}
            {t('Team rate: {rate} points per person day (estimate from the last sprints).', { rate: fmt(view.rate, 2) })}
          {/if}
          <a href="#/help/calculations?topic=rate">{t('How the rate is measured')}</a>
        </p>
      {/if}
    </section>

    <section aria-labelledby="fc-next" data-tour="forecast-table">
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
              <th><span class="sr-only">{t('Calculation of the number')}</span></th>
            </tr>
          </thead>
          <tbody>
            {#each view.upcoming as r (r.id)}
              {@const w = whatIfById.get(r.id)}
              <tr>
                <td>
                  <span class="data">{r.id}</span>
                  <span class="small muted data">{formatPeriod(r.start, r.end)}</span>
                  {#if r.state === 'current'}<span class="chip ok">{t('in progress')}</span>{/if}
                </td>
                <td class="num">{fmt(r.capacity)}</td>
                <td>
                  {capSource(r.capacitySource)}
                  {#if r.unsure}<span class="chip warn">{t('unsure')}</span>{/if}
                </td>
                <td class="num">{fmt(r.trend)}</td>
                <td class="num"><strong>{fmt(r.plan, view.rounding)}</strong></td>
                <td class="num">{r.low !== null ? `${fmt(r.low, view.rounding)} – ${fmt(r.high, view.rounding)}` : '–'}</td>
                <td class="num" title={r.carryIn > 0 ? t('After {n} points of carry-over.', { n: fmt(r.carryIn) }) : undefined}>
                  {fmt(r.plannable, view.rounding)}{r.carryIn > 0 ? '*' : ''}
                </td>
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
                      {:else}
                        <div class="muted">{t('The recorded commitment of the sprint, rounded down.')}</div>
                      {/if}
                      <div class="data">
                        {t('Plannable: ({plan} − {carry}) × {share}', { plan: fmt(r.plan, view.rounding), carry: fmt(r.carryIn), share: pct(view.roadmapShare) })} → {fmt(r.plannable, view.rounding)}
                      </div>
                      {#if r.carryIn > 0}
                        <div class="muted">
                          {r.carryAssumed ? t('Carry-over of {n} points is an assumption of the running sprint.', { n: fmt(r.carryIn) }) : t('Carry-over of {n} points continues in this sprint.', { n: fmt(r.carryIn) })}
                        </div>
                      {/if}
                      {#if r.overbooked}<div class="muted">{t('The carry-over alone exceeds the plan; nothing is plannable.')}</div>{/if}
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
      <section class="card stack" aria-labelledby="fc-wif" data-tour="forecast-whatif">
        <h2 id="fc-wif">{t('What if')}</h2>
        <p class="small muted">{t('Try other assumptions. Nothing is saved unless you keep it as a prognosis; the chart shows the result as a diamond.')}</p>
        <div class="row">
          <div class="field">
            <label for="wi-sprint">{t('Sprint')}</label>
            <select id="wi-sprint" class="input" bind:value={wiSprint}>
              <option value="">{t('All coming sprints')}</option>
              {#each view.upcoming.filter((r) => r.plan !== null) as r (r.id)}<option value={r.id}>{r.id}</option>{/each}
            </select>
          </div>
          <div class="field">
            <label for="wi-days">{t('Additional days off per sprint (PD)')}</label>
            <input id="wi-days" class="input" type="number" min="0" step="0.5" bind:value={extraDays} />
          </div>
          {#if view.running}
            <div class="field">
              <label for="wi-exp">{t('Expected velocity of {id}', { id: view.running })}</label>
              <input id="wi-exp" class="input" type="number" min="0" step="any" placeholder={view.runningCommitment !== null ? fmt(view.runningCommitment, 1) : ''} bind:value={expected} />
            </div>
          {/if}
        </div>
        <div class="field">
          <label for="wi-focus">{t('Focus (100 % = as measured): {n} %', { n: fmt(focus ?? 100, 0) })}</label>
          <input id="wi-focus" type="range" min="0" max="150" step="5" bind:value={focus} />
        </div>
        <div class="row">
          <button class="btn" type="button" disabled={!changed} onclick={reset}>{t('Reset')}</button>
          <button class="btn primary" type="button" disabled={!canSave || saving} onclick={save}>{t('Save as prognosis')}</button>
        </div>
        {#if changed && !canSave && view.next}
          <p class="small muted">{t('Only {id}, the sprint after the running one, can be kept as a prognosis. Choose it above.', { id: view.next })}</p>
        {/if}
        {#if wiProblem}<Banner tone="bad">{wiProblem}</Banner>{/if}
        <p aria-live="polite">
          {#if changed && whatIf.length > 0 && next}
            {t('Over {n} sprints the forecast changes from {a} to {b} points.', {
              n: whatIf.length,
              a: fmt(sum(whatIf.map((r) => r.base)), view.rounding),
              b: fmt(sum(whatIf.map((r) => r.forecast)), view.rounding),
            })}
          {/if}
        </p>
      </section>
    </div>

    <section aria-labelledby="fc-hist" data-tour="forecast-history">
      <h2 id="fc-hist">{t('Completed sprints')}</h2>
      {#if view.past.length === 0}
        <p class="muted">{t('No completed sprints yet.')}</p>
      {:else}
        {#if pastRows.length > PAST_SHORT}
          <div class="row past-filter">
            <div class="field">
              <label for="past-q">{t('Search sprint')}</label>
              <input id="past-q" class="input" type="search" placeholder={t('Name or date')} bind:value={pastQuery} />
            </div>
            <div class="field">
              <label for="past-year">{t('Year')}</label>
              <select id="past-year" class="input" bind:value={pastYear}>
                <option value="">{t('All years')}</option>
                {#each pastYears as y (y)}<option value={y}>{y}</option>{/each}
              </select>
            </div>
            {#if pastFiltering}
              <button class="btn" type="button" onclick={() => ((pastQuery = ''), (pastYear = ''))}>{t('Reset filter')}</button>
            {/if}
          </div>
        {/if}
        {#if pastShown.length === 0}
          <p class="muted">{t('No completed sprint fits this filter.')}</p>
        {:else}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{t('Sprint')}</th>
                <th class="num">{t('Capacity (PD)')}</th>
                <th class="num">{t('Commitment')}</th>
                <th class="num">{t('Velocity')}</th>
                <th class="num">{t('Fulfillment ratio')}</th>
                <th class="num">{t('Normalized velocity')}</th>
              </tr>
            </thead>
            <tbody>
              {#each pastShown as r (r.id)}
                <tr>
                  <td><span class="data">{r.id}</span> <span class="small muted data">{formatPeriod(r.start, r.end)}</span></td>
                  <td class="num">{fmt(r.capacity)}</td>
                  <td class="num">{fmt(r.commitment)}</td>
                  <td class="num">{fmt(r.velocity)}</td>
                  <td class="num">{pct(r.fulfillment)}</td>
                  <td class="num">{fmt(r.normalizedVelocity)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {/if}
        {#if !pastFiltering && pastRows.length > PAST_SHORT}
          <button class="btn past-toggle" type="button" aria-expanded={pastAll} onclick={() => (pastAll = !pastAll)}>
            <Icon name={pastAll ? 'keyboard_arrow_up' : 'keyboard_arrow_down'} size={18} />
            {pastAll ? t('Show fewer') : t('Show all {n} sprints', { n: pastRows.length })}
          </button>
        {:else if pastFiltering}
          <p class="small muted">{t('{n} of {total} sprints', { n: pastFiltered.length, total: pastRows.length })}</p>
        {/if}
      {/if}
    </section>
  </div>
  {/if}
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
  .past-filter {
    margin-bottom: 12px;
    align-items: end;
  }
  .past-toggle {
    margin-top: 12px;
  }
  .stack p {
    margin: 0;
  }
</style>
