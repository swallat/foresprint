<script lang="ts">
  import { t } from '../i18n.svelte';

  interface Props {
    value: string;
    /** Names of the fields of the tracker; empty while there is no connection (a text field then). */
    names: string[];
    label: string;
    placeholder?: string;
  }
  let { value = $bindable(), names, label, placeholder = '' }: Props = $props();

  // A saved name that the tracker does not list stays visible, so that nothing is lost silently.
  const unknown = $derived(value !== '' && !names.includes(value));
</script>

{#if names.length}
  <select class="input" aria-label={label} bind:value>
    <option value="">{placeholder || t('not set')}</option>
    {#if unknown}<option {value}>{t('{name} (not found)', { name: value })}</option>{/if}
    {#each names as n (n)}<option value={n}>{n}</option>{/each}
  </select>
{:else}
  <input class="input" aria-label={label} {placeholder} bind:value />
{/if}
