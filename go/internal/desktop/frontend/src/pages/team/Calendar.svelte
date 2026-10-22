<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { fmtDay } from '../../lib/team/format';
  import type { CalendarRow, CalendarView, NamingPreview } from '../../lib/types.team';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  const COUNT = 8;
  let view = $state<CalendarView>();
  let failed = $state('');

  let pattern = $state('{JJJJ}.{NN}');
  let from = $state('');
  let history = $state<'keep' | 'all'>('keep');
  let preview = $state<NamingPreview>();
  let patternInput = $state<HTMLInputElement>();
  let run = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const openRows = $derived((view?.rows ?? []).filter((r) => r.state === 'open' || r.state === 'planned'));
  const tokens = ['{JJJJ}', '{JJ}', '{NN}', '{N}', '{LFD}', '{Q}', '{MM}', '{KW}'];
  const tokenHint = (token: string) =>
    ({
      '{JJJJ}': t('Year, 4 digits'),
      '{JJ}': t('Year, 2 digits'),
      '{NN}': t('Number in the year, 2 digits'),
      '{N}': t('Number in the year'),
      '{LFD}': t('Running number'),
      '{Q}': t('Quarter'),
      '{MM}': t('Month'),
      '{KW}': t('Calendar week'),
    })[token] ?? token;

  async function load() {
    try {
      view = await api.Calendar(app.team, COUNT);
      failed = '';
      if (view.pattern && pattern === '{JJJJ}.{NN}') pattern = view.pattern;
    } catch (e) {
      failed = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    void app.team;
    load();
  });

  // The preview follows the form after a short pause; an older answer never overwrites a newer one.
  $effect(() => {
    const args = [pattern, from, history === 'all'] as const;
    void view;
    clearTimeout(timer);
    if (!args[0].trim()) {
      preview = undefined;
      return;
    }
    const mine = ++run;
    timer = setTimeout(async () => {
      try {
        const next = await api.NamingPreview(app.team, args[0], args[1], args[2], COUNT);
        if (mine === run) preview = next;
      } catch {
        if (mine === run) preview = undefined;
      }
    }, 150);
    return () => clearTimeout(timer);
  });

  function insert(token: string) {
    const input = patternInput;
    const a = input?.selectionStart ?? pattern.length;
    const b = input?.selectionEnd ?? a;
    pattern = pattern.slice(0, a) + token + pattern.slice(b);
    queueMicrotask(() => {
      input?.focus();
      input?.setSelectionRange(a + token.length, a + token.length);
    });
  }

  async function afterChange(result: { view: CalendarView; moved: number; undo: number }, message: string) {
    view = result.view;
    toast(message, 'ok', result.undo ? { label: t('Undo'), run: () => void undo(result.undo) } : undefined);
  }

  async function undo(token: number) {
    try {
      await api.Undo(app.team, token);
      toast(t('Change undone.'), 'ok');
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
    }
    await load();
  }

  async function setLast(row: CalendarRow, value: string) {
    if (!value || value === row.last) return load();
    try {
      const result = await api.SaveLastDays(app.team, [{ id: row.id, last: value }], COUNT);
      const now = result.view.rows.find((r) => r.id === row.id);
      await afterChange(
        result,
        t('Last day {date}, {days} working days. {moved} following sprints moved.', {
          date: fmtDay(value),
          days: now?.workdays ?? 0,
          moved: result.moved,
        }),
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
    }
  }

  async function rename(row: CalendarRow, value: string) {
    const name = value.trim();
    if (!name || name === row.id) return load();
    try {
      const result = await api.RenameSprint(app.team, row.id, name, COUNT);
      await afterChange(result, t('Sprint {old} is now called {new}. References in tickets and minutes move along.', { old: row.id, new: name }));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
    }
  }

  async function apply() {
    try {
      const result = await api.ApplyNaming(app.team, pattern, from, history === 'all', COUNT);
      from = '';
      await afterChange(result, t('{count} sprints renamed. The pattern names the sprints that follow.', { count: result.moved }));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
    }
  }

  const stateLabel = (r: CalendarRow) =>
    ({ finished: t('finished'), running: t('running'), open: t('open'), planned: t('planned') })[r.state];
  const stateClass = (r: CalendarRow) => ({ finished: '', running: 'ok', open: '', planned: 'fc' })[r.state];
  const lead = $derived(
    view
      ? t('Name, start, end and working days of each sprint. Country {country} and region {region} decide the holidays. Finished sprints are locked.', {
          country: view.country || '–',
          region: view.region || '–',
        })
      : '',
  );
</script>

<PageHead title={t('Sprint calendar')} {lead} />

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{:else if !view}
  <p class="muted">{t('Loading…')}</p>
{:else}
  <section class="card naming" aria-labelledby="naming-h">
    <div class="row head">
      <h2 id="naming-h">{t('Naming of the sprints')}</h2>
      {#if view.pattern}<span class="chip small data" title={t('Pattern in use')}>{view.pattern}</span>{/if}
    </div>
    <p class="small muted">
      {t('One pattern for the whole team. Placeholders are replaced for each sprint, everything else stays as typed. The number in the year starts again at 1 with the first sprint that begins in the new year.')}
    </p>
    <div class="grid cols-2">
      <div class="stack">
        <div class="field">
          <label for="nm-pattern">{t('Pattern')}</label>
          <input id="nm-pattern" class="input data" placeholder="{'{JJJJ}'}.{'{NN}'}" bind:value={pattern} bind:this={patternInput} />
        </div>
        <div class="row chips" role="group" aria-label={t('Insert a placeholder')}>
          {#each tokens as token (token)}
            <button type="button" class="chip filter" title={tokenHint(token)} onclick={() => insert(token)}>{token}</button>
          {/each}
        </div>
        <p class="small muted">
          {#each tokens as token, i (token)}{i ? ' · ' : ''}<span class="data">{token}</span> {tokenHint(token)}{/each}.
        </p>
        <div class="field narrow">
          <label for="nm-from">{t('Applies from sprint')}</label>
          <select id="nm-from" class="input" bind:value={from}>
            <option value="">{openRows[0] ? `${openRows[0].id} (${t('first open sprint')})` : t('first open sprint')}</option>
            {#each openRows.slice(1) as r (r.id)}<option value={r.id}>{r.id} ({t('Start')} {fmtDay(r.start)})</option>{/each}
          </select>
        </div>
        <fieldset class="stack radios">
          <legend class="sr-only">{t('Earlier sprints')}</legend>
          <label class="opt">
            <input type="radio" name="nm-hist" value="keep" bind:group={history} />
            <span><strong>{t('Earlier sprints keep their name')}</strong><br /><span class="small muted">{t('Recommended. Minutes, tags and history stay as they are.')}</span></span>
          </label>
          <label class="opt">
            <input type="radio" name="nm-hist" value="all" bind:group={history} />
            <span>
              <strong>{t('Rename running and finished sprints too')}</strong><br />
              <span class="small muted">{t('References in tickets, minutes and history move along. Git tags and file names of old minutes stay as they are.')}</span>
            </span>
          </label>
        </fieldset>
      </div>
      <div>
        <div class="small muted lbl">{t('Preview')}</div>
        {#if preview && preview.rows.length}
          <div class="tw">
            <table class="t">
              <thead><tr><th><span class="sr-only">{t('Locked')}</span></th><th>{t('Start')}</th><th>{t('Until now')}</th><th>{t('New')}</th></tr></thead>
              <tbody>
                {#each preview.rows as r (r.index)}
                  <tr class:muted={!r.changes}>
                    <td>{#if r.locked}<Icon name="lock" size={16} />{/if}</td>
                    <td class="data">{fmtDay(r.start)}</td>
                    <td class="data">{r.old}</td>
                    <td class="data">{#if r.changes}<strong>{r.new}</strong>{:else}<span class="muted">{t('stays')}</span>{/if}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
        {#if preview?.problem}
          <Banner tone="bad">{t('Unknown placeholder {name}.', { name: preview.problem })}</Banner>
        {:else if preview?.duplicate}
          <Banner tone="bad">{t('The pattern gives double names ({name}). A number such as {NN}, {LFD} or {KW} makes them unique.', { name: preview.duplicate })}</Banner>
        {:else if preview?.noNumber}
          <Banner tone="warn">{t('Without a number in the pattern the names are not unique.')}</Banner>
        {/if}
        <div class="row apply">
          <button class="btn primary" type="button" disabled={!preview || !!preview.problem || !!preview.duplicate || !pattern.trim()} onclick={apply}>
            <Icon name="edit" />{preview && preview.count ? t('Rename {count} sprints', { count: preview.count }) : t('Use pattern for the next sprints')}
          </button>
        </div>
      </div>
    </div>
  </section>

  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th>{t('Sprint')}</th>
          <th>{t('Start')}</th>
          <th>{t('Last day')}</th>
          <th class="num">{t('Working days')}</th>
          <th>{t('Days off')}</th>
          <th>{t('Status')}</th>
        </tr>
      </thead>
      <tbody>
        {#each view.rows as r (r.id)}
          <tr>
            <td>
              {#if r.locked || !r.saved}
                <span class="data">{r.id}</span>
              {:else}
                <input class="input data name" value={r.id} aria-label={t('Sprint name')} onchange={(e) => rename(r, e.currentTarget.value)} />
              {/if}
            </td>
            <td class="data">{fmtDay(r.start)}</td>
            <td>
              {#if r.locked}
                <span class="data">{fmtDay(r.last)}</span> <Icon name="lock" size={16} />
              {:else}
                <input class="input data" type="date" min={r.start} value={r.last} aria-label={t('Last day of {id}', { id: r.id })} onchange={(e) => setLast(r, e.currentTarget.value)} />
              {/if}
            </td>
            <td class="num data">
              {r.workdays}
              <Calc label={t('Working days of {id}', { id: r.id })} topic="workdays">
                {t('Working days = calendar days minus weekends. Holidays are deducted in the capacity, not here.')}
              </Calc>
            </td>
            <td class="small">
              {#if r.holidays.length}
                {#each r.holidays as h, i (h.date)}{i ? ', ' : ''}{fmtDay(h.date)} {h.name}{/each}
              {:else}
                <span class="muted">{t('none')}</span>
              {/if}
            </td>
            <td><span class="chip {stateClass(r)}">{stateLabel(r)}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <div class="grid cols-2 below">
    <div class="card">
      <h2>{t('Change the last day')}</h2>
      <p class="small muted">{t('A new last day moves start and end of all following sprints; their length stays. Working days are calculated again from weekends.')}</p>
    </div>
    <div class="card">
      <h2>{t('Rename a single sprint')}</h2>
      <p class="small muted">{t('For exceptions directly in the table. The name shows in tickets, minutes and history; all references move along. It has to be unique, and the pattern above does not apply to this sprint.')}</p>
    </div>
  </div>
{/if}

<style>
  .naming {
    margin-bottom: 16px;
  }
  .head {
    align-items: baseline;
  }
  .head h2 {
    margin: 0;
    flex: 1;
  }
  .chips {
    gap: 6px;
    flex-wrap: wrap;
  }
  .narrow {
    max-width: 280px;
  }
  .opt {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .opt input {
    margin-top: 3px;
  }
  .radios {
    border: 0;
    padding: 0;
    margin: 0;
    gap: 8px;
  }
  .lbl {
    margin-bottom: 6px;
  }
  .apply {
    margin-top: 12px;
  }
  .name {
    width: 140px;
  }
  .below {
    margin-top: 16px;
  }
  input[type='date'] {
    width: 160px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
