<script lang="ts">
  import { app } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { current, link } from '../../lib/router.svelte';

  // The three pages of the area Data as tabs (flows.md: Overview, Conflicts, History and tags).
  const tabs = [
    { path: '/data', icon: 'database', label: 'Overview' },
    { path: '/data/conflicts', icon: 'call_split', label: 'Conflicts' },
    { path: '/data/history', icon: 'history', label: 'History and tags' },
  ] as const;
</script>

<nav class="tabs" aria-label={t('Data')}>
  {#each tabs as tab (tab.path)}
    <a href={link(tab.path)} data-tour={tab.path === '/data/conflicts' ? 'data-conflicts' : tab.path === '/data/history' ? 'data-history' : undefined} class:active={current.path === tab.path} aria-current={current.path === tab.path ? 'page' : undefined}>
      <Icon name={tab.icon} />{t(tab.label)}
      {#if tab.path === '/data/conflicts' && (app.status.data?.conflicts ?? 0) > 0}
        <span class="chip bad data">{app.status.data.conflicts}</span>
      {/if}
    </a>
  {/each}
</nav>
