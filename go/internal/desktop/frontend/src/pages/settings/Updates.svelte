<script lang="ts">
  import { app, toast } from '../../lib/app.svelte';
  import { api } from '../../lib/api';
  import { openExternal } from '../../lib/external';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { UpdateInfo } from '../../lib/types.settings';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  let info = $state<UpdateInfo>();
  let working = $state<'' | 'check' | 'install'>('');
  let checked = $state(false);

  function show(next: UpdateInfo): void {
    info = next;
    app.update = next.available ? next : undefined;
  }

  async function run(kind: 'check' | 'install', call: () => Promise<UpdateInfo>): Promise<void> {
    working = kind;
    try {
      show(await call());
      if (kind === 'check') checked = true;
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      working = '';
    }
  }

  async function setMode(mode: string): Promise<void> {
    try {
      await api.SetUpdateMode(mode);
      if (info) info = { ...info, mode: mode as UpdateInfo['mode'] };
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  $effect(() => {
    void api
      .UpdateStatus()
      .then((s) => (info = s))
      .catch((e) => toast(String(e), 'bad'));
  });

  const modes = $derived([
    { code: 'on', label: t('Look for new versions'), hint: t('Once a day at the start. Installing is always your click.') },
    { code: 'notice', label: t('Only tell me'), hint: t('Same check; the command line only reports and never installs.') },
    { code: 'off', label: t('Never look'), hint: t('The program does not contact GitHub by itself.') },
  ]);

  function when(iso: string): string {
    return iso ? new Date(iso).toLocaleString(app.prefs?.language ?? 'en') : t('never');
  }
</script>

<PageHead title={t('Updates')} lead={t('New versions of Foresprint come from the releases on GitHub.')} />

{#if info}
  <div class="stack gap">
    {#if info.dev}
      <Banner tone="info">{t('This is a development build. It does not update itself; install a release instead.')}</Banner>
    {:else if info.restart}
      <Banner tone="info">{t('Version {latest} is installed. Close Foresprint and start it again to use it.', { latest: info.latest })}</Banner>
    {:else if info.available}
      <Banner tone="info">
        {t('Version {latest} is available (installed: {version}).', { latest: info.latest, version: info.version })}
        {#snippet action()}
          <button class="btn primary" type="button" disabled={!!working} onclick={() => run('install', api.InstallUpdate)}>
            <Icon name="download" />{working === 'install' ? t('Installing …') : t('Install')}
          </button>
        {/snippet}
      </Banner>
    {:else if checked}
      <Banner tone="info">{t('Version {version} is the latest.', { version: info.version })}</Banner>
    {/if}

    <div class="card">
      <h2>{t('Version')}</h2>
      <dl class="facts">
        <dt>{t('Installed')}</dt>
        <dd class="data">{info.version}</dd>
        <dt>{t('Newest known')}</dt>
        <dd class="data">{info.latest || '–'}</dd>
        <dt>{t('Last check')}</dt>
        <dd>{when(info.lastCheck)}</dd>
      </dl>
      <div class="row">
        <button class="btn" type="button" disabled={!!working || info.dev} onclick={() => run('check', () => api.CheckUpdate(false))}>
          <Icon name="sync" />{working === 'check' ? t('Looking …') : t('Check now')}
        </button>
        {#if info.url}
          <button class="btn ghost" type="button" onclick={() => openExternal(info?.url ?? '')}>
            <Icon name="open_in_new" />{t('Release notes')}
          </button>
        {/if}
      </div>
      <p class="small muted">{t('The program checks the download against the checksums of the release. Installing replaces the program file; your data is not touched.')}</p>
    </div>

    <div class="card">
      <h2>{t('Automatic check')}</h2>
      <div class="row" role="group" aria-label={t('Automatic check')}>
        {#each modes as m (m.code)}
          <button
            type="button"
            class="chip filter"
            class:on={info.mode === m.code}
            aria-pressed={info.mode === m.code}
            disabled={info.modeEnv}
            title={m.hint}
            data-setting="update-mode"
            onclick={() => setMode(m.code)}
          >
            {m.label}
          </button>
        {/each}
      </div>
      <p class="small muted">{modes.find((m) => m.code === info?.mode)?.hint}</p>
      {#if info.modeEnv}
        <p class="small muted">{t('The environment variable FORESPRINT_AUTOUPDATE takes precedence.')}</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  .gap {
    gap: 16px;
  }
  .facts {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 16px;
    margin: 0 0 12px;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
  }
  p {
    margin: 8px 0 0;
  }
</style>
