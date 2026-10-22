<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';

  interface Props {
    title: string;
    onclose: () => void;
    children: Snippet;
  }
  let { title, onclose, children }: Props = $props();
  let panel: HTMLElement | undefined = $state();

  onMount(() => {
    const first = panel?.querySelector<HTMLElement>('input, select, textarea, button.primary');
    first?.focus();
  });

  function key(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<svelte:window onkeydown={key} />

<div class="panel" role="dialog" aria-modal="false" aria-label={title} bind:this={panel}>
  <div class="panel-head">
    <h2 style="margin:0;flex:1">{title}</h2>
    <button type="button" class="btn icon ghost" aria-label={t('Close')} onclick={onclose}><Icon name="close" /></button>
  </div>
  <div class="panel-body">{@render children()}</div>
</div>
