<script lang="ts">
  import { api } from '../api';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import { fmtDay } from '../team/format';
  import type { CalendarChange, CalendarPreview, CalendarResult, ChangeNote, ChangeKind, ChangeMode, ChangeNaming } from '../types.team';
  import Banner from '../ui/Banner.svelte';
  import { timeline } from './timeline';

  // Change of the sprint calendar (start, last day or removal): shows before writing what moves,
  // what falls away and what the sprints with a file are called afterwards.
  let {
    kind,
    id,
    date,
    count,
    onclose,
    ondone,
  }: {
    kind: ChangeKind;
    id: string;
    date: string;
    count: number;
    onclose: () => void;
    ondone: (result: CalendarResult, message: string) => void | Promise<void>;
  } = $props();

  let mode = $state<ChangeMode>(kind === 'remove' ? 'keep' : 'shift');
  let naming = $state<ChangeNaming>('keep');
  let preview = $state<CalendarPreview>();
  let failed = $state('');
  let busy = $state(false);
  let first = $state<HTMLButtonElement>();
  let run = 0;

  const change = (): CalendarChange => ({ kind, id, date, mode, naming });

  $effect(() => {
    void mode;
    void naming;
    const mine = ++run;
    api
      .PreviewCalendarChange(app.team, change(), count)
      .then((p) => {
        if (mine === run) {
          preview = p;
          failed = '';
        }
      })
      .catch((e) => {
        if (mine === run) failed = e instanceof Error ? e.message : String(e);
      });
  });

  $effect(() => {
    first?.focus();
  });

  const title = $derived(
    kind === 'remove'
      ? t('Remove sprint {id}', { id })
      : kind === 'rhythm'
        ? t('Restore the rhythm from {id}', { id })
        : kind === 'start' ? t('Change the start of {id}', { id }) : t('Change the last day of {id}', { id }),
  );
  const asksMode = $derived(kind !== 'remove' && kind !== 'rhythm' && !!preview && !preview.forced && !preview.problem);
  const lanes = $derived(preview ? timeline(preview.rows) : { before: [], after: [] });
  const ok = $derived(!!preview && !preview.problem && !busy);

  function note(n: ChangeNote): string {
    const d = Math.abs(n.days);
    switch (n.kind) {
      case 'moved':
        return n.days > 0 ? t('{days} days later', { days: d }) : t('{days} days earlier', { days: d });
      case 'longer':
        return t('{days} days longer', { days: d });
      case 'shorter':
        return t('{days} days shorter', { days: d });
      case 'starts-later':
        return t('starts {days} days later', { days: d });
      case 'starts-earlier':
        return t('starts {days} days earlier', { days: d });
      case 'gone':
        return t('falls away');
      default:
        return t('was {name}', { name: n.from });
    }
  }
  const tone = (n: ChangeNote) => (n.kind === 'gone' ? 'bad' : 'warn');

  async function apply() {
    if (!ok) return;
    busy = true;
    try {
      const result = await api.ApplyCalendarChange(app.team, change(), count);
      const message =
        kind === 'remove'
          ? t('Sprint {id} removed.', { id })
          : kind === 'rhythm'
            ? t('Rhythm restored from {id}. {moved} sprints changed.', { id, moved: result.moved })
            : t('{moved} sprints changed.', { moved: result.moved });
      await ondone(result, message);
    } catch (e) {
      failed = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  function keys(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<div class="scrim" role="presentation" onclick={onclose}></div>
<div class="dialog card" role="dialog" aria-modal="true" aria-labelledby="cd-title" tabindex="-1" onkeydown={keys}>
  <div class="row head">
    <h2 id="cd-title">{title}</h2>
    <button class="btn ghost" type="button" aria-label={t('Close')} onclick={onclose}><Icon name="close" /></button>
  </div>
  {#if failed}<Banner tone="bad">{failed}</Banner>{/if}
  {#if preview}
    {#if preview.problem}
      <Banner tone="bad">{preview.problem}</Banner>
    {:else}
      {#if kind === 'rhythm'}
        <p class="small muted">{t('{id} keeps its start. It and all following sprints get the regular length again and follow each other without a gap.', { id })}</p>
      {:else if preview.via}
        <p class="small muted">
          {kind === 'remove'
            ? t('The days of {id} go to the sprint before, {via}.', { id, via: preview.via })
            : t('The start of {id} is the day after the last day of {via}. That last day is what changes.', { id, via: preview.via })}
        </p>
      {:else if preview.forced}
        <p class="small muted">{t('The sprint before is finished and locked. {id} and all following sprints move by the difference.', { id })}</p>
      {/if}
      {#if asksMode}
        <fieldset class="stack radios">
          <legend>{t('What happens to the following sprints?')}</legend>
          <div class="row opts">
            <label class="opt">
              <input type="radio" name="cd-mode" value="shift" bind:group={mode} />
              <span><strong>{t('Following sprints move along')}</strong><br /><span class="small muted">{t('Each later sprint starts later or earlier by the same number of days and keeps its length. For correcting a mistake.')}</span></span>
            </label>
            <label class="opt">
              <input type="radio" name="cd-mode" value="keep" bind:group={mode} />
              <span><strong>{t('Following sprints keep their dates')}</strong><br /><span class="small muted">{t('Sprints that are covered fall away, one that is cut starts later. For a break such as Christmas.')}</span></span>
            </label>
          </div>
        </fieldset>
      {/if}
      {#if preview.lost.length}
        <Banner tone="bad">
          {t('Sprints with a file fall away: {ids}. Their planned days and typed absence days are lost. Absence periods stay, they belong to dates. Earmarks move to {target}. You can undo this.', { ids: preview.lost.join(', '), target: preview.target || t('the next sprint') })}
        </Banner>
      {:else if preview.free.length}
        <Banner tone="warn">{t('Sprints without a file fall away: {ids}. Nothing is lost.', { ids: preview.free.join(', ') })}</Banner>
      {/if}
      {#if preview.namingChoice}
        <fieldset class="stack radios">
          <legend>{t('Names of sprints with a file')}</legend>
          <div class="row opts">
            <label class="opt">
              <input type="radio" name="cd-naming" value="keep" bind:group={naming} />
              <span><strong>{t('Names stay (recommended)')}</strong><br /><span class="small muted">{t('The count may have a gap. Files, minutes and tracker names still match. Sprints without a file keep counting on.')}</span></span>
            </label>
            <label class="opt">
              <input type="radio" name="cd-naming" value="renumber" bind:group={naming} />
              <span><strong>{t('Close the gap')}</strong><br /><span class="small muted">{t('Sprints with a file are numbered again by the pattern. Files and references move along, names in the tracker do not.')}</span></span>
            </label>
          </div>
        </fieldset>
        {#if naming === 'renumber'}<Banner tone="warn">{t('In the tracker these sprints keep their old names, so matching by name no longer finds them.')}</Banner>{/if}
      {/if}
      <div class="timeline" aria-hidden="true">
        {#each [{ label: t('Before'), bars: lanes.before }, { label: t('After'), bars: lanes.after }] as lane (lane.label)}
          <div class="lane">
            <span class="small muted">{lane.label}</span>
            <div class="track">
              {#each lane.bars as b, i (i)}<div class="seg" class:gone={b.gone} style="left: {b.left}%; width: {b.width}%">{b.id}</div>{/each}
            </div>
          </div>
        {/each}
      </div>
      <div class="tw">
        <table class="t">
          <thead><tr><th>{t('Sprint')}</th><th>{t('Start')}</th><th>{t('Last day')}</th><th class="num">{t('Working days')}</th><th>{t('Result')}</th></tr></thead>
          <tbody>
            {#each preview.rows as r (r.old)}
              <tr class:gone={r.gone}>
                <td class="data">{r.id}</td>
                <td class="data">{fmtDay(r.start)}</td>
                <td class="data">{fmtDay(r.last)}</td>
                <td class="num data">{r.gone ? '–' : r.workdays}</td>
                <td>{#each r.notes as n, i (i)}<span class="chip small {tone(n)}">{note(n)}</span> {/each}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if !failed}
    <p class="muted">{t('Loading…')}</p>
  {/if}
  <div class="row end">
    <button class="btn" type="button" bind:this={first} onclick={onclose}>{t('Cancel')}</button>
    <button class="btn primary" type="button" disabled={!ok} onclick={apply}>
      <Icon name={kind === 'remove' ? 'delete' : 'check'} />{kind === 'remove' ? t('Remove sprint') : t('Apply')}
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
    top: 6vh;
    transform: translateX(-50%);
    width: min(780px, calc(100vw - 32px));
    max-height: 88vh;
    overflow: auto;
    box-shadow: var(--shadow);
    display: grid;
    gap: 12px;
  }
  .head {
    align-items: center;
  }
  .head h2 {
    flex: 1;
    margin: 0;
  }
  .radios {
    border: 0;
    padding: 0;
    margin: 0;
    gap: 8px;
  }
  legend {
    font-weight: 600;
    padding: 0;
    margin-bottom: 6px;
  }
  .opts {
    gap: 8px;
    align-items: stretch;
  }
  .opt {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    flex: 1 1 260px;
    min-width: 0;
    padding: 9px;
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
  }
  .opt input {
    margin-top: 3px;
  }
  .timeline {
    display: grid;
    gap: 4px;
  }
  .lane {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr);
    gap: 8px;
    align-items: center;
  }
  .track {
    position: relative;
    height: 26px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .seg {
    position: absolute;
    top: 2px;
    bottom: 2px;
    display: flex;
    align-items: center;
    padding: 0 4px;
    font-size: 11px;
    overflow: hidden;
    white-space: nowrap;
    background: var(--primary-weak);
    color: var(--text);
    border-left: 2px solid var(--primary);
    border-radius: 3px;
  }
  .seg.gone {
    background: var(--bad-weak);
    border-left-color: var(--bad);
    text-decoration: line-through;
  }
  tr.gone td {
    text-decoration: line-through;
    color: var(--text-muted);
  }
  .end {
    justify-content: flex-end;
  }
</style>
