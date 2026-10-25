<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    checked: boolean;
    title: string;
    children?: Snippet;
    onchange?: (checked: boolean) => void;
  }
  let { checked = $bindable(), title, children, onchange }: Props = $props();
</script>

<label class="sw">
  <input type="checkbox" bind:checked onchange={() => onchange?.(checked)} />
  <span>
    <strong>{title}</strong>
    {#if children}<br /><span class="small muted">{@render children()}</span>{/if}
  </span>
</label>

<style>
  .sw {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  input {
    margin-top: 3px;
  }
</style>
