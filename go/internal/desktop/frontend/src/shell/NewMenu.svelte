<script lang="ts">
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import type { IconName } from '../lib/icons';
  import { go } from '../lib/router.svelte';

  let open = $state(false);
  let root: HTMLElement | undefined = $state();

  // Each entry opens the page that owns the thing with the form for a new one ("new" in the address).
  const entries: { icon: IconName; label: () => string; run: () => void }[] = [
    { icon: 'groups', label: () => t('Create a new team'), run: () => go('/setup', {}, { add: 'team' }) },
    { icon: 'person_add', label: () => t('Add person'), run: () => go('/team/people', {}, { new: '1' }) },
    { icon: 'category', label: () => t('Add product'), run: () => go('/team/products', {}, { new: '1' }) },
    { icon: 'flag', label: () => t('New project'), run: () => go('/projects', {}, { new: '1' }) },
  ];

  function choose(run: () => void): void {
    open = false;
    run();
  }

  $effect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (root && !root.contains(e.target as Node)) open = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') open = false;
    };
    window.addEventListener('pointerdown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  });
</script>

<div class="new" bind:this={root}>
  <button
    class="btn icon plus"
    type="button"
    data-tour="topbar-new"
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label={t('Create new')}
    title={t('Create new')}
    onclick={() => (open = !open)}
  >
    <Icon name="add" />
  </button>
  {#if open}
    <div class="pop" role="menu" aria-label={t('Create new')}>
      {#each entries as e, i (i)}
        <button class="item" type="button" role="menuitem" disabled={i > 0 && !app.team} onclick={() => choose(e.run)}>
          <Icon name={e.icon} />{e.label()}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .new {
    position: relative;
    flex: none;
  }
  .plus {
    background: var(--primary);
    border-color: var(--primary);
    color: var(--on-primary);
  }
  .plus:hover {
    background: var(--primary);
    filter: brightness(1.08);
  }
  .pop {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 20;
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
    cursor: pointer;
  }
  .item:hover:not([disabled]),
  .item:focus-visible {
    background: var(--surface-2);
  }
  .item[disabled] {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
