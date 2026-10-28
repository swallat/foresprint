<script lang="ts">
  import { api } from '../../lib/api';
  import { app, refreshStatus, showNewData, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { Done, Label, Version } from '../../lib/types.data';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import DataTabs from './DataTabs.svelte';
  import { shortFile } from './util';

  let { params }: PageProps = $props();
  void params;

  type Mode = 'team' | 'sprint' | 'file';
  const teamFiles = ['team.yaml', 'people.yaml', 'products.yaml', 'projects.yaml', 'tickets.yaml', 'preplan.yaml', 'abwesenheiten.yaml'];

  let mode = $state<Mode>('team');
  let sprint = $state('');
  let file = $state(teamFiles[0] ?? '');
  let versions = $state<Version[]>([]);
  let labels = $state<Label[]>([]);
  let loading = $state(true);
  let failed = $state('');
  /** The entry waiting for the decision how to bring it back. */
  let asking = $state<{ id: string; kind: 'restore' | 'revert' | 'label' | 'delete' } | undefined>();
  let seq = 0;
  let newLabel = $state('');
  let working = $state(false);

  const team = $derived(app.team);
  const sprintId = $derived(sprint || app.sprint);
  const scope = $derived.by(() => {
    if (!team) return '';
    if (mode === 'sprint') return `${team}/sprints/${sprintId}.yaml`;
    if (mode === 'file') return `${team}/${file}`;
    return team;
  });
  const key = $derived(`${scope}:${app.rev}:${app.status.data?.unsaved}`);

  async function load(): Promise<void> {
    const mine = ++seq;
    loading = true;
    failed = '';
    try {
      const [v, l] = await Promise.all([api.History(scope, 100), api.Labels(false)]);
      if (mine !== seq) return;
      [versions, labels] = [v, l];
    } catch (e) {
      if (mine !== seq) return;
      versions = [];
      labels = [];
      failed = String(e);
    } finally {
      if (mine === seq) loading = false;
    }
  }

  $effect(() => {
    void key;
    void load();
  });

  async function after(done: Done, message: string, filesChanged = false): Promise<void> {
    asking = undefined;
    await refreshStatus();
    if (done.problem) {
      toast(done.problem.hint ? `${done.problem.message} ${done.problem.hint}` : done.problem.message, 'bad');
    } else {
      toast(done.warning ? `${message} ${done.warning}` : message, 'ok');
      if (filesChanged) {
        // the files changed under the open pages: they read their data anew (this page too)
        await showNewData();
        return;
      }
    }
    await load();
  }

  async function guarded(run: () => Promise<void>): Promise<void> {
    working = true;
    try {
      await run();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  const restore = (v: Version, wholeTeam = false) =>
    guarded(async () => after(await api.Restore(wholeTeam ? '' : scope, v.id, ''), t('Brought back and saved on this computer. Save shares it.'), true));
  const revert = (v: Version) =>
    guarded(async () => after(await api.Revert(v.id), t('Change taken back and saved on this computer. Save shares it.'), true));
  const setLabel = () =>
    guarded(async () => {
      const name = newLabel.trim();
      if (!name) return;
      await after(await api.SetLabel(name, '', ''), t('Tag {name} set.', { name }));
      newLabel = '';
    });
  const shareLabel = (l: Label) => guarded(async () => after(await api.ShareLabel(l.name), t('Tag {name} shared.', { name: l.name })));
  const deleteLabel = (l: Label) => guarded(async () => after(await api.DeleteLabel(l.name), t('Tag {name} deleted.', { name: l.name })));

  const files = (v: Version) => v.files.map((f) => shortFile(f, team)).join(', ');
  const unsaved = $derived(app.status.data?.unsaved ?? 0);
  const needSaved = $derived(unsaved > 0 ? t('Save or discard the unsaved changes first.') : '');
</script>

<PageHead
  title={t('History and tags')}
  lead={t('Who changed what and when. Take back one change or bring back an earlier state. Both are saved on this computer first; Save shares them.')}
/>
<DataTabs />

{#if unsaved > 0}
  <Banner tone="info">
    {t('You have {n} unsaved changes. Bringing back a state needs them saved or discarded first.', { n: unsaved })}
    {#snippet action()}
      <a class="btn" href={link('/data')}>{t('Look at them')}</a>
    {/snippet}
  </Banner>
{/if}

<div class="row scope" role="group" aria-label={t('Scope')}>
  <span class="small muted">{t('Scope')}</span>
  {#each [['team', t('Team')], ['sprint', t('Sprint')], ['file', t('File')]] as [m, label] (m)}
    <button class="chip filter" class:on={mode === m} type="button" aria-pressed={mode === m} onclick={() => (mode = m as Mode)}>{label}</button>
  {/each}
  {#if mode === 'sprint'}
    <select class="input data" aria-label={t('Sprint')} value={sprintId} onchange={(e) => (sprint = e.currentTarget.value)}>
      {#each app.sprints as s (s.id)}<option value={s.id}>{s.id}</option>{/each}
    </select>
  {:else if mode === 'file'}
    <select class="input data" aria-label={t('File')} bind:value={file}>
      {#each teamFiles as f (f)}<option value={f}>{f}</option>{/each}
    </select>
  {/if}
  <span class="small muted">{t('{n} entries', { n: versions.length })}</span>
</div>

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{/if}

<div class="tw">
  <table class="t">
    <thead>
      <tr><th>{t('When')}</th><th>{t('Who')}</th><th>{t('What')}</th><th>{t('Files')}</th><th><span class="sr">{t('Actions')}</span></th></tr>
    </thead>
    <tbody>
      {#each versions as v (v.id)}
        <tr>
          <td class="data">{v.day}</td>
          <td>{v.who}</td>
          <td class="wrap">
            {v.summary}
            {#each v.tags as tag (tag)}<span class="chip fc"><Icon name="sell" /><span class="data">{tag}</span></span>{/each}
          </td>
          <td class="data muted wrap">{files(v)}</td>
          <td>
            <div class="actions">
              <button class="btn" type="button" disabled={v.merge || working || !!app.busy || unsaved > 0} title={v.merge ? t('A merge cannot be taken back.') : needSaved} onclick={() => (asking = { id: v.id, kind: 'revert' })}>
                <Icon name="undo" />{t('Take back this change')}
              </button>
              <button class="btn" type="button" disabled={working || !!app.busy || unsaved > 0} title={needSaved} onclick={() => (asking = { id: v.id, kind: 'restore' })}>
                <Icon name="settings_backup_restore" />{t('Restore this state')}
              </button>
            </div>
          </td>
        </tr>
        {#if asking?.id === v.id && asking.kind !== 'label'}
          <tr class="ask">
            <td colspan="5">
              <div class="confirm" role="alertdialog" aria-label={t('Confirm')}>
                <Icon name="info" />
                <div class="grow">
                  {#if asking.kind === 'revert'}
                    {t('This reverses only the change of {who} from {day}. It is saved on this computer; Save shares it.', { who: v.who, day: v.day })}
                  {:else}
                    {t('The files in this scope go back to the state after the change of {who} from {day}. This is saved on this computer, the current state stays in the history; Save shares it.', { who: v.who, day: v.day })}
                  {/if}
                </div>
                {#if asking.kind === 'revert'}
                  <button class="btn primary" type="button" disabled={working || !!app.busy} onclick={() => revert(v)}>{t('Bring it back')}</button>
                {:else}
                  <button class="btn primary" type="button" disabled={working || !!app.busy} onclick={() => restore(v)}>{t('Bring it back')}</button>
                {/if}
                <button class="btn" type="button" onclick={() => (asking = undefined)}>{t('Cancel')}</button>
              </div>
            </td>
          </tr>
        {/if}
      {:else}
        <tr><td colspan="5" class="muted wrap">{loading ? t('Loading…') : t('No entries in this scope.')}</td></tr>
      {/each}
    </tbody>
  </table>
</div>

<h2 class="tags">{t('Tags')}</h2>
<p class="muted small lead">{t('A tag names a state of the data, for example the end of a sprint. Any earlier state can be chosen; tags help to find it.')}</p>
<div class="row set">
  <input class="input data" aria-label={t('Name of the new tag')} placeholder={t('e.g. 2026.22')} bind:value={newLabel} onkeydown={(e) => e.key === 'Enter' && setLabel()} />
  <button class="btn" type="button" disabled={working || !newLabel.trim()} onclick={setLabel}><Icon name="sell" />{t('Tag the current state')}</button>
</div>
{#if app.pendingTags.length > 0}
  <div class="stack pending" data-pending-tags>
    {#each app.pendingTags as p (p.name)}
      <div class="row">
        <span class="chip fc"><Icon name="sell" /><span class="data">{p.name}</span></span>
        {#if p.ready}
          <span class="muted small">{t('Set with the next Save (asked for by a sprint review).')}</span>
        {:else}
          <span class="chip warn"><Icon name="warning" />{t('Cannot be set: the name is invalid or already taken.')}</span>
        {/if}
      </div>
    {/each}
  </div>
{/if}
<div class="tw">
  <table class="t">
    <thead><tr><th>{t('Tag')}</th><th>{t('Date')}</th><th>{t('Occasion')}</th><th>{t('Shared')}</th><th><span class="sr">{t('Actions')}</span></th></tr></thead>
    <tbody>
      {#each labels as l (l.name)}
        <tr>
          <td><span class="chip fc"><Icon name="sell" /><span class="data">{l.name}</span></span></td>
          <td class="data">{l.day}</td>
          <td class="wrap">{l.summary}</td>
          <td>
            {#if l.differs}<span class="chip warn"><Icon name="warning" />{t('Differs from the shared version')}</span>
            {:else if l.onServer === false}<span class="chip">{t('Only here')}</span>
            {:else if l.onServer}<span class="chip ok"><Icon name="check" />{t('Shared')}</span>
            {:else}<span class="muted">–</span>{/if}
          </td>
          <td>
            <div class="actions">
              {#if l.onServer === false}
                <button class="btn" type="button" disabled={working} onclick={() => shareLabel(l)}><Icon name="cloud_upload" />{t('Share')}</button>
              {/if}
              <button class="btn" type="button" disabled={working || !!app.busy || unsaved > 0} title={needSaved} onclick={() => (asking = { id: l.name, kind: 'label' })}>
                <Icon name="settings_backup_restore" />{t('Restore this state')}
              </button>
              <button class="btn icon ghost" type="button" disabled={working} aria-label={t('Delete tag {name}', { name: l.name })} title={t('Delete tag')} onclick={() => (asking = { id: l.name, kind: 'delete' })}>
                <Icon name="delete" />
              </button>
            </div>
          </td>
        </tr>
        {#if asking?.id === l.name && asking.kind === 'delete'}
          <tr class="ask">
            <td colspan="5">
              <div class="confirm" role="alertdialog" aria-label={t('Confirm')}>
                <Icon name="warning" />
                <div class="grow">{t('Delete the tag {name}? The tag goes away, where possible for the others too. The saved states stay.', { name: l.name })}</div>
                <button class="btn danger" type="button" disabled={working} onclick={() => deleteLabel(l)}>{t('Delete tag')}</button>
                <button class="btn" type="button" onclick={() => (asking = undefined)}>{t('Cancel')}</button>
              </div>
            </td>
          </tr>
        {/if}
        {#if asking?.id === l.name && asking.kind === 'label'}
          <tr class="ask">
            <td colspan="5">
              <div class="confirm" role="alertdialog" aria-label={t('Confirm')}>
                <Icon name="warning" />
                <div class="grow">
                  {t('This affects all teams in the data folder: later changes to people, sprints and projects go back. It is saved on this computer, the current state stays in the history; Save shares it.')}
                </div>
                <button class="btn primary" type="button" disabled={working || !!app.busy} onclick={() => restore({ id: l.target } as Version, true)}>{t('Bring it back')}</button>
                <button class="btn" type="button" onclick={() => (asking = undefined)}>{t('Cancel')}</button>
              </div>
            </td>
          </tr>
        {/if}
      {:else}
        <tr><td colspan="5" class="muted wrap">{t('No tags yet. Every sprint review can set one.')}</td></tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .pending {
    margin-bottom: 8px;
  }
  .scope {
    margin-bottom: 12px;
  }
  .wrap {
    white-space: normal;
    overflow-wrap: anywhere;
    min-width: 160px;
  }
  .actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
  }
  .tags {
    margin-top: 24px;
  }
  .lead {
    margin: -4px 0 8px;
  }
  .set {
    margin-bottom: 12px;
  }
  .set input {
    width: 200px;
  }
  tr.ask td {
    background: var(--surface-2);
    white-space: normal;
    height: auto;
  }
  .confirm {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .confirm .grow {
    flex: 1;
    min-width: 240px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
