<script lang="ts">
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { pct } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import type { FulfillmentView } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';

  /** Fewer sprints with a value than this show no mean (same limit as the Go analysis). */
  const MIN_SAMPLES = 3;
  /** A mean below this says the commitment is regularly set too high. */
  const LOW = 0.9;

  let view = $state<FulfillmentView>();
  let problem = $state('');

  $effect(() => {
    const team = app.team;
    let stale = false;
    view = undefined;
    problem = '';
    if (!team) return;
    api
      .ForecastFulfillment(team)
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

  const enough = $derived(!!view && view.samples >= MIN_SAMPLES && view.average !== null);
  const low = $derived(enough && (view?.average ?? 1) < LOW);
</script>

<section class="card stack" aria-labelledby="fc-ful">
  <h2 id="fc-ful">{t('Fulfillment')}</h2>
  {#if problem}
    <Banner tone="bad">{problem}</Banner>
  {:else if view && view.rows.length === 0}
    <p class="muted">{t('No completed sprints yet.')}</p>
  {:else if view}
    {#if enough}
      <p>
        {t('Mean of the last {n} sprints: {avg}. Lowest {min}, highest {max}.', { n: view.samples, avg: pct(view.average), min: pct(view.min), max: pct(view.max) })}
        {#if view.trend !== null}{t('Trend: {n}.', { n: pct(view.trend) })}{/if}
      </p>
      {#if low}
        <Banner tone="warn">{t('The sprints deliver clearly less than committed. The commitment is probably set too high.')}</Banner>
      {/if}
    {:else}
      <Banner tone="info">{t('Too few sprints with a commitment and a velocity for a mean. At least {n} are needed.', { n: MIN_SAMPLES })}</Banner>
    {/if}
    <div class="tw">
      <table class="t">
        <thead>
          <tr><th scope="col">{t('Sprint')}</th><th scope="col" class="num">{t('Fulfillment ratio')}</th><th scope="col"><span class="sr-only">{t('Bar')}</span></th></tr>
        </thead>
        <tbody>
          {#each view.rows as r (r.sprint)}
            <tr>
              <td class="data">{r.sprint}</td>
              <td class="num">{pct(r.value)}</td>
              <td class="barcell">
                {#if r.value !== null}<span class="bar" style:width="{Math.min(r.value, 1.5) / 1.5 * 100}%"></span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="small muted">
      {t('Sprints without a commitment or velocity are left out, not counted as 0 %.')}
      <Calc label={t('Fulfillment')} topic="fulfillment">
        <div class="muted">{t('Fulfillment = velocity / commitment per sprint. The mean is the plain mean of these ratios over the last sprints of the window. Work added later counts as done, so a sprint can lie above 100 %.')}</div>
      </Calc>
    </p>
  {/if}
</section>

<style>
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
