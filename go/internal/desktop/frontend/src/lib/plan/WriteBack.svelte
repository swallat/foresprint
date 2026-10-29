<script lang="ts">
  // Write the planned sprint back to the tracker (optional, off unless the team switched it on).
  // Nothing happens before the person asks: first the preview shows every move, each can be left
  // out, then one button writes. What went through can be taken back in this session.
  import { api } from '../api';
  import { app, toast } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { PlanSprint, WritePreview, WriteResult } from '../types.plan';

  interface Props {
    d: PlanSprint;
  }
  let { d }: Props = $props();

  let preview = $state<WritePreview | null>(null);
  let result = $state<WriteResult | null>(null);
  let left = $state<string[]>([]);
  let busy = $state(false);
  const tracker = $derived(d.trackerName || t('the tracker'));

  /** The sprint in view; the preview is dropped when it changes, not when the data reloads. */
  let shown = '';
  $effect(() => {
    const key = `${app.team}/${d.sprint}`;
    if (key === shown) return;
    shown = key;
    preview = null;
    result = null;
    left = [];
  });

  async function run<T>(call: () => Promise<T>): Promise<T | undefined> {
    busy = true;
    try {
      return await call();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }

  async function show(): Promise<void> {
    result = null;
    const p = await run(() => api.PlanWritePreview(app.team, d.sprint));
    if (p) {
      preview = p;
      left = [];
    }
  }

  async function write(): Promise<void> {
    const r = await run(() => api.PlanWriteApply(app.team, d.sprint, preview!.moves.map((m) => m.key).filter((k) => !left.includes(k))));
    if (!r) return;
    result = r;
    preview = null;
    if (r.error) toast(t('Writing stopped: {error}', { error: r.error }), 'bad');
    else toast(t('{n} tickets moved in {tracker}.', { n: r.done.length, tracker }), 'ok');
  }

  async function undo(): Promise<void> {
    const r = await run(() => api.PlanWriteUndo(app.team, d.sprint));
    if (!r) return;
    result = r;
    toast(r.error ? t('Taking back stopped: {error}', { error: r.error }) : t('{n} tickets put back.', { n: r.done.length }), r.error ? 'bad' : 'ok');
  }

  const toggle = (key: string, on: boolean) => (left = on ? left.filter((k) => k !== key) : [...left, key]);
  const place = (name: string) => name || t('Backlog');
  const count = $derived(preview ? preview.moves.filter((m) => !left.includes(m.key)).length : 0);
  const canUndo = $derived(result?.canUndo ?? preview?.canUndo ?? d.writeUndo);
</script>

<div class="card gapb" id="writeback" data-tour="plan-writeback">
  <h2>{t('Write the sprint to {tracker}', { tracker })}</h2>
  <p class="small muted">
    {t('Moves tickets between sprints of {tracker} and changes nothing else. Nothing is written before you press the button, and you can take it back afterwards.', { tracker })}
  </p>

  {#if !preview}
    <div class="row">
      <button class="btn" type="button" id="wb-show" disabled={busy || (d.stage !== 'planned' && d.stage !== 'current')} onclick={show}>
        <Icon name="preview" />{t('Show what would change')}
      </button>
      {#if canUndo}
        <button class="btn" type="button" id="wb-undo" disabled={busy} onclick={undo}><Icon name="undo" />{t('Take back what was written')}</button>
      {/if}
      {#if (d.stage !== 'planned' && d.stage !== 'current')}<span class="small muted">{t('Start the sprint first.')}</span>{/if}
    </div>
  {:else}
    {#each preview.problems as p (p)}
      <div class="banner warn" role="alert"><Icon name="warning" /><div class="grow">{p}</div></div>
    {/each}
    {#if preview.moves.length}
      <table class="t">
        <thead><tr><th></th><th>{t('Ticket')}</th><th>{t('From')}</th><th>{t('Destination')}</th></tr></thead>
        <tbody>
          {#each preview.moves as m (m.key)}
            <tr>
              <td><input type="checkbox" checked={!left.includes(m.key)} onchange={(e) => toggle(m.key, e.currentTarget.checked)} aria-label={t('Write {key}', { key: m.key })} /></td>
              <td><span class="data">{m.key}</span> {m.title}</td>
              <td>{m.fromKnown ? place(m.from) : t('unknown')}</td>
              <td>{place(m.to)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else if !preview.problems.length}
      <p class="muted small">{t('Nothing to write: the tracker and the plan agree.')}</p>
    {/if}
    <div class="row gap">
      <button class="btn primary" type="button" id="wb-write" disabled={busy || count === 0} onclick={write}>
        <Icon name="upload" />{t('Write {n} changes to {tracker}', { n: count, tracker })}
      </button>
      <button class="btn" type="button" disabled={busy} onclick={() => (preview = null)}>{t('Cancel')}</button>
    </div>
  {/if}

  {#if result}
    <p class="small gap" role="status">
      {result.error ? t('{done} of {all} changes written. {error}', { done: result.done.length, all: result.done.length + result.failed.length, error: result.error }) : t('{n} changes written.', { n: result.done.length })}
    </p>
  {/if}
</div>

<style>
  .gapb {
    margin-bottom: 16px;
  }
  .gap {
    margin-top: 8px;
  }
</style>
