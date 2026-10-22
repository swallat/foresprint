<script lang="ts">
  // The calculation next to a number: a calculator button that opens it in place, or shown
  // always, or not at all, by the personal setting (data-calc on the document). The full
  // explanation of every formula is Help > Calculations.
  import type { Snippet } from 'svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    /** Short name of what is calculated, for the button's label. */
    what: string;
    children: Snippet;
  }
  let { what, children }: Props = $props();
  let open = $state(false);
  const mode = $derived(document.documentElement.dataset.calc ?? 'icon');
</script>

<button
  class="btn icon ghost calc-btn"
  type="button"
  aria-expanded={open}
  aria-label={t('Show calculation: {what}', { what })}
  onclick={() => (open = !open)}
>
  <Icon name="calculate" />
</button>
{#if mode !== 'off' && (open || mode === 'inline')}
  <div class="calc-inline" role="note">{@render children()}</div>
{/if}
