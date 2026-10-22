<script lang="ts">
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import { flows } from '../../lib/tour/flows';
  import { startTour } from '../../lib/tour/tour.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;
</script>

<PageHead
  title={t('Guided flows')}
  lead={t('Short walk-throughs of the everyday flows. They always run on the invented demo team, never on your data.')}
/>

<ul class="flows">
  {#each flows as f (f.id)}
    <li class="card">
      <div class="grow">
        <h2><span class="data">{f.id}</span> {f.title()}</h2>
        <p class="muted">{f.summary()}</p>
        <p class="small muted">{f.steps.length === 1 ? t('1 step') : t('{n} steps', { n: f.steps.length })}</p>
      </div>
      <button class="btn primary" type="button" onclick={() => void startTour(f.id)}><Icon name="play_arrow" />{t('Start')}</button>
    </li>
  {/each}
</ul>

<style>
  .flows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 12px;
    max-width: 760px;
  }
  .flows li {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  h2 {
    margin: 0 0 4px;
    font-size: 16px;
    line-height: 24px;
  }
  p {
    margin: 0;
  }
</style>
