<script lang="ts">
  import { api } from '../../lib/api';
  import { app, refresh, refreshStatus, save, showNewData, toast } from '../../lib/app.svelte';
  import { openExternal } from '../../lib/external';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { Change, UnsavedFile, ValueChange, Version } from '../../lib/types.data';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import DataTabs from './DataTabs.svelte';
  import { fileState, shortFile } from './util';

  let { params }: PageProps = $props();
  void params;

  let incoming = $state<Change[]>([]);
  let unsaved = $state<UnsavedFile[]>([]);
  let recent = $state<Version[]>([]);
  /** The file whose discard waits for a confirmation, '' = all, undefined = none. */
  let discarding = $state<string | undefined>();
  let checking = $state(false);
  let putting = $state(false);
  let failed = $state('');
  let seq = 0;

  const data = $derived(app.status.data);
  // Reload when the numbers behind the lists change, not on every poll of the status.
  const key = $derived(`${app.rev}:${data?.unsaved}:${data?.incoming}:${data?.pending}:${app.team}`);

  async function load(): Promise<void> {
    const mine = ++seq;
    try {
      const [i, u, r] = await Promise.all([api.DataIncoming(), api.UnsavedChanges(), api.History(app.team, 5)]);
      if (mine !== seq) return;
      [incoming, unsaved, recent, failed] = [i, u, r, ''];
    } catch (e) {
      if (mine !== seq) return;
      // No data repository yet is already said by the banner; anything else is shown here.
      incoming = [];
      unsaved = [];
      recent = [];
      failed = data?.problem ? '' : String(e);
    }
  }

  $effect(() => {
    void key;
    void load();
  });

  async function checkNow(): Promise<void> {
    checking = true;
    try {
      app.status = await api.CheckForChanges();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      checking = false;
    }
  }

  const shownValue = (v: ValueChange, side: 'before' | 'after'): string =>
    (side === 'before' ? v.hasBefore : v.hasAfter) ? v[side] : t('(none)');

  async function putBack(file: string, v: ValueChange): Promise<void> {
    if (putting) return;
    putting = true;
    try {
      const done = await api.DiscardValues([{ file, path: v.path }]);
      await refreshStatus();
      await showNewData();
      if (done.problem) toast(done.problem.message, 'bad');
      else toast(done.warning ?? t('Put back.'), 'ok');
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      putting = false;
    }
  }

  async function discard(files: string[]): Promise<void> {
    const done = await api.Discard(files);
    discarding = undefined;
    await refreshStatus();
    await showNewData();
    if (done.problem) toast(done.problem.message, 'bad');
    else toast(done.warning ?? t('Discarded.'), 'ok');
  }

  const team = $derived(app.team);
  const stateText = (s: string) => {
    switch (fileState(s)) {
      case 'deleted':
        return t('deleted');
      case 'new':
        return t('new');
      case 'renamed':
        return t('renamed');
      default:
        return t('changed');
    }
  };
  const location = $derived(data?.location || t('This computer only'));
  const reviewLink = $derived(app.status.link || data?.link || '');
</script>

