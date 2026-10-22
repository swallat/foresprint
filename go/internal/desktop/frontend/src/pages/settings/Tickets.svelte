<script lang="ts">
  import { app, loadFeatures, refreshStatus, syncTracker, toast } from '../../lib/app.svelte';
  import { api } from '../../lib/api';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import ChangesCard from '../../lib/settings/ChangesCard.svelte';
  import Switch from '../../lib/settings/Switch.svelte';
  import { changes, type Field } from '../../lib/settings/diff';
  import type { Connection, QueryCheck, TrackerSettings } from '../../lib/types.settings';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import FieldMapping from './FieldMapping.svelte';
  import PackageImport from './PackageImport.svelte';

  let { params }: PageProps = $props();
  void params;

  let applied = $state<TrackerSettings>();
  let draft = $state<TrackerSettings>();
  let busy = $state(false);
  let token = $state('');
  let connection = $state<Connection>();
  let queryCheck = $state<QueryCheck>();
  let fieldNames = $state<string[]>([]);
  let working = $state('');

  async function load(team: string): Promise<void> {
    applied = draft = connection = queryCheck = undefined;
    fieldNames = [];
    if (!team) return;
    try {
      const s = await api.TrackerSettings(team);
      if (team !== app.team) return; // the team changed while the answer was on its way
      s.boardId = s.boardId || null;
      applied = s;
      draft = structuredClone(s);
      if (s.source === 'tracker' && s.kind === 'jira' && (s.token.stored || s.token.fromEnv)) {
        fieldNames = await api.TrackerFieldNames(team, s.baseUrl);
      }
    } catch (e) {
      toast(String(e), 'bad');
    }
  }
  $effect(() => {
    void load(app.team);
  });

  const tracker = $derived(draft?.kind === 'csv' ? 'CSV' : 'Jira');
  const production = $derived(app.features?.production ?? false);
  const isTracker = $derived(draft?.source === 'tracker');
  const jira = $derived(isTracker && draft?.kind === 'jira');

  const sourceLabel = (s: unknown) => ({ tracker: tracker, packages: t('Work packages'), none: t('No tickets') })[String(s) as 'tracker'] ?? String(s);
  const byLabel = (v: unknown) => (v === 'field' ? t('Field') : t('Rules'));

  const fields: Field<TrackerSettings>[] = $derived([
    { label: t('Source of the work'), get: (s) => s.source, show: sourceLabel },
    { label: t('Kind of tracker'), get: (s) => s.kind, show: (v) => (v === 'csv' ? t('CSV file') : 'Jira') },
    { label: t('Address'), get: (s) => s.baseUrl },
    { label: t('Query'), get: (s) => s.query },
    { label: t('Field: estimate'), get: (s) => s.fields.estimate },
    { label: t('Field: remaining effort'), get: (s) => s.fields.remaining },
    { label: t('Field: epic'), get: (s) => s.fields.epic },
    { label: t('Field: status'), get: (s) => s.fields.status },
    { label: t('Field: acceptance criteria'), get: (s) => s.fields.acceptance },
    { label: t('Source: product'), get: (s) => s.productBy, show: byLabel },
    { label: t('Field: product'), get: (s) => s.fields.product },
    { label: t('Source: project'), get: (s) => s.projectBy, show: byLabel },
    { label: t('Field: project'), get: (s) => s.fields.project },
    { label: t('Source: refined'), get: (s) => s.refinedBy, show: byLabel },
    { label: t('Field: refined'), get: (s) => s.fields.refined },
    { label: t('Label that marks refined tickets'), get: (s) => s.refinedLabel },
    { label: t('Rule: also refined if'), get: (s) => s.refinedRule },
    { label: t('Source: production share'), get: (s) => s.productionBy, show: (v) => ({ manual: t('By hand only'), rule: t('Rules'), 'field+rule': t('Field, otherwise rules') })[String(v) as 'rule'] },
    { label: t('Field: production share'), get: (s) => s.fields.production },
    { label: t('Label that means 100 percent'), get: (s) => s.productionLabel },
    { label: t('Production rules'), get: (s) => s.prodRules.map((r) => `${r.rule} → ${r.percent} %`), show: (v) => ((v as string[]).length ? (v as string[]).join('; ') : '–') },
    { label: t('Fields for rules'), get: (s) => s.ruleFields.map((f) => `${f.name} = ${f.display}`) },
    { label: t('Write the sprint back'), get: (s) => s.writeSprint },
    { label: t('Board number'), get: (s) => s.boardId || '' },
    { label: t('Removed tickets go to'), get: (s) => s.removedTarget, show: removedLabel },
    { label: t('Label planned_for_<sprint>'), get: (s) => s.writeLabels },
    { label: t('Prefix of work packages'), get: (s) => s.packagePrefix },
  ]);

  function removedLabel(v: unknown): string {
    return ({ '': t('the backlog'), backlog: t('the backlog'), pro_forma: t('a pro-forma sprint'), next: t('the next sprint') })[String(v) as 'next'] ?? String(v);
  }

  const rows = $derived(applied && draft ? changes(fields, applied, draft, { on: t('on'), off: t('off'), none: '–' }) : []);

  async function apply(): Promise<void> {
    if (!draft || !app.team) return;
    const board = draft.boardId;
    if (board !== null && (!Number.isInteger(board) || board < 0 || board > 2_000_000_000)) {
      toast(t('The board number is a positive whole number.'), 'bad');
      return;
    }
    busy = true;
    try {
      await api.SaveTrackerSettings(app.team, draft);
      toast(t('Applied, not saved yet.'), 'ok');
      await load(app.team);
      await loadFeatures();
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }

  function reset(): void {
    if (applied) draft = structuredClone(applied);
  }

  async function guarded(name: string, action: () => Promise<void>): Promise<void> {
    working = name;
    try {
      await action();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = '';
    }
  }

  /** Only the state of the token changes; what the user typed on the page stays. */
  async function refreshToken(): Promise<void> {
    const state = await api.TokenInfo(app.team, draft?.baseUrl ?? '');
    if (applied) applied.token = state;
    if (draft) draft.token = state;
  }

  const test = () =>
    guarded('test', async () => {
      connection = await api.TestTrackerConnection(app.team, draft?.baseUrl ?? '');
      if (connection.ok) fieldNames = await api.TrackerFieldNames(app.team, draft?.baseUrl ?? '');
    });

  const storeToken = () =>
    guarded('token', async () => {
      if (!token.trim()) {
        toast(t('Paste the token first.'), 'bad');
        return;
      }
      await api.SetTrackerToken(app.team, draft?.baseUrl ?? '', token);
      token = '';
      toast(t('Token stored in the keychain.'), 'ok');
      await refreshToken();
    });

  const removeToken = () =>
    guarded('remove', async () => {
      await api.RemoveTrackerToken(app.team, draft?.baseUrl ?? '');
      connection = undefined;
      toast(t('Token removed. Fetching pauses.'), 'ok');
      await refreshToken();
    });

  const testQuery = () =>
    guarded('query', async () => {
      queryCheck = await api.TestTrackerQuery(app.team, draft?.baseUrl ?? '', draft?.query ?? '');
    });

  const syncedAt = $derived(
    applied?.imported ? new Date(applied.imported).toLocaleString(app.prefs?.language ?? 'en') : '',
  );
</script>

<PageHead
  title={t('Tickets and tracker')}
  lead={isTracker ? t('Where the work comes from. Connection to {tracker}, query, field mapping.', { tracker }) : t('Where the work comes from. Applies to the whole team (team.yaml).')}
/>

{#if !app.team}
  <p class="muted">{t('Choose a team first.')}</p>
{:else if draft && applied}
  <div class="card source">
    <h2>{t('Where does the work come from?')}</h2>
    <div class="stack" role="radiogroup" aria-label={t('Source of the work')}>
      <label class="opt">
        <input type="radio" name="source" value="tracker" bind:group={draft.source} />
        <span><strong>{t('From a tracker')}</strong><br /><span class="small muted">{t('Tickets are fetched and only read. Backlog, earmarks and planning work with tickets.')}</span></span>
      </label>
      <label class="opt">
        <input type="radio" name="source" value="packages" bind:group={draft.source} />
        <span><strong>{t('Work packages in Foresprint')}</strong><br /><span class="small muted">{t('You keep them in Foresprint itself. Same flows, no fetch, no links, no assignment rules.')}</span></span>
      </label>
      <label class="opt">
        <input type="radio" name="source" value="none" bind:group={draft.source} />
        <span><strong>{t('No tickets')}</strong><br /><span class="small muted">{t('Amounts per product and project instead of tickets; there is no backlog.')}</span></span>
      </label>
    </div>
  </div>

  {#if draft.source === 'packages'}
    <Banner>
      <strong>{t('Work packages in Foresprint:')}</strong>
      {t('The backlog shows work packages you create by hand; Pre-plan and Plan work with them like with tickets. The product sits on the work package itself, and there are no assignment rules. They are saved with the team data in arbeitspakete.yaml.')}
    </Banner>
    <div class="card pad">
      <div class="field" style="max-width:240px">
        <label for="t-prefix">{t('Prefix of the keys')}</label>
        <input id="t-prefix" class="input data" placeholder="AP" bind:value={draft.packagePrefix} />
      </div>
      <p class="small muted">{t('Keys look like AP-424. Leave empty for AP.')}</p>
    </div>
    <PackageImport ready={applied.source === 'packages'} />
  {:else if draft.source === 'none'}
    <Banner>
      <strong>{t('No tickets:')}</strong>
      {t('Pre-plan holds an amount per product and a split per project, the rest is daily business. Tracker settings are kept here for later but not used.')}
    </Banner>
  {/if}

  {#if isTracker}
    <div class="grid cols-2 pad">
      <div class="card">
        <h2>{t('Kind of tracker')}</h2>
        <div class="field" style="max-width:280px">
          <label for="t-kind">{t('Tracker')}</label>
          <select id="t-kind" class="input" bind:value={draft.kind}>
            <option value="jira">Jira</option>
            <option value="csv">{t('CSV file (export)')}</option>
          </select>
        </div>
        {#if draft.kind === 'csv'}
          <p class="small muted">{t('Tickets come from an export file you read in; there is no connection and no token.')}</p>
        {/if}
      </div>

      {#if jira}
        <div class="card">
          <h2>{t('Connection')}</h2>
          <div class="stack">
            <div class="field">
              <label for="t-url">{t('Address')}</label>
              <input id="t-url" class="input data" placeholder="https://jira.example.org" bind:value={draft.baseUrl} />
            </div>
            <div class="field">
              <label for="t-token">{t('Token')}</label>
              <input
                id="t-token"
                class="input data"
                type="password"
                autocomplete="new-password"
                placeholder={applied.token.stored ? '••••••••••••••••' : t('Paste the token')}
                bind:value={token}
              />
            </div>
            <div class="row">
              <button class="btn" type="button" disabled={working !== ''} onclick={test}><Icon name="network_check" />{t('Test connection')}</button>
              <button class="btn" type="button" disabled={working !== '' || !token} onclick={storeToken}>
                {applied.token.stored ? t('Replace token') : t('Store token')}
              </button>
              <button class="btn danger" type="button" disabled={working !== '' || !applied.token.stored} onclick={removeToken}>
                <Icon name="delete" />{t('Remove')}
              </button>
            </div>
            <div class="small" role="status">
              {#if connection?.ok}
                <span class="chip ok"><Icon name="check_circle" size={14} />{connection.message}</span>
              {:else if connection}
                <span class="chip bad"><Icon name="error" size={14} />{connection.message}</span>
              {:else if applied.token.fromEnv}
                <span class="muted">{t('The token comes from the environment variable {variable}; it wins over the keychain.', { variable: applied.token.variable })}</span>
              {:else if applied.token.stored}
                <span class="muted">{t('Token stored in the keychain of this computer.')}</span>
              {:else}
                <span class="chip warn"><Icon name="warning" size={14} />{t('No token')}</span>
                {#if !applied.token.keychainUsable}
                  <span class="muted">{t('This computer has no keychain; set the environment variable {variable}.', { variable: applied.token.variable })}</span>
                {/if}
              {/if}
            </div>
            <p class="small muted">{t('The token is only kept in the keychain of the operating system, never in the team data. Jira: profile > Personal Access Tokens.')}</p>
          </div>
        </div>

        <div class="card">
          <h2>{t('Fetching')}</h2>
          <dl class="kv">
            <dt>{t('Last fetch')}</dt>
            <dd class="data">{syncedAt || t('never')}</dd>
            <dt>{t('Tickets')}</dt>
            <dd class="data">{applied.tickets}</dd>
          </dl>
          {#if app.status.tracker.failed}
            <p class="small"><span class="chip bad"><Icon name="error" size={14} />{app.status.tracker.failed}</span></p>
          {/if}
          <div class="row top">
            <button class="btn" type="button" disabled={app.busy !== '' || rows.length > 0} onclick={syncTracker}>
              <Icon name="sync" />{app.busy === 'sync' ? t('Fetching …') : t('Fetch now')}
            </button>
            {#if rows.length}<span class="small muted">{t('Apply or discard the changes first.')}</span>{/if}
          </div>
        </div>

        <div class="card full">
          <h2>{t('Query')}</h2>
          <div class="field">
            <label for="t-query">{t('Which tickets Foresprint reads (JQL)')}</label>
            <textarea id="t-query" class="input data" rows="2" bind:value={draft.query}></textarea>
          </div>
          <div class="row top">
            <button class="btn" type="button" disabled={working !== ''} onclick={testQuery}><Icon name="play_arrow" />{t('Test query')}</button>
            {#if queryCheck}
              <span class="chip {queryCheck.ok ? 'ok' : 'bad'}"><Icon name={queryCheck.ok ? 'check_circle' : 'error'} size={14} />{queryCheck.message}</span>
            {/if}
          </div>
        </div>

        <div class="card full" data-tour="settings-writeback">
          <div class="row head">
            <h2>{t('Write to {tracker}', { tracker })}</h2>
            <span class="chip {draft.writeSprint ? 'warn' : ''}">{draft.writeSprint ? t('Writing back on') : t('Read only')}</span>
          </div>
          <p class="small muted">
            {t('The default is read only. When you plan completely in Foresprint, the plan can take the sprint assignment over into {tracker}: only on a button, always with preview and undo. Order, estimate, status and texts stay untouched, and Foresprint never creates, starts or closes sprints. The token needs the right to edit sprints.', { tracker })}
          </p>
          <div class="stack gap">
            <Switch bind:checked={draft.writeSprint} title={t('Write the planned sprint back to {tracker}', { tracker })}>
              {t('Plan offers a button to write the sprint to {tracker}, with preview, per-ticket opt-out and undo; it is logged in the planning minutes.', { tracker })}
            </Switch>
            <div class="field" style="max-width:420px" class:off={!draft.writeSprint}>
              <label for="t-removed">{t('Tickets taken out in planning land in {tracker}', { tracker })}</label>
              <select id="t-removed" class="input" disabled={!draft.writeSprint} bind:value={draft.removedTarget}>
                <option value="backlog">{t('in the backlog (default)')}</option>
                <option value="pro_forma">{t('in a pro-forma sprint')}</option>
                <option value="next">{t('in the next sprint')}</option>
              </select>
            </div>
            {#if jira}
              <div class="field" style="max-width:240px" class:off={!draft.writeSprint}>
                <label for="t-board">{t('Board number')}</label>
                <input id="t-board" class="input data" type="number" min="1" step="1" disabled={!draft.writeSprint} bind:value={draft.boardId} />
                <p class="small muted">{t('The Jira board whose sprints are looked up, so that a sprint without tickets is found too. Leave empty if tickets alone are enough.')}</p>
              </div>
            {/if}
            <Switch bind:checked={draft.writeLabels} title={t('Propose the label planned_for_<sprint> when freezing')}>
              {t('The only other write action: after freezing the plan, as before.')}
            </Switch>
          </div>
        </div>
      {/if}

      <FieldMapping bind:draft {fieldNames} {production} {tracker} />
    </div>
  {/if}

  <ChangesCard {rows} {busy} onapply={apply} onreset={reset} />
{:else}
  <p class="muted">{t('Loading …')}</p>
{/if}

<style>
  .source {
    margin-bottom: 16px;
  }
  .pad {
    margin-bottom: 16px;
  }
  .full {
    grid-column: 1 / -1;
  }
  .opt {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .opt input {
    margin-top: 3px;
  }
  .gap {
    gap: 12px;
  }
  .top {
    margin-top: 12px;
  }
  .head {
    justify-content: space-between;
    margin-bottom: 4px;
  }
  .head h2 {
    margin: 0;
  }
  .off {
    opacity: 0.6;
  }
  p {
    margin: 8px 0 0;
  }
</style>
