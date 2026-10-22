<script lang="ts">
  import { api } from '../api';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    id: string;
    label: string;
    value: string;
    /** Rule fields registered on the page but maybe not saved yet. */
    extra?: string[];
    placeholder?: string;
  }
  let { id, label, value = $bindable(), extra = [], placeholder }: Props = $props();

  let problem = $state('');
  let version = 0;

  // The check runs in Go with the grammar of the rules, so the window never disagrees with it.
  $effect(() => {
    const text = value;
    const sources = [...extra];
    const mine = ++version;
    const timer = setTimeout(async () => {
      try {
        const r = await api.CheckRule(text, sources);
        if (mine === version) problem = r.ok ? '' : r.message;
      } catch {
        if (mine === version) problem = '';
      }
    }, 250);
    return () => clearTimeout(timer);
  });
</script>

<div class="rule">
  <input {id} class="input data rule-txt" aria-label={label} aria-invalid={problem !== ''} {placeholder} bind:value />
  {#if problem}
    <div class="small err" role="status"><Icon name="error" size={14} /> {problem}</div>
  {/if}
</div>

<style>
  .rule {
    min-width: 240px;
    width: 100%;
  }
  .rule input {
    width: 100%;
  }
  input[aria-invalid='true'] {
    border-color: var(--bad);
  }
  .err {
    color: var(--bad);
    margin-top: 4px;
    display: flex;
    gap: 4px;
    align-items: flex-start;
  }
</style>
