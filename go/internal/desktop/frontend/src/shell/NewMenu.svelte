<script lang="ts">
  import { tick } from 'svelte';
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import type { IconName } from '../lib/icons';
  import { current, link } from '../lib/router.svelte';

  let open = $state(false);
  let root: HTMLElement | undefined = $state();
  let trigger: HTMLButtonElement | undefined = $state();
  let pop: HTMLElement | undefined = $state();

  // Each entry opens the page that owns the thing with the form for a new one ("new" in the address).
  const entries: { icon: IconName; label: () => string; path: string; query: Record<string, string>; needsTeam: boolean }[] = [
    { icon: 'groups', label: () => t('Create a new team'), path: '/setup', query: { add: 'team' }, needsTeam: false },
    { icon: 'person_add', label: () => t('Add person'), path: '/team/people', query: { new: '1' }, needsTeam: true },
    { icon: 'category', label: () => t('Add product'), path: '/team/products', query: { new: '1' }, needsTeam: true },
    { icon: 'flag', label: () => t('New project'), path: '/projects', query: { new: '1' }, needsTeam: true },
  ];

  const blocked = (e: (typeof entries)[number]) => e.needsTeam && !app.team;

  function choose(e: (typeof entries)[number]): void {
    if (blocked(e)) return;
    open = false;
    // On the target page itself the address is replaced, so Back does not show the page twice.
    if (current.path === e.path) location.replace(link(e.path, {}, e.query));
    else location.hash = link(e.path, {}, e.query);
  }

  function items(): HTMLButtonElement[] {
    return Array.from(pop?.querySelectorAll<HTMLButtonElement>('[role=menuitem]:not([aria-disabled=true])') ?? []);
  }

  async function toggle(): Promise<void> {
    open = !open;
    if (open) {
      await tick();
      items()[0]?.focus();
    }
  }

  function close(refocus: boolean): void {
    open = false;
    if (refocus) trigger?.focus();
  }

  function onMenuKey(ev: KeyboardEvent): void {
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const to = ev.key === 'ArrowDown' ? at + 1 : ev.key === 'ArrowUp' ? at - 1 : ev.key === 'Home' ? 0 : ev.key === 'End' ? list.length - 1 : undefined;
    if (to === undefined || list.length === 0) return;
    ev.preventDefault();
    list[(to + list.length) % list.length]?.focus();
  }

  $effect(() => {
    if (!open) return;
    const onDown = (ev: PointerEvent) => {
      if (root && !root.contains(ev.target as Node)) open = false;
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') close(true);
    };
    window.addEventListener('pointerdown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  });
</script>

<div class="new" bind:this={root} onfocusout={(ev) => { if (open && !root?.contains(ev.relatedTarget as Node | null)) open = false; }}>
  <button
    class="btn icon primary"
    type="button"
    bind:this={trigger}
    data-tour="topbar-new"
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label={t('Create new')}
    title={t('Create new')}
    onclick={toggle}
  >
    <Icon name="add" />
  </button>
  {#if open}
    <div class="pop" role="menu" tabindex="-1" aria-label={t('Create new')} bind:this={pop} onkeydown={onMenuKey}>
      {#each entries as e (e.path + e.label())}
        <button class="item" type="button" role="menuitem" aria-disabled={blocked(e)} onclick={() => choose(e)}>
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
  .pop {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
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
    cursor: pointer;
  }
  .item:hover:not([aria-disabled='true']),
  .item:focus-visible {
    background: var(--surface-2);
  }
  .item[aria-disabled='true'] {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
