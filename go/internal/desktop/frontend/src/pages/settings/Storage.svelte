<script lang="ts">
  import { api } from '../../lib/api';
  import { app, loadTeams, refreshStatus, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { go, link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { Branch, LineEndings, Problem, RecentFolder, ServerCheck, SignInGuide, StorageSettings } from '../../lib/types.data';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  // Settings > Storage. The only page with the words of the storage kind (server, branch, merge
  // request, token); everywhere else the window says save, refresh and history.

  let { params }: PageProps = $props();
  void params;

  let st = $state<StorageSettings>();
  let branches = $state<Branch[]>([]);
  let endings = $state<LineEndings>();
  let recent = $state<RecentFolder[]>([]);
  let loadFailed = $state('');
  let working = $state(false);

  // Form values
  let server = $state('');
  let allowInsecure = $state(false);
  let acceptNewBranch = $state(false);
  let allowOffline = $state(false);
  let check = $state<ServerCheck>();
  let user = $state('');
  /** True once the person typed a user name; until then it follows the kind of server. */
  let userTouched = $state(false);
  /** The server type picked by hand for an address the app cannot tell (generic). */
  let pickedKind = $state('');
  let pickedGuide = $state<SignInGuide>();
  let token = $state('');
  let name = $state('');
  let email = $state('');
  let pickBranch = $state('');
  let cloneAddress = $state('');
  /** The stored values the form fields were last filled from. */
  let shown = { server: '', name: '', email: '' };

  async function load(): Promise<void> {
    try {
      st = await api.Storage();
      loadFailed = '';
    } catch (e) {
      loadFailed = String(e);
      return;
    }
    // A field the person is typing in keeps its text; only untouched fields follow the stored value.
    if (server === shown.server) server = st.server;
    if (name === shown.name) name = st.name;
    if (email === shown.email) email = st.email;
    shown = { server: st.server, name: st.name, email: st.email };
    if (pickedKind && st.guide.kind !== 'generic' && st.guide.kind !== pickedKind) {
      pickedKind = '';
      pickedGuide = undefined;
    }
    if (!userTouched) user = (pickedGuide ?? st.guide).username;
    recent = await api.RecentFolders().catch(() => []);
    if (st.ready) {
      branches = await api.Branches().catch(() => []);
      pickBranch = st.branch;
      endings = await api.LineEndings().catch(() => undefined);
    } else {
      branches = [];
      endings = undefined;
    }
  }

  $effect(() => {
    void app.rev;
    void load();
  });

  async function pickKind(kind: string): Promise<void> {
    pickedKind = kind;
    pickedGuide = kind ? await api.SignInGuide(kind).catch(() => undefined) : undefined;
    if (!userTouched) user = (pickedGuide ?? st?.guide)?.username ?? '';
  }

  /** Runs an action that answers with a problem or nothing; shows the outcome. */
  async function act(run: () => Promise<Problem | null | undefined>, ok: string, reload = true): Promise<boolean> {
    working = true;
    try {
      const problem = await run();
      if (problem) {
        toast(problem.hint ? `${problem.message} ${problem.hint}` : problem.message, 'bad');
        await load(); // the controls show what is stored again
        return false;
      }
      toast(ok, 'ok');
      if (reload) {
        await load();
        await refreshStatus();
      }
      return true;
    } catch (e) {
      toast(String(e), 'bad');
      return false;
    } finally {
      working = false;
    }
  }

  async function testServer(): Promise<void> {
    working = true;
    try {
      check = await api.CheckServer(server, allowInsecure);
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function saveServer(): Promise<void> {
    working = true;
    try {
      const r = await api.SaveServer(server, { allowInsecure, acceptNewBranch, allowOffline });
      if (r.problem) {
        toast(r.problem.hint ? `${r.problem.message} ${r.problem.hint}` : r.problem.message, 'bad');
        return;
      }
      toast(r.verified ? t('Server address saved and checked.') : t('Server address saved. The server could not be checked now.'), 'ok');
      check = undefined;
      await load();
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function folderAction(kind: 'open' | 'create' | 'clone', folder: string | undefined = undefined): Promise<void> {
    working = true;
    try {
      const picked =
        folder ??
        (await api.PickFolder(kind === 'open' ? t('Choose the data folder') : kind === 'create' ? t('Choose a folder for the new data') : t('Choose a folder to copy the data into')));
      if (!picked) return;
      const o = kind === 'open' ? await api.OpenFolder(picked) : kind === 'create' ? await api.CreateFolder(picked) : await api.CloneFrom(cloneAddress, picked);
      if (o.problem) {
        toast(o.problem.hint ? `${o.problem.message} ${o.problem.hint}` : o.problem.message, 'bad');
        return;
      }
      app.prefs = await api.Prefs();
      toast(t('Data folder in use: {folder}', { folder: o.folder }), 'ok');
      await loadTeams();
      await load();
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function switchBranch(): Promise<void> {
    working = true;
    try {
      const d = await api.SwitchBranch(pickBranch);
      if (d.problem) toast(d.problem.message, 'bad');
      else toast(t('Branch {name} is in use.', { name: pickBranch }), 'ok');
      await load();
      await refreshStatus();
      await loadTeams();
      app.rev++;
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function reattach(): Promise<void> {
    working = true;
    try {
      const r = await api.Reattach();
      if (r.problem) toast(r.problem.message, 'bad');
      else toast(r.rescue ? t('Back on {branch}. Your work is kept on {rescue}.', { branch: r.branch, rescue: r.rescue }) : t('Back on {branch}.', { branch: r.branch }), 'ok');
      await load();
      await refreshStatus();
      await loadTeams();
      app.rev++;
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  async function fixEndings(): Promise<void> {
    working = true;
    try {
      endings = await api.ApplyLineEndings();
      if (endings.problem) toast(endings.problem.message, 'bad');
      else toast(t('Line endings are set. Save shares the setting with the team.'), 'ok');
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = false;
    }
  }

  const unsaved = $derived(app.status.data?.unsaved ?? 0);
  const hostLabel = (h: string) => (h === '' ? t('Detect from the address') : h);
  const signedIn = $derived(!!st && st.helper !== '' && st.helper !== 'none');
</script>

<PageHead title={t('Storage')} lead={t('The technical details of where the data is kept. In daily work you only need Save and Refresh.')} />

{#if loadFailed}
  <Banner tone="bad">{loadFailed}</Banner>
{/if}

{#if st}
  {#if st.problem}
    <Banner tone="warn">
      <strong>{st.problem.title || t('No data repository yet.')}</strong>
      {st.problem.message}
      {#if st.problem.hint}{st.problem.hint}{/if}
    </Banner>
  {/if}
  {#if st.special}
    <Banner tone="info">
      {t('The remote address has a setup that the app leaves alone ({kind}). Change it with Git directly if you need to.', { kind: st.special })}
    </Banner>
  {/if}

  <div class="grid cols-2">
    <section class="card" aria-labelledby="s-kind" data-tour="settings-storage">
      <h2 id="s-kind">{t('Kind of storage')}</h2>
      <div class="stack">
        <div class="opt on">
          <div class="row"><Icon name="check_circle" /><strong>{t('Git repository')}</strong></div>
          <p class="small muted">{t('History, restoring and data safety. The standard in 1.0.')}</p>
        </div>
        <div class="opt off" aria-disabled="true">
          <div class="row"><strong>{t('Shared folder')}</strong><span class="chip">{t('after 1.0')}</span></div>
          <p class="small muted">{t('File server or SharePoint will use the same interface after 1.0.')}</p>
        </div>
      </div>
    </section>

    <section class="card" aria-labelledby="s-folder">
      <h2 id="s-folder">{t('Data folder')}</h2>
      <p class="data wrap">{st.folder || t('No folder chosen.')}</p>
      <div class="row">
        <button class="btn" type="button" disabled={working} onclick={() => folderAction('open')}><Icon name="folder_open" />{t('Open a folder')}</button>
        <button class="btn" type="button" disabled={working} onclick={() => folderAction('create')}><Icon name="create_new_folder" />{t('Start a new one')}</button>
      </div>
      <div class="field top">
        <label for="s-clone">{t('Or copy the data of a team from a server')}</label>
        <div class="row">
          <input id="s-clone" class="input data grow" placeholder="https://git.example.com/team/data" bind:value={cloneAddress} />
          <button class="btn" type="button" disabled={working || !cloneAddress.trim()} onclick={() => folderAction('clone')}>
            <Icon name="download" />{t('Copy into a folder')}
          </button>
        </div>
      </div>
      {#if recent.length > 0}
        <h3 class="small muted">{t('Recently used folders')}</h3>
        <ul class="plain">
          {#each recent as r (r.path)}
            <li class="row">
              <span class="data wrap grow">{r.path}</span>
              {#if r.inUse}<span class="chip ok">{t('in use')}</span>
              {:else if r.missing}<span class="chip warn"><Icon name="warning" />{t('not found')}</span>
              {:else}<button class="btn" type="button" disabled={working} aria-label={t('Open {path}', { path: r.path })} onclick={() => folderAction('open', r.path)}>{t('Open')}</button>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    {#if st.ready}
      <section class="card" aria-labelledby="s-server">
        <h2 id="s-server">{t('Server')}</h2>
        <div class="field">
          <label for="s-addr">{t('Address of the repository')}</label>
          <input id="s-addr" class="input data" bind:value={server} oninput={() => (check = undefined)} />
        </div>
        <label class="check"><input type="checkbox" bind:checked={allowInsecure} />{t('Allow an unencrypted address (http)')}</label>
        <div class="row top">
          <button class="btn" type="button" disabled={working || !server.trim()} onclick={testServer}><Icon name="network_check" />{t('Test connection')}</button>
          <button class="btn primary" type="button" disabled={working || !server.trim() || server === st.server} onclick={saveServer}>{t('Save address')}</button>
        </div>
        {#if check}
          <div class="result" role="status">
            {#if check.ok}
              <span class="chip ok"><Icon name="check_circle" />{t('Reachable')}</span>
              {#if check.empty}<span class="small">{t('The server has no data yet. The first Save puts yours there.')}</span>
              {:else if check.branchMissing}
                <label class="check"><input type="checkbox" bind:checked={acceptNewBranch} />{t('The server has data, but not under the branch {branch}. Create it with the first Save.', { branch: st.branch })}</label>
              {/if}
            {:else if check.problem}
              <span class="chip bad"><Icon name="error" />{check.problem.title || t('Not reachable')}</span>
              <span class="small">{check.problem.message} {check.problem.hint ?? ''}</span>
              {#if check.problem.kind === 'offline'}
                <label class="check"><input type="checkbox" bind:checked={allowOffline} />{t('Save the address although the server cannot be reached now')}</label>
              {/if}
            {/if}
          </div>
        {/if}
      </section>

      <section class="card" aria-labelledby="s-auth">
        <h2 id="s-auth">{t('Sign-in (token)')}</h2>
        <p class="row">
          {#if signedIn}<span class="chip ok"><Icon name="verified_user" />{t('Credential helper: {name}', { name: st.helper })}</span>
          {:else}<span class="chip warn"><Icon name="key_off" />{t('No credential helper set up')}</span>{/if}
        </p>
        {#if !signedIn && st.suggestedHelper}
          <div class="row">
            <button class="btn" type="button" disabled={working} onclick={() => act(() => api.EnableHelper(st!.suggestedHelper), t('Credential helper {name} turned on.', { name: st!.suggestedHelper }))}>
              {t('Use the helper {name}', { name: st.suggestedHelper })}
            </button>
          </div>
        {/if}
        {#if st.guide.kind === 'generic' || pickedKind}
          <div class="field top">
            <label for="s-kind">{t('My server is')}</label>
            <select id="s-kind" class="input" value={pickedKind} onchange={(e) => pickKind(e.currentTarget.value)}>
              <option value="">{t('Other server')}</option>
              <option value="gitlab">GitLab</option>
              <option value="forgejo">Forgejo / Gitea / Codeberg</option>
              <option value="github">GitHub</option>
            </select>
          </div>
        {/if}
        {#if (pickedGuide ?? st.guide).steps}
          <details class="top">
            <summary>{t('How do I get a token?')}</summary>
            <p class="small wrap">{(pickedGuide ?? st.guide).steps}</p>
          </details>
        {/if}
        <div class="field top">
          <label for="s-user">{t('User name at the server')}</label>
          <input id="s-user" class="input data" bind:value={user} oninput={() => (userTouched = true)} autocomplete="off" />
        </div>
        <div class="field top">
          <label for="s-token">{t('New token')}</label>
          <input id="s-token" class="input data" type="password" autocomplete="new-password" placeholder={t('Paste the token')} bind:value={token} />
        </div>
        <div class="row top">
          <button class="btn primary" type="button" disabled={working || !token || !st.server}
            onclick={async () => { if (await act(() => api.SignIn(st!.server, user, token), t('Signed in. The token is kept by the credential helper of your system.'))) token = ''; }}>
            <Icon name="verified_user" />{t('Sign in')}
          </button>
          <button class="btn danger" type="button" disabled={working || !st.server} onclick={() => act(() => api.ForgetSignIn(st!.server, user), t('Sign-in removed.'))}>
            <Icon name="delete" />{t('Remove sign-in')}
          </button>
        </div>
        <p class="small muted">{t('The token goes to the credential helper of your system, never into the data of the team and never into a file of this app.')}</p>
      </section>

      <section class="card" aria-labelledby="s-branch">
        <h2 id="s-branch">{t('Branch')}</h2>
        <div class="row">
          <select class="input data" aria-label={t('Branch')} bind:value={pickBranch} disabled={unsaved > 0 || working}>
            {#each branches as b (b.name)}<option value={b.name}>{b.name}{b.current ? ` (${t('in use')})` : ''}</option>{/each}
          </select>
          <button class="btn" type="button" disabled={unsaved > 0 || working || pickBranch === st.branch} onclick={switchBranch}>{t('Switch')}</button>
        </div>
        {#if unsaved > 0}
          <Banner tone="warn">
            {t('Switching is locked: {n} unsaved changes. Save or discard them first.', { n: unsaved })}
            {#snippet action()}<a class="btn" href={link('/data')}>{t('Look at them')}</a>{/snippet}
          </Banner>
        {:else}
          <p class="small muted">{t('The branch in use: {name}.', { name: st.branch })}</p>
        {/if}
      </section>

      <section class="card" aria-labelledby="s-id">
        <h2 id="s-id">{t('Name and e-mail')}</h2>
        <div class="stack">
          <div class="field"><label for="s-name">{t('Name in saves')}</label><input id="s-name" class="input" bind:value={name} /></div>
          <div class="field"><label for="s-mail">{t('E-mail')}</label><input id="s-mail" class="input" type="email" bind:value={email} /></div>
        </div>
        <div class="row top">
          <button class="btn primary" type="button" disabled={working || (name === st.name && email === st.email)} onclick={() => act(() => api.SetIdentity(name, email), t('Name and e-mail saved.'))}>{t('Save name and e-mail')}</button>
        </div>
        <p class="small muted">{t('Shown in the history as the author of each change.')}</p>
      </section>

      <section class="card" aria-labelledby="s-review">
        <h2 id="s-review">{t('Merge request')}</h2>
        {#key st}
        <div class="field">
          <label for="s-share">{t('How saves reach the server')}</label>
          <select id="s-share" class="input" value={st.share || 'direct'} onchange={(e) => act(() => api.SetShare(e.currentTarget.value), t('Saved.'))} disabled={working}>
            <option value="direct">{t('Directly to the main branch')}</option>
            <option value="merge_request">{t('Through a merge request')}</option>
          </select>
        </div>
        <p class="small">
          {t('Some servers accept changes to the main branch only through a merge request. The app notices this at the first Save and switches by itself.')}
        </p>
        <ol class="small steps">
          <li>{t('Save sends your changes to a branch of your own and opens the merge request.')}</li>
          <li>{t('The status shows "Waiting for review" with a link.')}</li>
          <li>{t('Further saves update the same merge request.')}</li>
          <li>{t('After the approval on the server, Refresh takes the state over.')}</li>
        </ol>
        <label class="check"><input type="checkbox" checked={st.autoMerge} disabled={working} onchange={(e) => act(() => api.SetAutoMerge(e.currentTarget.checked), t('Saved.'))} />{t('Merge automatically when the checks pass')}</label>
        <div class="field top">
          <label for="s-host">{t('Kind of server')}</label>
          <select id="s-host" class="input" value={st.host} onchange={(e) => act(() => api.SetHost(e.currentTarget.value), t('Saved.'))} disabled={working}>
            {#each ['', ...st.hosts] as h (h)}<option value={h}>{hostLabel(h)}</option>{/each}
          </select>
          {#if st.host === '' && st.detectedHost}<span class="small muted">{t('Detected: {kind}', { kind: st.detectedHost })}</span>{/if}
        </div>
              {/key}
      </section>
    {/if}

    {#if endings?.needed}
      <section class="card" aria-labelledby="s-eol">
        <h2 id="s-eol">{t('Line endings')}</h2>
        <p>{t('Windows and Linux write line breaks differently. Without a fixed setting, a save can show whole files as changed.')}</p>
        <p class="small muted">
          {t('The setting goes into {file}:', { file: endings.file })}
          <span class="data">{endings.rules.join(', ')}</span>
        </p>
        {#if endings.affected.length > 0}
          <p class="small muted">{t('{n} existing files change their line endings with the next save.', { n: endings.affected.length })}</p>
        {/if}
        <button class="btn" type="button" disabled={working} onclick={fixEndings}>{t('Fix line endings')}</button>
      </section>
    {/if}

    <section class="card" aria-labelledby="s-setup">
      <h2 id="s-setup">{t('Setup check')}</h2>
      <div class="row">
        <button class="btn" type="button" onclick={() => go('/setup', {}, { only: 'storage' })}><Icon name="restart_alt" />{t('Run first-start setup again')}</button>
        <span class="muted small">{t('Walks through storage and sign-in again. You can cancel at any time. Your data stays.')}</span>
      </div>
      <ul class="plain">
        {#each st.setup as item (item.key)}
          <li class="row">
            <Icon name={item.ok ? 'check_circle' : 'warning'} />
            <span class:muted={item.ok}>{item.detail}</span>
          </li>
        {/each}
      </ul>
      {#if app.status.data?.chip.state === 'problem' && st.ready}
        <details class="top">
          <summary>{t('The data is not on a working version')}</summary>
          <p class="small">{t('Go back to the main version. Work that is not on a branch is kept on a rescue branch first.')}</p>
          <button class="btn" type="button" disabled={working} onclick={reattach}>{t('Go back to the main version')}</button>
        </details>
      {/if}
    </section>
  </div>
{/if}

<style>
  .opt {
    border: 1px solid var(--border);
    border-radius: var(--r-card);
    padding: 10px 12px;
  }
  .opt.on {
    border: 2px solid var(--primary);
    padding: 9px 11px;
    background: var(--primary-weak);
  }
  .opt.off {
    color: var(--text-muted);
  }
  .opt p {
    margin: 4px 0 0;
  }
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
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .check {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-top: 8px;
  }
  .result {
    margin-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-start;
  }
  .steps {
    margin: 0 0 8px;
    padding-left: 18px;
  }
  h3 {
    margin: 16px 0 4px;
    font-weight: 600;
  }
  .grow {
    flex: 1;
  }
  .grow:is(input) {
    min-width: 200px;
  }
</style>
