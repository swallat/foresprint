<script lang="ts">
  // The official start of a sprint: a sprint runs when the team starts it, not when its first
  // day comes, and it stays running until its Review is closed. The start day may be earlier than
  // the day of the click, so a late start or a mistake can be put right.
  import { api } from '../api';
  import { app, refreshSprints, toast } from '../app.svelte';
  import { fmtDay } from '../team/format';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    sprint: string;
    /** The planned first day (YYYY-MM-DD). */
    start: string;
    /** The day after the last day (YYYY-MM-DD). */
    end: string;
    /** The day it counts as started from; empty before the start. */
    startedOn: string;
    /** The first day has come and the sprint is not started. */
    due: boolean;
    /** The sprint is running (started, Review not closed): its start can be moved or taken back. */
    running: boolean;
    onchange?: () => void | Promise<void>;
  }
  let { sprint, start, end, startedOn, due, running, onchange }: Props = $props();

  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const today = iso(new Date());

  let asking = $state(false);
  let day = $state('');
  let busy = $state(false);
  let failed = $state('');

  // The start of a sprint whose last day is over cannot be taken back: it would count as never started.
  const canTakeBack = $derived(end > today);
  const valid = $derived(day >= start && day <= today);

  function ask(): void {
    day = startedOn || start;
    failed = '';
    asking = true;
  }

  async function run(call: () => Promise<unknown>, done: string): Promise<void> {
    busy = true;
    failed = '';
    try {
      await call();
      asking = false;
      await refreshSprints();
      await onchange?.();
      toast(done, 'ok');
    } catch (e) {
      failed = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  const startIt = () => run(() => api.StartSprint(app.team, sprint, day), t('Sprint {id} started.', { id: sprint }));
  const takeBack = () => run(() => api.WithdrawSprintStart(app.team, sprint), t('The start of sprint {id} is taken back.', { id: sprint }));
</script>

{#if due || running}
  <div class="banner" class:warn={due && !asking} data-tour="sprint-start">
    <Icon name="play_arrow" />
    <div class="grow">
      {#if running}
        <strong>{t('Sprint {id} runs since {day}.', { id: sprint, day: fmtDay(startedOn || start) })}</strong>
        <span class="small muted">{t('It stays running until its Review is closed.')}</span>
      {:else}
        <strong>{t('Sprint {id} is not started yet.', { id: sprint })}</strong>
        <span class="small muted">{t('Planning and Review can go on. Start the sprint when you are ready; it then counts from the day you choose.')}</span>
      {/if}
      {#if asking}
        <div class="row">
          <label>
            <span class="small">{t('Started on')}</span>
            <input type="date" bind:value={day} min={start} max={today} />
          </label>
          <button class="btn primary" type="button" disabled={busy || !valid} onclick={startIt}>
            <Icon name="play_arrow" />{running ? t('Change start day') : t('Start sprint')}
          </button>
          <button class="btn" type="button" disabled={busy} onclick={() => (asking = false)}>{t('Cancel')}</button>
        </div>
        {#if day && !valid}<p class="small">{t('The start day lies between the first day of the sprint and today.')}</p>{/if}
      {/if}
      {#if failed}<p class="small" role="alert">{failed}</p>{/if}
    </div>
    {#if !asking}
      {#if running}
        <button class="btn" type="button" disabled={busy} onclick={ask}>{t('Change start day')}</button>
        {#if canTakeBack}<button class="btn" type="button" disabled={busy} onclick={takeBack}>{t('Take start back')}</button>{/if}
      {:else}
        <button class="btn primary" type="button" disabled={busy} onclick={ask}><Icon name="play_arrow" />{t('Start sprint')}</button>
      {/if}
    {/if}
  </div>
{/if}
