<script lang="ts">
  import { browser, copyBrowserLink, inBrowserPage, loadBrowser, openInBrowser } from '../lib/browserAccess.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { link } from '../lib/router.svelte';

  let open = $state(false);
  let root: HTMLElement | undefined = $state();

  $effect(() => {
    void loadBrowser();
  });

  $effect(() => {
    if (!open) return;
    const onDown = (ev: PointerEvent) => {
      if (root && !root.contains(ev.target as Node)) open = false;
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') open = false;
    };
    window.addEventListener('pointerdown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  });

  async function run(action: () => Promise<void>): Promise<void> {
    open = false;
    await action();
  }
</script>

{#if browser.available && !inBrowserPage}
  <div class="menu" bind:this={root}>
    <button class="btn icon ghost" class:on={browser.running} type="button" aria-haspopup="menu" aria-expanded={open} aria-label={t('Browser')} title={browser.running ? t('The browser access is on') : t('Show in the browser')} onclick={() => (open = !open)}>
      <Icon name="open_in_browser" />
    </button>
    {#if open}
      <div class="pop" role="menu" aria-label={t('Browser')}>
        <button class="item" type="button" role="menuitem" onclick={() => run(openInBrowser)}><Icon name="open_in_new" />{t('Open in browser')}</button>
        <button class="item" type="button" role="menuitem" onclick={() => run(copyBrowserLink)}><Icon name="content_copy" />{t('Copy browser link')}</button>
        <a class="item" role="menuitem" href={link('/settings/browser')} onclick={() => (open = false)}><Icon name="tune" />{t('Browser settings')}</a>
      </div>
    {/if}
  </div>
{/if}

<style>
  .menu {
    position: relative;
    flex: none;
  }
  .on {
    color: var(--accent);
  }
  .pop {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 36;
    min-width: 220px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-card);
    box-shadow: var(--shadow);
  }
  .item {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 36px;
    padding: 0 10px;
    border: 0;
    border-radius: var(--r-ctl);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }
  .item:hover,
  .item:focus-visible {
    background: var(--surface-2);
  }
</style>
