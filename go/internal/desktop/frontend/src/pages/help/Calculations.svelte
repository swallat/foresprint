<script lang="ts">
  import { tick } from 'svelte';
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import { fmt, pct } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import { current } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { ForecastView } from '../../lib/types.forecast';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  // The team's own numbers fill the examples; without a forecast the formulas stand alone.
  let view = $state<ForecastView>();
  $effect(() => {
    const team = app.team;
    view = undefined;
    if (!team) return;
    api
      .Forecast(team)
      .then((v) => {
        if (team === app.team) view = v;
      })
      .catch(() => {});
  });

  const topic = $derived(current.query.topic ?? '');
  const ref = $derived(view?.referenceCapacity ?? 40);
  const last = $derived(view?.past.at(-1));
  const next = $derived(view?.upcoming.find((r) => r.plan !== null && r.planSource === 'projection'));

  // A link with ?topic=... opens that section and scrolls to it.
  let opened = $state<Record<string, boolean>>({ rate: true });
  $effect(() => {
    const id = topic;
    if (!id) return;
    opened[id] = true;
    void tick().then(() => document.getElementById(`calc-${id}`)?.scrollIntoView({ block: 'start' }));
  });
</script>

{#snippet section(id: string, title: string, lead: string, body: import('svelte').Snippet)}
  <details class="card calc" id="calc-{id}" bind:open={opened[id]}>
    <summary>
      <span class="h">{title}</span>
      <span class="lead">{lead}</span>
    </summary>
    <div class="body stack">{@render body()}</div>
  </details>
{/snippet}

{#snippet example(text: string)}
  <p class="ex"><span class="small muted">{t('With your numbers')}</span> <span class="data">{text}</span></p>
{/snippet}

<PageHead title={t('Calculations')} lead={t('Every formula once, in full. Next to a number, the calculator icon shows the short version.')} />

<div class="stack-lg">
  {#snippet capacityBody()}
    <p>{t('Capacity is counted in person days (PD) and frozen at the Review. For a coming sprint it is calculated from the people list.')}</p>
    <p class="formula data">{t('(working days of the calendar − holidays) × FTE − confirmed absences − overhead')}</p>
    <ul>
      <li>{t('Holidays and the work week come from the team country and region; people can differ.')}</li>
      <li>{t('Overhead (Scrum events and the like) is a share of the capacity or a fixed number of days per full-time person.')}</li>
      <li>{t('Absences are periods only. Announced ones count as soon as they are entered; for later sprints the average of the last sprints is expected.')}</li>
      <li>{t('Without a people list, the capacity follows the trend of the last sprints and is marked as unsure.')}</li>
    </ul>
    {#if last?.capacity != null}{@render example(t('{id}: {n} PD', { id: last.id, n: fmt(last.capacity) }))}{/if}
  {/snippet}
  {@render section('capacity', t('Capacity'), t('Person days available in a sprint.'), capacityBody)}

  {#snippet rateBody()}
    <h3>{t('Where the numbers come from')}</h3>
    <p>{t('The rate is measured only in finished sprints, at the Review.')}</p>
    <ul>
      <li>{t('Velocity is the sum of the estimates at sprint start of all items that are done at sprint end, including items pulled in later. Unfinished items count zero. Without tickets, it is the value entered at the Review.')}</li>
      <li>{t('Capacity is the person days frozen at the Review: calendar minus holidays, times FTE, minus confirmed absences, minus overhead.')}</li>
      <li>{t('The rate of a sprint is velocity ÷ capacity.')}</li>
      <li>{t('The calculation runs on the normalized velocity = rate × reference capacity (a team setting). The mean or trend over the window is taken of that number; the rate used for the forecast and for conversions is that mean (or trend) ÷ reference capacity, which equals the mean of the rates.')}</li>
      <li>{t('Sprints without velocity or without capacity do not count towards the window. The first forecast comes from 3 sprints; with fewer, a notice is shown instead of an estimated rate.')}</li>
    </ul>
    <h3>{t('What the rate is used for')}</h3>
    <ul>
      <li>{t('The Forecast PLAN of coming sprints.')}</li>
      <li>{t('Points to person days for contingents and production time.')}</li>
      <li>{t('Story points to person days when the unit conversion is “from velocity”. A fixed factor replaces the rate only for that conversion.')}</li>
    </ul>
    <p class="small muted">{t('Planned work uses the forecast rate of its sprint; done work uses the actual rate. Every converted value is an estimate and is labelled so.')}</p>
    {#if view?.rate != null}{@render example(t('Rate {rate} points per person day; reference capacity {ref} PD', { rate: fmt(view.rate, 2), ref: fmt(ref, 0) }))}{/if}
  {/snippet}
  {@render section('rate', t('Rate'), t('Points the team finishes per person day.'), rateBody)}

  {#snippet forecastBody()}
    <p class="formula data">{t('Forecast PLAN = trend of the normalized velocity ÷ reference capacity × capacity of the sprint, rounded down')}</p>
    <ul>
      <li>{t('The trend is flat (mean of the window), rising or falling, as set in the forecast settings. With thin history only the mean is used and the sprint is marked.')}</li>
      <li>{t('The range uses the lowest and the highest normalized velocity of the last sprints instead of the trend, with the same calculation. It needs at least 2 sprints; below 5 it is only a rough hint.')}</li>
      <li>{t('For a sprint that is already planned, the recorded commitment replaces the projection and is marked as actual.')}</li>
    </ul>
    {#if next?.trend != null && next.capacity != null && next.plan != null}
      {@render example(`${next.id}: ${fmt(next.trend)} ÷ ${fmt(ref, 0)} × ${fmt(next.capacity)} = ${fmt((next.trend / ref) * next.capacity, 2)} → ${fmt(next.plan, 0)}`)}
    {/if}
  {/snippet}
  {@render section('forecast', t('Forecast PLAN and range'), t('How many points a coming sprint can take.'), forecastBody)}

  {#snippet plannableBody()}
    <p class="formula data">{t('Plannable = (Forecast PLAN − carried-over rest) × plannable share, rounded down; the remainder is small items')}</p>
    <ul>
      <li>{t('The plannable share is a team setting (roadmap share). The carried-over rest is what continues in this sprint from the last one.')}</li>
      <li>{t('The small items are not planned ticket by ticket; they absorb the day-to-day work.')}</li>
    </ul>
    {#if view && next?.plan != null}{@render example(`${next.id}: ${fmt(next.plan, 0)} × ${pct(view.roadmapShare)} → ${fmt(next.plannable, 0)} + ${fmt(next.small, 0)}`)}{/if}
  {/snippet}
  {@render section('plannable', t('Plannable and small items'), t('The part of the plan for planned work.'), plannableBody)}

  {#snippet whendoneBody()}
    <p>{t('For each coming sprint a normalized velocity of the last sprints is drawn at random, scaled to the capacity of that sprint and multiplied by the share of the forecast that is available. The sprint in which the sum reaches the remaining work is counted over 10,000 runs.')}</p>
    <ul>
      <li>{t('“Half of the runs” and “85 % of the runs” are the sprints in which the work is done that often. They are likelihoods, not commitments.')}</li>
      <li>{t('The draw uses a fixed seed, so the same data gives the same answer.')}</li>
      <li>{t('Beyond the people list, the average capacity of the last sprints is used, because a capacity trend is unstable over many sprints.')}</li>
    </ul>
  {/snippet}
  {@render section('whendone', t('When is it done?'), t('A likelihood from a simulation, not a promise.'), whendoneBody)}
</div>

<style>
  .stack-lg {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    max-width: 860px;
  }
  .calc summary {
    cursor: pointer;
    display: grid;
    gap: 2px;
    list-style: none;
  }
  .calc summary::-webkit-details-marker {
    display: none;
  }
  .calc summary:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 4px;
    border-radius: 4px;
  }
  .h {
    font: 600 16px/24px var(--font-ui);
  }
  .lead {
    color: var(--text-muted);
  }
  .body {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .body :global(p),
  .body :global(ul),
  .body :global(h3) {
    margin: 0;
  }
  .body :global(h3) {
    font: 600 14px/20px var(--font-ui);
  }
  .body :global(ul) {
    padding-left: 20px;
    display: grid;
    gap: 4px;
  }
  .formula {
    padding: 8px 10px;
    background: var(--surface-2);
    border-radius: var(--r-ctl);
  }
  .ex {
    padding: 8px 10px;
    border: 1px dashed var(--border-control);
    border-radius: var(--r-ctl);
  }
</style>
