<script lang="ts">
  import { api } from '../../lib/api';
  import { openExternal } from '../../lib/external';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  const repo = 'https://github.com/swallat/foresprint';

  let version = $state('');
  let notices = $state('');
  let showNotices = $state(false);

  $effect(() => {
    void api
      .UpdateStatus()
      .then((s) => (version = s.version))
      .catch(() => {});
  });

  // The texts of all third-party licences are large; they load when opened.
  async function toggleNotices(): Promise<void> {
    showNotices = !showNotices;
    if (showNotices && !notices) notices = (await import('../../assets/third-party-notices.txt?raw')).default;
  }
</script>

<PageHead title={t('About Foresprint')} lead={t('Velocity and capacity forecasts for Scrum teams.')} />

<div class="stack gap">
  <div class="card">
    <dl class="facts">
      <dt>{t('Version')}</dt>
      <dd class="data">{version || '–'}</dd>
      <dt>{t('Copyright')}</dt>
      <dd>© 2026 Sebastian Wallat</dd>
      <dt>{t('License')}</dt>
      <dd>{t('European Union Public Licence v. 1.2 (EUPL-1.2)')}</dd>
    </dl>
    <div class="row">
      <button class="btn ghost" type="button" onclick={() => openExternal(repo)}>
        <Icon name="open_in_new" />{t('Project page')}
      </button>
      <button class="btn ghost" type="button" onclick={() => openExternal(`${repo}/blob/main/LICENSE`)}>
        <Icon name="open_in_new" />{t('License text')}
      </button>
    </div>
  </div>

  <div class="card">
    <h2>{t('Third-party components')}</h2>
    <p class="small muted">
      {t('Foresprint contains the fonts Iosevka and Iosevka Aile (SIL Open Font License 1.1), the icons of Material Symbols (Apache License 2.0), Svelte (MIT) and Go libraries under MIT, BSD and Apache licenses. Their license texts follow.')}
    </p>
    <button class="btn" type="button" aria-expanded={showNotices} onclick={toggleNotices}>
      <Icon name={showNotices ? 'keyboard_arrow_up' : 'keyboard_arrow_down'} />{showNotices ? t('Hide license texts') : t('Show license texts')}
    </button>
    {#if showNotices}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <pre class="notices data small" tabindex="0" aria-label={t('License texts')}>{notices || t('Loading …')}</pre>
    {/if}
  </div>
</div>

<style>
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
  .notices {
    max-height: 28rem;
    overflow: auto;
    white-space: pre-wrap;
    margin: 12px 0 0;
    padding: 12px;
    border: 1px solid var(--border, currentColor);
    border-radius: 6px;
  }
</style>
