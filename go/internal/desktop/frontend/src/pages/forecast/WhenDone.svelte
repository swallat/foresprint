<script lang="ts">
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { fmt, formatDate, formatPeriod, pct } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { current } from '../../lib/router.svelte';
  import type { WhenDoneView, WhenProject } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';

  let { roadmapShare }: { roadmapShare: number } = $props();

  let projects = $state<WhenProject[]>([]);
  let project = $state('');
  let remaining = $state(60);
  let share = $state(50);
  let done = $state<WhenDoneView>();
  let problem = $state('');
  let asked = 0;

  const chosen = $derived(projects.find((p) => p.id === project));
  const wanted = $derived(current.query.project ?? '');

  // The projects of the team; a link from a project selects it and asks right away.
  $effect(() => {
    const team = app.team;
    let stale = false;
    projects = [];
    project = '';
    done = undefined;
    problem = '';
    asked++;
    share = Math.round(roadmapShare * 100);
    if (!team) return;
    api
      .ForecastWhenProjects(team)
      .then((list) => {
        if (stale) return;
        projects = list;
        if (wanted && list.some((p) => p.id === wanted)) void pick(wanted);
      })
      .catch((e) => {
        if (!stale) problem = String(e);
      });
    return () => {
      stale = true;
    };
  });

  /** Choosing a project fills the form with its open scope and the usual share, then asks. */
  async function pick(id: string): Promise<void> {
    project = id;
    const p = projects.find((x) => x.id === id);
    if (p) {
      share = Math.round(roadmapShare * 100);
      if (p.openScope !== null) {
        remaining = p.openScope;
        await ask();
      } else {
        asked++;
        done = undefined;
      }
    }
  }

  async function ask(): Promise<void> {
    const team = app.team;
    const id = ++asked;
    problem = '';
    try {
      const result = await api.ForecastWhenDone(team, remaining, share, project);
      if (id === asked && team === app.team) done = result;
    } catch (e) {
      if (id === asked && team === app.team) problem = String(e);
    }
  }

  const lightText = (l: string, end: string): string =>
    l === 'ok'
      ? t('On track: done by {end} in 85 % of the runs.', { end })
      : l === 'warn'
        ? t('Tight: done by {end} in half of the runs, but not in 85 % of them.', { end })
        : t('At risk: done by {end} in fewer than half of the runs.', { end });
  const lightIcon = (l: string) => (l === 'ok' ? 'check_circle' : l === 'warn' ? 'error' : 'cancel');
  const period = (v: WhenDoneView, id: string): string => {
    const i = v.sprints.indexOf(id);
    const s = v.starts[i];
    const e = v.ends[i];
    return s && e ? formatPeriod(s, e) : '';
  };
</script>

<section class="card stack" aria-labelledby="fc-done" data-tour="forecast-analysis">
  <h2 id="fc-done">{t('When is it done?')}</h2>
  <p class="small muted">{t('Simulates the coming sprints from the velocities so far. A likelihood, not a promise.')}</p>
  <form
    class="row"
    onsubmit={(e) => {
      e.preventDefault();
      void ask();
    }}
  >
    {#if projects.length > 0}
      <div class="field">
        <label for="wd-project">{t('Project')}</label>
        <select id="wd-project" class="input" value={project} onchange={(e) => void (e.currentTarget.value ? pick(e.currentTarget.value) : ((project = ''), ask()))}>
          <option value="">{t('No project, enter the work by hand')}</option>
          {#each projects as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
        </select>
      </div>
    {/if}
    <div class="field">
      <label for="wd-rest">{t('Remaining work (points)')}</label>
      <input id="wd-rest" class="input" type="number" min="0" step="any" bind:value={remaining} />
    </div>
    <div class="field">
      <label for="wd-share">{t('Share of the forecast for it (%)')}</label>
      <input id="wd-share" class="input" type="number" min="1" max="100" step="any" bind:value={share} />
    </div>
    <div class="field">
      <label for="wd-slide">{t('Share as a slider')}</label>
      <input id="wd-slide" type="range" min="5" max="100" step="5" bind:value={share} />
    </div>
    <button class="btn primary" type="submit">{t('Calculate')}</button>
  </form>
  {#if chosen}
    <p class="small muted">
      {#if chosen.openScope === null}
        {t('The project has no open scope yet. Enter the remaining work by hand.')}
      {:else}
        {t('Open scope of the project: {n} points in {tickets} open tickets. The share is the usual roadmap share; change it if the project gets more or less.', { n: fmt(chosen.openScope), tickets: chosen.open })}
      {/if}
    </p>
  {/if}
  <div>
    {#if problem}
      <div aria-live="polite"><Banner tone="bad">{problem}</Banner></div>
    {:else if done && !done.available}
      <div aria-live="polite"><Banner tone="info">
        {#if done.remaining <= 0 || done.share <= 0}
          {t('Enter the remaining work and a share above 0 to simulate.')}
        {:else}
          {t('There are too few sprints with a velocity to simulate. At least 2 are needed.')}
        {/if}
      </Banner></div>
    {:else if done}
      <div class="stack">
        <p aria-live="polite">
          {#if done.p50}
            {t('Probably done in sprint {p50}.', { p50: done.p50 })}
            {#if done.earliest && done.p85}
              {t('Earliest in sprint {earliest}, latest in sprint {p85} (85 % of the runs).', { earliest: done.earliest, p85: done.p85 })}
            {:else if done.earliest}
              {t('Earliest in sprint {earliest}; in 85 % of the runs not within the simulated period.', { earliest: done.earliest })}
            {/if}
          {:else}
            {t('Not done within the simulated period.')}
          {/if}
        </p>
        {#if done.projectEnd}
          <p aria-live="polite">
            <span class="chip wd-light {done.light}"><Icon name={lightIcon(done.light)} size={16} />{lightText(done.light, formatDate(done.projectEnd))}</span>
          </p>
        {:else if done.projectName}
          <p class="small muted">{t('The project has no end date, so there is nothing to compare with.')}</p>
        {/if}
        <div class="tw">
          <table class="t">
            <thead>
              <tr><th scope="col">{t('Sprint')}</th><th scope="col">{t('Period')}</th><th scope="col" class="num">{t('Done by then')}</th><th scope="col"><span class="sr-only">{t('Bar')}</span></th></tr>
            </thead>
            <tbody>
              {#each done.sprints.slice(0, 12) as id, i (id)}
                {@const c = done.cumulative[i] ?? 0}
                <tr>
                  <td class="data">{id}</td>
                  <td class="data small">{period(done, id)}</td>
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

<style>
  .wd-light {
    height: auto;
    white-space: normal;
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
