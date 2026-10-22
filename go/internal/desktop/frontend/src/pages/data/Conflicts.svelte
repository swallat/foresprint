<script lang="ts">
  import { api } from '../../lib/api';
  import { announce, app, refreshStatus, save, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { Conflict, ConflictEntry } from '../../lib/types.data';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import DataTabs from './DataTabs.svelte';
  import { decisionsOf, entryKey, openCount, shortFile } from './util';

  let { params }: PageProps = $props();
  void params;

  let conflicts = $state<Conflict[]>([]);
  let choices = $state<Record<string, 'ours' | 'theirs'>>({});
  let working = $state(false);
  let confirm = $state<'theirs' | 'abort' | undefined>();
  let failed = $state('');
  let seq = 0;

  const open = $derived(openCount(conflicts, choices));
  const total = $derived(conflicts.reduce((n, c) => n + c.entries.length, 0));
  const decided = $derived(app.status.storage === 'decided');
  const key = $derived(`${app.rev}:${app.status.data?.conflicts}:${app.status.storage}`);

  async function load(): Promise<void> {
    const mine = ++seq;
    try {
      const list = await api.Conflicts();
      if (mine !== seq) return;
      conflicts = list;
      failed = '';
    } catch (e) {
      if (mine !== seq) return;
      // Keep what is shown and the choices made; say that the list could not be read.
      failed = String(e);
      return;
    }
    // Keep only the choices that still belong to an entry.
    const known = new Set(conflicts.flatMap((c) => c.entries.map((e) => entryKey(c.file, e))));
    choices = Object.fromEntries(Object.entries(choices).filter(([k]) => known.has(k)));
  }

  $effect(() => {
    void key;
    void load();
  });

  function choose(file: string, entry: ConflictEntry, choice: 'ours' | 'theirs'): void {
    choices[entryKey(file, entry)] = choice;
  }

  const result = (entry: ConflictEntry, choice: 'ours' | 'theirs' | undefined): string | undefined => {
    if (!choice) return undefined;
    const missing = choice === 'ours' ? entry.mineMissing : entry.theirsMissing;
    return missing ? t('removed') : choice === 'ours' ? entry.mine : entry.theirs;
  };

  async function applyAndSave(): Promise<void> {
    working = true;
    try {
      const r = await api.ResolveConflicts(decisionsOf(conflicts, choices));
      await refreshStatus();
      if (r.outcome === 'decided') {
        await save();
      } else {
        announce(r);
      }
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
      await load();
    }
  }

  async function takeTheirs(): Promise<void> {
    confirm = undefined;
    working = true;
    try {
      announce(await api.TakeTheirs());
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
      await load();
    }
  }

  async function abortMerge(): Promise<void> {
    confirm = undefined;
    working = true;
    try {
      app.status = await api.AbortMerge();
      if (app.status.storage === 'conflict' || app.status.storage === 'decided') {
        toast(t('The merge could not be cancelled. Your own work stays.'), 'bad');
      } else {
        toast(t('The merge is cancelled. Your own work stays.'), 'ok');
      }
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
      await load();
    }
  }
</script>

<PageHead title={t('Conflicts')} lead={t('The same value was changed by two people. You decide per value; nothing is lost.')} />
<DataTabs />

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{/if}
{#if conflicts.length === 0 && !failed}
  <div class="card empty">
    <Icon name="check_circle" size={32} />
    {#if decided}
      <h2>{t('All conflicts are decided')}</h2>
      <p class="muted">{t('Save finishes the merge and shares the result with the team.')}</p>
      <button class="btn primary" type="button" disabled={!!app.busy} onclick={save}><Icon name="save" />{t('Save')}</button>
    {:else}
      <h2>{t('No conflicts')}</h2>
      <p class="muted">{t('All changes could be merged automatically.')}</p>
      <a class="btn" href={link('/data')}>{t('Back to the overview')}</a>
    {/if}
  </div>
{:else if conflicts.length > 0}
  <Banner tone="bad">
    {t('The status stays red until every value is decided. All other pages stay usable.')}
  </Banner>

  <div class="stack list">
    {#each conflicts as c (c.file)}
      <section class="card" aria-label={shortFile(c.file, app.team)}>
        <div class="row head">
          <strong class="grow">{c.whole ? t('Whole file') : t('Values')}</strong>
          <span class="chip data">{shortFile(c.file, app.team)}</span>
        </div>
        {#if c.mineDeleted || c.theirsDeleted}
          <p class="muted small">
            {c.mineDeleted ? t('You deleted this file.') : t('Someone else deleted this file.')}
          </p>
        {/if}
        {#each c.entries as e (entryKey(c.file, e))}
          {@const choice = choices[entryKey(c.file, e)]}
          <div class="entry" data-entry>
            <div class="row"><strong>{e.label}</strong></div>
            <div class="grid cols-3 sides">
              {#if e.hasBefore}
                <div class="side muted-bg">
                  <div class="small muted">{t('Before')}</div>
                  <pre class="data">{e.before}</pre>
                  <div class="small muted">{t('common state')}</div>
                </div>
              {/if}
              <div class="side" class:picked={choice === 'ours'}>
                <div class="small muted">{t('Mine')}</div>
                <pre class="data">{e.mineMissing ? t('(removed)') : e.mine}</pre>
                <div class="small muted">{t('from you')}</div>
              </div>
              <div class="side" class:picked={choice === 'theirs'}>
                <div class="small muted">{t('From others')}</div>
                <pre class="data">{e.theirsMissing ? t('(removed)') : e.theirs}</pre>
                <div class="small muted">{t('from someone else')}</div>
              </div>
            </div>
            <div class="row" role="group" aria-label={t('Decision for {label}', { label: e.label })}>
              <button class="chip filter" class:on={choice === 'ours'} type="button" aria-pressed={choice === 'ours'} onclick={() => choose(c.file, e, 'ours')}>
                {#if choice === 'ours'}<Icon name="check" />{/if}{t('Keep mine')}
              </button>
              <button class="chip filter" class:on={choice === 'theirs'} type="button" aria-pressed={choice === 'theirs'} onclick={() => choose(c.file, e, 'theirs')}>
                {#if choice === 'theirs'}<Icon name="check" />{/if}{t('Take from others')}
              </button>
              <span class="grow"></span>
              <span class="small">
                {#if choice}{t('Result:')} <strong class="data">{result(e, choice)}</strong>
                {:else}<span class="muted">{t('not decided yet')}</span>{/if}
              </span>
            </div>
          </div>
        {/each}
      </section>
    {/each}
  </div>

  <div class="bar">
    {#if open === 0}
      <span class="chip ok"><Icon name="check_circle" />{t('All decided')}</span>
    {:else}
      <span class="chip warn"><Icon name="pending" />{t('{open} of {total} open', { open, total })}</span>
    {/if}
    <span class="grow"></span>
    <button class="btn ghost" type="button" disabled={working || !!app.busy} onclick={() => (confirm = 'abort')}>{t('Cancel the merge')}</button>
    <button class="btn danger" type="button" disabled={working || !!app.busy} onclick={() => (confirm = 'theirs')}><Icon name="delete" />{t('Discard mine')}</button>
    <button class="btn primary" type="button" disabled={working || open > 0 || !!app.busy} onclick={applyAndSave}>
      <Icon name="save" />{t('Apply decisions and save')}
    </button>
  </div>
  {#if confirm}
    <div class="confirm" role="alertdialog" aria-label={t('Confirm')}>
      <Icon name="warning" />
      <div class="grow">
        {#if confirm === 'theirs'}
          {t('Discard mine takes the value of the others for every entry. Only your change to these values is lost.')}
        {:else}
          {t('Cancel the merge and go back to your own state? Your own work stays; the changes of others come with the next Refresh.')}
        {/if}
      </div>
      <button class="btn danger" type="button" disabled={working || !!app.busy} onclick={confirm === 'theirs' ? takeTheirs : abortMerge}>
        {confirm === 'theirs' ? t('Discard mine') : t('Cancel the merge')}
      </button>
      <button class="btn" type="button" onclick={() => (confirm = undefined)}>{t('Back')}</button>
    </div>
  {/if}
{/if}

<style>
  .empty {
    text-align: center;
    padding: 32px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }
  .empty h2,
  .empty p {
    margin: 0;
  }
  .list {
    gap: 12px;
  }
  .head {
    margin-bottom: 4px;
  }
  .entry {
    padding: 12px 0;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .sides {
    gap: 8px;
  }
  .side {
    border: 1px solid var(--border);
    border-radius: var(--r-card);
    padding: 8px 12px;
    min-width: 0;
  }
  .side.picked {
    border: 2px solid var(--primary);
    padding: 7px 11px;
  }
  .muted-bg {
    background: var(--surface-2);
  }
  pre {
    margin: 2px 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 16px;
    line-height: 24px;
    max-height: 160px;
    overflow: auto;
  }
  .bar {
    position: sticky;
    bottom: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 16px;
    padding: 8px 0;
    background: var(--bg);
  }
  .confirm {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 10px 12px;
    border-radius: var(--r-ctl);
    background: var(--warn-weak);
    color: var(--warn);
  }
  .confirm .grow {
    flex: 1;
    min-width: 240px;
    color: var(--text);
  }
</style>
