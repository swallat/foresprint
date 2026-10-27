<script lang="ts">
  // One absence period in a dialog: first and last day, announced or confirmed, delete.
  // Only dates are stored, never a reason or kind of absence (data protection).
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { changed, isLocked, touchesFinished } from '../../lib/team/absences';
  import type { AbsencePeriod } from '../../lib/types.team';

  interface Props {
    name: string;
    /** The period as saved, or the proposal for a new one. */
    period: AbsencePeriod;
    isNew: boolean;
    openFrom: string;
    onsave: (next: AbsencePeriod) => void | Promise<void>;
    onremove: () => void | Promise<void>;
    onclose: () => void;
  }
  let { name, period, isNew, openFrom, onsave, onremove, onclose }: Props = $props();

  // svelte-ignore state_referenced_locally
  let from = $state(period.from);
  // svelte-ignore state_referenced_locally
  let to = $state(period.to);
  // svelte-ignore state_referenced_locally
  let confirmed = $state(period.confirmed);
  let first = $state<HTMLInputElement>();

  const locked = $derived(!isNew && isLocked(period, openFrom));
  // A first day inside finished sprints is only refused when it was changed here.
  const next = $derived(changed({ ...period, from: period.from }, from === period.from ? { to, confirmed } : { from, to, confirmed }, openFrom));
  const problem = $derived(
    !from || !to
      ? t('Enter the first and the last day.')
      : to < from
        ? t('The last day lies before the first day.')
        : openFrom && from < openFrom && from !== period.from
          ? t('The first day lies in a finished sprint. Finished sprints stay as they are.')
          : '',
  );

  $effect(() => {
    first?.focus();
  });

  function keys(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<div class="scrim" role="presentation" onclick={onclose}></div>
<div class="dialog card" role="dialog" aria-modal="true" aria-labelledby="ad-title" tabindex="-1" onkeydown={keys}>
  <h2 id="ad-title">{isNew ? t('New absence: {name}', { name }) : t('Absence: {name}', { name })}</h2>
  {#if locked}
    <p class="small muted"><Icon name="history" size={14} /> {t('Lies in finished sprints. They stay as they are.')}</p>
  {:else if !isNew && touchesFinished(period, openFrom)}
    <p class="small muted"><Icon name="info" size={14} /> {t('Days in finished sprints stay as they are; a change only reaches the open sprints.')}</p>
  {/if}
  <div class="fields">
    <label>
      <span class="small muted">{t('First day')}</span>
      <input class="input data" type="date" bind:value={from} disabled={locked} bind:this={first} />
    </label>
    <label>
      <span class="small muted">{t('Last day')}</span>
      <input class="input data" type="date" bind:value={to} disabled={locked} />
    </label>
  </div>
  <label class="check">
    <input type="checkbox" bind:checked={confirmed} disabled={locked} />
    {t('Confirmed (otherwise announced)')}
  </label>
  {#if problem}<p class="small bad">{problem}</p>{/if}
  <div class="row end">
    {#if !isNew}
      <button class="btn danger" type="button" disabled={locked} onclick={onremove}><Icon name="delete" />{t('Delete')}</button>
    {/if}
    <span class="grow"></span>
    <button class="btn ghost" type="button" onclick={onclose}>{t('Cancel')}</button>
    <button class="btn primary" type="button" disabled={locked || problem !== '' || !next} onclick={() => next && onsave(next)}>
      <Icon name="check" />{t('Apply')}
    </button>
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--text) 40%, transparent);
    z-index: 70;
  }
  .dialog {
    position: fixed;
    z-index: 71;
    left: 50%;
    top: 20vh;
    transform: translateX(-50%);
    width: min(440px, calc(100vw - 32px));
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  h2 {
    margin: 0;
  }
  .fields {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .check {
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  .bad {
    color: var(--bad);
    margin: 0;
  }
  .end {
    align-items: center;
    gap: 8px;
  }
  .grow {
    flex: 1;
  }
</style>
