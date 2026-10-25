<script lang="ts" module>
  /** Jira accepts the name in any letter case and the id (customfield_10002) of a field as well. */
  export function isKnownField(value: string, names: string[]): boolean {
    if (names.length === 0 || value === '') return true;
    if (/^customfield_\d+$/i.test(value.trim())) return true;
    const low = value.trim().toLowerCase();
    return names.some((n) => n.toLowerCase() === low);
  }
</script>

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

  const other = '\u0000other';
  let typing = $state(false);
  // A saved value the list does not show (an id, an ambiguous name) stays editable as text.
  const asText = $derived(names.length === 0 || typing || (value !== '' && !names.includes(value)));

  function choose(e: Event): void {
    const v = (e.currentTarget as HTMLSelectElement).value;
    if (v === other) typing = true;
    else value = v;
  }
</script>

{#if asText}
  <div class="pick">
    <input class="input" aria-label={label} {placeholder} bind:value />
    {#if names.length}
      <button class="btn ghost" type="button" onclick={() => { typing = false; if (!names.includes(value)) value = ''; }}>{t('Choose from the list')}</button>
    {/if}
  </div>
{:else}
  <select class="input" aria-label={label} {value} onchange={choose}>
    <option value="">{placeholder || t('not set')}</option>
    {#each names as n (n)}<option value={n}>{n}</option>{/each}
    <option value={other}>{t('Other (type the name or id)')}</option>
  </select>
{/if}

<style>
  .pick {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .pick .input {
    flex: 1;
  }
</style>
