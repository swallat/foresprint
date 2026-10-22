<script lang="ts">
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { current, link, match } from '../lib/router.svelte';
  import { nav, pages } from '../lib/routes';

  const team = $derived(app.teams.find((x) => x.key === app.team));
  const active = $derived(pages.find((p) => match(p.path, current.path))?.nav ?? current.path);

  function close(): void {
    app.railOpen = false;
  }
</script>

<nav class="rail" class:open={app.railOpen} aria-label={t('Main navigation')}>
  {#each nav as group, i (i)}
    {#if group.label}
      <h6>{t(group.label)}{#if group.sprint && app.sprint} <span class="data">{app.sprint}</span>{/if}</h6>
    {/if}
    {#each group.items as item (item.path)}
      {#if item.needs !== 'tickets' || team?.tickets !== false}
        <a href={link(item.path)} class:active={active === item.path} class:sub={item.sub} aria-current={active === item.path ? 'page' : undefined} onclick={close}>
          <Icon name={item.icon} /><span>{t(item.label)}</span>
          {#if item.path === '/data/conflicts' && app.status.storage === 'conflict'}
            <span class="count" style="color: var(--bad)">!</span>
          {/if}
          {#if item.path === '/data' && app.status.findings > 0}
            <span class="count" title={t('Findings of the data check')}>{app.status.findings}</span>
          {/if}
        </a>
      {/if}
    {/each}
  {/each}
</nav>
