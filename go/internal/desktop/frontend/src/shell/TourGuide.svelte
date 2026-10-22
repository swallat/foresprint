<script lang="ts">
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { endTour, nextStep, previousStep, tour } from '../lib/tour/tour.svelte';

  const step = $derived(tour.flow?.steps[tour.index]);
  const last = $derived(!!tour.flow && tour.index === tour.flow.steps.length - 1);

  function key(ev: KeyboardEvent): void {
    if (tour.flow && ev.key === 'Escape' && !ev.defaultPrevented) void endTour();
  }
</script>

<svelte:window onkeydown={key} />

{#if tour.flow && step}
  <aside class="guide" role="dialog" aria-label={t('Guided flow')} aria-live="polite">
    <div class="step">{tour.flow.id} · {tour.flow.title()} · {tour.index + 1}/{tour.flow.steps.length}</div>
    <p>{step.text()}</p>
    {#if tour.unmarked}<p class="small muted">{t('The element for this step is not on the page right now.')}</p>{/if}
    <div class="row">
      <button class="btn" type="button" onclick={() => void previousStep()} disabled={tour.index === 0}><Icon name="arrow_back" />{t('Back')}</button>
      <button class="btn primary" type="button" onclick={() => void nextStep()}>
        {last ? t('Finish') : t('Next')}<Icon name={last ? 'check' : 'arrow_forward'} />
      </button>
      <span class="grow"></span>
      <button class="btn" type="button" onclick={() => void endTour()}><Icon name="close" />{t('End tour')}</button>
    </div>
  </aside>
{/if}

<style>
  .grow {
    flex: 1;
  }
</style>
