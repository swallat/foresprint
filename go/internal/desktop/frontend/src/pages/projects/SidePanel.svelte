<script lang="ts">
  import { onDestroy, onMount, type Snippet } from 'svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';

  interface Props {
    title: string;
    onclose: () => void;
    /** True while the panel holds input that closing would throw away: it asks first. */
    dirty?: boolean;
    /** Gets a close function that asks first when the panel is dirty. */
    children: Snippet<[() => void]>;
  }
  let { title, onclose, dirty = false, children }: Props = $props();
  let asking = $state(false);

  function close(): void {
    if (dirty && !asking) {
      asking = true;
      return;
    }
    onclose();
  }
  let panel: HTMLElement | undefined = $state();

  // The button that opened the panel gets the focus back when the panel closes.
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
  onDestroy(() => {
    if (opener?.isConnected) opener.focus();
  });

  onMount(() => {
    const first = panel?.querySelector<HTMLElement>('input, select, textarea, button.primary');
    first?.focus();
  });

  function key(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.stopPropagation();
      if (asking) asking = false;
      else close();
    }
  }
</script>

<svelte:window onkeydown={key} />

<div class="panel" role="dialog" aria-modal="false" aria-label={title} bind:this={panel}>
  <div class="panel-head">
    <h2 style="margin:0;flex:1">{title}</h2>
    <button type="button" class="btn icon ghost" aria-label={t('Close')} onclick={close}><Icon name="close" /></button>
  </div>
  {#if asking}
    <div class="banner warn" role="alert">
      <Icon name="warning" />
      <div class="grow">{t('Discard your changes?')}</div>
      <button type="button" class="btn" onclick={() => (asking = false)}>{t('Keep editing')}</button>
      <button type="button" class="btn" onclick={onclose}>{t('Discard')}</button>
    </div>
  {/if}
  <div class="panel-body">{@render children(close)}</div>
</div>
