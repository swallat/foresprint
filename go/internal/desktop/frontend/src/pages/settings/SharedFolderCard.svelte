<script lang="ts">
  import { api } from '../../lib/api';
  import { app, loadTeams, refreshStatus, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { SharedFolderCheck, SharedFolderTest, StorageSettings } from '../../lib/types.data';
  import Banner from '../../lib/ui/Banner.svelte';

  // Settings > Storage > Shared folder: keep the team's data in a folder on a file server or in a
  // sync service (Dropbox, Nextcloud, OneDrive ...) instead of a Git repository.

  let { st, onchange, embedded = false }: { st: StorageSettings; onchange: () => void | Promise<void>; embedded?: boolean } = $props();

  let shared = $state('');
  let local = $state('');
  let person = $state('');
  let create = $state(false);
  let check = $state<SharedFolderCheck>();
  let working = $state(false);

  const isFolder = $derived(st.kind === 'folder');

  // After a switch back to Git the card starts empty again.
  $effect(() => {
    if (isFolder) return;
    shared = '';
    local = '';
    person = '';
    create = false;
    check = undefined;
  });

  async function pick(which: 'shared' | 'local'): Promise<void> {
    const got = await api.PickFolder(which === 'shared' ? t('Choose the shared folder') : t('Choose the folder for your copy of the data'));
    if (!got) return;
    if (which === 'shared') {
      shared = got;
      check = undefined;
    } else local = got;
  }

  async function test(): Promise<void> {
    working = true;
    try {
      check = await api.CheckSharedFolder(shared.trim());
      // A folder with data is joined; an empty one is the start of a new storage.
      create = check.ok && !check.hasData;
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function use(): Promise<void> {
    working = true;
    try {
      const o = await api.UseSharedFolder(local.trim() || st.folder, shared.trim(), person.trim(), create);
      if (o.problem) {
        toast(o.problem.hint ? `${o.problem.message} ${o.problem.hint}` : o.problem.message, 'bad');
        // The copy is set up but the first refresh failed: the window follows the storage anyway.
        if (o.folder) {
          app.prefs = await api.Prefs();
          await loadTeams();
          await onchange();
          await refreshStatus();
        }
        return;
      }
      app.prefs = await api.Prefs();
      toast(t('Shared folder in use: {folder}', { folder: shared.trim() }), 'ok');
      await loadTeams();
      await onchange();
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  function label(r: SharedFolderTest): string {
    switch (r.key) {
      case 'exists': return t('The folder can be reached');
      case 'write': return t('You can write in it');
      case 'lock': return t('The lock file can be created exclusively');
      case 'replace': return t('A file can be replaced in one step');
      case 'clock': return t('Clock difference to this computer: {diff}', { diff: r.detail });
      default: return t('Names with umlauts work');
    }
  }
</script>

<svelte:element this={embedded ? 'div' : 'section'} class={embedded ? 'embedded' : 'card'} aria-labelledby={embedded ? undefined : 's-shared'} data-tour={embedded ? undefined : 'settings-shared-folder'}>
  {#if !embedded}<h2 id="s-shared">{t('Shared folder')}</h2>{/if}
  {#if isFolder}
    <p class="data wrap">{st.shared}</p>
    <div class="row">
      {#if st.connected}<span class="chip ok"><Icon name="check_circle" />{t('reachable')}</span>
      {:else}<span class="chip warn"><Icon name="warning" />{t('not reachable')}</span>{/if}
      <span class="small muted">{t('Your name in the history: {name}', { name: st.person ?? '' })}</span>
    </div>
    <p class="small muted">{t('You work on a copy in {folder}. Save puts your changes into the shared folder, Refresh takes over what others saved. Without a connection you can keep working; saving waits.', { folder: st.folder })}</p>
  {:else}
    <p class="small muted">{t('Instead of a Git repository, the team can keep its data in a folder on a file server or in a sync service such as Dropbox, Nextcloud or OneDrive. You work on a copy; Save merges your changes into the shared folder.')}</p>
    <div class="field top">
      <label for="sf-shared">{t('Shared folder')}</label>
      <div class="row">
        <input id="sf-shared" class="input data grow" bind:value={shared} oninput={() => (check = undefined)} placeholder={t('Path of the shared folder')} />
        <button class="btn" type="button" disabled={working} onclick={() => pick('shared')}><Icon name="folder_open" />{t('Choose')}</button>
      </div>
    </div>
    <div class="row top">
      <button class="btn" type="button" disabled={working || !shared.trim()} onclick={test}><Icon name="fact_check" />{t('Test the folder')}</button>
    </div>
    {#if check}
      <ul class="plain top" role="status" aria-label={t('Result of the test')}>
        {#each check.results as r (r.key)}
          <li class="row">
            <Icon name={r.ok ? 'check_circle' : 'warning'} />
            <span class:muted={r.ok}>{#if !r.ok}<span class="sr">{t('Failed:')} </span>{/if}{label(r)}{#if !r.ok && r.detail}: <span class="data">{r.detail}</span>{/if}</span>
          </li>
        {/each}
      </ul>
      {#if check.service}
        <Banner tone="info">
          {t('{service} delivers changes with a delay. Foresprint does not rely on a lock there; it compares versions when you save and merges. If the service still makes a conflict copy, you decide in the list of conflicts.', { service: check.service })}
        </Banner>
      {/if}
      {#if check.ok}
        {#if check.hasData}
          <p class="small">{t('The folder already holds team data; your copy takes it over.')}</p>
        {:else}
          <label class="check"><input type="checkbox" bind:checked={create} />{t('Start a new shared storage in this folder')}</label>
        {/if}
        <div class="field top">
          <label for="sf-local">{t('Your copy of the data')}</label>
          <div class="row">
            <input id="sf-local" class="input data grow" bind:value={local} placeholder={st.folder} />
            <button class="btn" type="button" disabled={working} onclick={() => pick('local')}><Icon name="folder_open" />{t('Choose')}</button>
          </div>
        </div>
        <div class="field top">
          <label for="sf-person">{t('Your name in the history')}</label>
          <input id="sf-person" class="input" bind:value={person} placeholder={t('Name of this computer user')} />
        </div>
        <div class="row top">
          <button class="btn primary" type="button" disabled={working || (!create && !check.hasData)} onclick={use}>
            <Icon name="check_circle" />{t('Use this folder')}
          </button>
        </div>
        {#if !create && !check.hasData}
          <p class="small muted">{t('The folder holds no team data yet. Tick “Start a new shared storage in this folder” to use it.')}</p>
        {/if}
      {/if}
    {/if}
  {/if}
</svelte:element>

<style>
  .wrap {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .top {
    margin-top: 12px;
  }
  .plain {
    list-style: none;
    padding: 0;
    margin: 12px 0 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .check {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-top: 8px;
  }
</style>