<PageHead title={t('Data')} lead={t('Where the data of the team is kept, whether everything is saved and what others changed.')}>
  {#snippet actions()}
    <button class="btn" type="button" disabled={!!app.busy} onclick={refresh}><Icon name="download" />{t('Refresh')}</button>
    <button class="btn primary" type="button" disabled={!!app.busy} onclick={save}><Icon name="save" />{t('Save')}</button>
  {/snippet}
</PageHead>
<DataTabs />

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{/if}
{#if data?.problem}
  <Banner tone="bad">
    <strong>{data.problem.title || t('The storage cannot be used.')}</strong>
    {data.problem.message}
    {#if data.problem.hint}<span class="muted">{data.problem.hint}</span>{/if}
    {#snippet action()}
      <a class="btn" href={link('/settings/storage')}>{t('Open storage settings')}</a>
    {/snippet}
  </Banner>
{:else if app.status.storage === 'conflict'}
  <Banner tone="bad">
    <strong>{t('Conflict:')}</strong>
    {t('You and someone else changed the same value. All other pages stay usable, only the affected values wait.')}
    {#snippet action()}
      <a class="btn" href={link('/data/conflicts')}>{t('Decide')}</a>
    {/snippet}
  </Banner>
{:else if app.status.storage === 'decided'}
  <Banner tone="warn">
    {t('All conflicts are decided. Save finishes it.')}
    {#snippet action()}
      <button class="btn primary" type="button" disabled={!!app.busy} onclick={save}>{t('Save')}</button>
    {/snippet}
  </Banner>
{:else if app.status.storage === 'offline'}
  <Banner tone="info">
    <strong>{t('No connection.')}</strong>
    {t('You keep working with the last state. Save keeps your changes on this computer; they go to the team when the connection is back.')}
  </Banner>
{:else if app.status.storage === 'mr'}
  <Banner tone="warn">
    <strong>{t('Waiting for review.')}</strong>
    {t('Changes need an approval first. Yours are submitted.')}
    {#snippet action()}
      {#if reviewLink}
        <a class="btn" href={reviewLink} onclick={(e) => { e.preventDefault(); openExternal(reviewLink); }}>{t('Open the review')}<Icon name="open_in_new" /></a>
      {/if}
    {/snippet}
  </Banner>
{:else if app.status.storage === 'local'}
  <Banner tone="info">
    {t('No shared storage is set up. Your data is saved on this computer only.')}
    {#snippet action()}
      <a class="btn" href={link('/settings/storage')}>{t('Set up storage')}</a>
    {/snippet}
  </Banner>
{:else if app.status.storage === 'incoming'}
  <Banner tone="warn">{t('Others changed something. Refresh takes it over; your own changes stay.')}</Banner>
{:else if app.status.storage === 'pending'}
  <Banner tone="warn">{t('Saved on this computer, not shared with the team yet. Save shares it.')}</Banner>
{:else if app.status.storage === 'dirty'}
  <Banner tone="info">{t('You have unsaved changes. Save shares them with the team.')}</Banner>
{:else}
  <Banner tone="info">{t('Everything is saved. Your state is the state of the team.')}</Banner>
{/if}

<div class="grid cols-2">
  <section class="card">
    <h2>{t('Where the data is')}</h2>
    <dl class="kv">
      <dt>{t('Storage')}</dt>
      <dd>{t('Team data')}</dd>
      <dt>{t('Location')}</dt>
      <dd class="data wrap">{location}</dd>
      <dt>{t('Waiting to be shared')}</dt>
      <dd class="data">{data?.pending ?? 0}</dd>
      <dt>{t('Connection')}</dt>
      <dd>
        {#if !data?.configured}<span class="chip">{t('Not shared')}</span>
        {:else if data.connected}<span class="chip ok"><Icon name="check_circle" />{t('Connected')}</span>
        {:else}<span class="chip warn"><Icon name="cloud_off" />{t('Offline')}</span>{/if}
      </dd>
    </dl>
    <p class="muted small">
      {t('Change the kind of storage, the sign-in and your name:')}
      <a href={link('/settings/storage')}>{t('Settings, Storage')}</a>
    </p>
  </section>

  <section class="card">
    <div class="row head">
      <h2>{t('Changes of others')}</h2>
      <button class="btn" type="button" disabled={checking || !!app.busy} onclick={checkNow}>
        <Icon name="sync" />{checking ? t('Checking …') : t('Check now')}
      </button>
    </div>
    {#if incoming.length === 0}
      <p class="muted">{t('Nothing new. The app checks in the background.')}</p>
    {:else}
      <ul class="plain">
        {#each incoming as c, i (i)}
          <li>
            <div class="row"><strong>{c.who}</strong><span class="muted small">{c.day}</span></div>
            <div>{c.summary}</div>
          </li>
        {/each}
      </ul>
      <div class="row">
        <button class="btn primary" type="button" disabled={!!app.busy} onclick={refresh}><Icon name="download" />{t('Refresh')}</button>
        <span class="muted small">{t('Your unsaved changes stay.')}</span>
      </div>
    {/if}
  </section>
</div>

<section class="card block" id="unsaved">
  <div class="row head">
    <h2>{t('My unsaved changes')}</h2>
    {#if unsaved.length > 0}
      <button class="btn danger" type="button" disabled={!!app.busy} onclick={() => (discarding = '')}>{t('Discard all')}</button>
    {/if}
  </div>
  {#if unsaved.length === 0}
    <p class="muted">{t('No unsaved changes.')}</p>
  {:else}
    <div class="stack">
      {#each unsaved as f (f.file)}
        <div class="file" data-file>
          <div class="row">
            <span class="chip data grow">{shortFile(f.file, team)}</span>
            <span class="muted small">{stateText(f.status)}</span>
            <button class="btn icon ghost" type="button" aria-label={t('Discard: {file}', { file: shortFile(f.file, team) })} title={t('Discard')} disabled={!!app.busy} onclick={() => (discarding = f.file)}>
              <Icon name="undo" />
            </button>
          </div>
          {#if !f.whole && f.values.length > 0}
            <div class="tw">
              <table class="t">
                <thead><tr><th>{t('Value')}</th><th>{t('Before')}</th><th>{t('Now')}</th><th><span class="sr">{t('Actions')}</span></th></tr></thead>
                <tbody>
                  {#each f.values as v (v.path.join('\u0000'))}
                    <tr>
                      <td class="wrap">{v.label}</td>
                      <td class="data wrap">{shownValue(v, 'before')}</td>
                      <td class="data wrap">{shownValue(v, 'after')}</td>
                      <td>
                        <button class="btn icon ghost" type="button" aria-label={t('Put back: {label}', { label: v.label })} title={t('Put back')} disabled={!!app.busy || putting} onclick={() => putBack(f.file, v)}>
                          <Icon name="undo" />
                        </button>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
  {#if discarding !== undefined}
    <div class="confirm" role="alertdialog" aria-label={t('Confirm discarding')}>
      <Icon name="warning" />
      <div class="grow">
        {#if discarding === ''}
          {t('Discard all unsaved changes? They are gone from the files but kept in a trash folder next to the data.')}
        {:else}
          {t('Discard the unsaved changes in {file}? They are gone from the file but kept in a trash folder next to the data.', { file: shortFile(discarding, team) })}
        {/if}
      </div>
      <button class="btn danger" type="button" disabled={!!app.busy} onclick={() => discard(discarding === '' ? [] : [discarding!])}>{t('Discard')}</button>
      <button class="btn" type="button" onclick={() => (discarding = undefined)}>{t('Cancel')}</button>
    </div>
  {/if}
</section>

<section class="card block">
  <div class="row head">
    <h2>{t('Saved recently')}</h2>
    <a href={link('/data/history')}>{t('Whole history')}</a>
  </div>
  {#if recent.length === 0}
    <p class="muted">{t('Nothing saved yet.')}</p>
  {:else}
    <div class="tw">
      <table class="t">
        <thead><tr><th>{t('When')}</th><th>{t('Who')}</th><th>{t('What')}</th></tr></thead>
        <tbody>
          {#each recent as v (v.id)}
            <tr><td class="data">{v.day}</td><td>{v.who}</td><td class="wrap">{v.summary}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  .file + .file {
    margin-top: 12px;
  }
  .block {
    margin-top: 16px;
  }
  .head {
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .head h2 {
    margin: 0;
  }
  .wrap {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .plain {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .confirm {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 12px;
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
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
