<script lang="ts">
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import { fmt } from '../../lib/format';
  import { t } from '../../lib/i18n.svelte';
  import type { ProductsOverTime } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';

  let data = $state<ProductsOverTime>();
  let problem = $state('');

  $effect(() => {
    const team = app.team;
    let stale = false;
    data = undefined;
    problem = '';
    if (!team) return;
    api
      .ForecastProducts(team)
      .then((v) => {
        if (!stale) data = v;
      })
      .catch((e) => {
        if (!stale) problem = String(e);
      });
    return () => {
      stale = true;
    };
  });

  const measures = [
    { key: 'standard', label: () => t('Standard') },
    { key: 'preplanned', label: () => t('Pre-planned') },
    { key: 'planned', label: () => t('Planned') },
    { key: 'done', label: () => t('Done') },
  ] as const;
  const signed = (n: number): string => `${n > 0 ? '+' : ''}${fmt(n)}`;
</script>

{#if problem}
  <Banner tone="bad">{problem}</Banner>
{:else if !data}
  <p class="muted">{t('Loading…')}</p>
{:else if !data.enabled}
  <Banner tone="info">{t('This tab appears when the team looks after more than one product.')}</Banner>
{:else}
  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th rowspan="2" scope="col">{t('Product')}</th>
          {#each data.sprints as id (id)}
            <th class="num" colspan="4" scope="colgroup" class:now={id === data.current}>
              {id}{#if id === data.current}<span class="chip ok">{t('in progress')}</span>{/if}
            </th>
          {/each}
          <th class="num" colspan="2" scope="colgroup">{t('Product balance')}</th>
        </tr>
        <tr>
          {#each data.sprints as id (id)}
            {#each measures as m (m.key)}<th class="num sub" scope="col">{m.label()}</th>{/each}
          {/each}
          <th class="num sub">{t('Difference')}</th>
          <th class="num sub">{t('Sprints')}</th>
        </tr>
      </thead>
      <tbody>
        {#each data.lines as line (line.id)}
          <tr>
            <th scope="row" class="rowh">{line.name}</th>
            {#each line.cells as cell, i (i)}
              {#each measures as m (m.key)}<td class="num">{fmt(cell[m.key])}</td>{/each}
            {/each}
            <td class="num" class:neg={line.difference < 0}><strong>{line.sprints > 0 ? signed(line.difference) : '–'}</strong></td>
            <td class="num">
              {line.sprints}
              {#if line.missing > 0}<span class="small muted">({t('{n} without Done value', { n: line.missing })})</span>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="small muted">{t('Balance = Done − Standard over the sprints with a Done value. A missing value counts as neither 0 nor the standard.')}</p>
{/if}

<style>
  .rowh {
    font-weight: 400;
  }
  .sub {
    font-weight: 400;
  }
  .neg {
    color: var(--bad);
  }
  .now {
    background: var(--forecast-weak);
  }
  p {
    margin: 0 0 8px;
  }
</style>
