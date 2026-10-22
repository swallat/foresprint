<script lang="ts">
  import { tick } from 'svelte';
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { endTour, nextStep, previousStep, tour } from '../lib/tour/tour.svelte';

  const step = $derived(tour.flow?.steps[tour.index]);
  const last = $derived(!!tour.flow && tour.index === tour.flow.steps.length - 1);

  // Esc is seen before the palette or the side menu close on it, so that their Esc does not end the tour.
  function key(ev: KeyboardEvent): void {
    if (!tour.flow || ev.key !== 'Escape' || ev.defaultPrevented) return;
    if (app.paletteOpen || app.railOpen) return;
    void endTour();
  }

  // A new step moves the focus to the card, so that the keyboard goes on from there.
  let card = $state<HTMLElement>();
  $effect(() => {
    void tour.flow;
    void tour.index;
    void tick().then(() => card?.focus({ preventScroll: true }));
  });
</script>

<svelte:window onkeydowncapture={key} />

{#if tour.flow && step}
  <div class="guide" role="dialog" aria-label={t('Guided flow')} tabindex="-1" bind:this={card}>
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
  </div>
{/if}

<style>
  .grow {
    flex: 1;
  }
</style>
