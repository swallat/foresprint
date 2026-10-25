<script lang="ts">
  // A panel on the right edge for one thing at a time (times of a person, absences, a product to
  // end). It is no dialog: the page stays usable next to it. Escape and the button close it.
  import type { Snippet } from 'svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    title: string;
    onclose: () => void;
    children: Snippet;
  }
  let { title, onclose, children }: Props = $props();
  let closeButton: HTMLButtonElement | undefined = $state();

  $effect(() => {
    closeButton?.focus();
  });

  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<svelte:window onkeydown={key} />

<aside class="panel" aria-label={title}>
  <div class="panel-head">
    <strong class="grow">{title}</strong>
    <button class="btn icon ghost" type="button" aria-label={t('Close')} title={t('Close')} onclick={onclose} bind:this={closeButton}>
      <Icon name="close" />
    </button>
  </div>
  <div class="panel-body">{@render children()}</div>
</aside>

<style>
  .panel {
    width: min(540px, 100vw);
  }
  .grow {
    flex: 1;
  }
</style>
