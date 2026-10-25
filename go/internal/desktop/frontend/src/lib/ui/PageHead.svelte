<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title: string;
    /** One sentence under the title. Keep it short; details go in an expander. */
    lead?: string;
    actions?: Snippet;
  }
  let { title, lead, actions }: Props = $props();
</script>

<div class="page-head">
  <div>
    <h1>{title}</h1>
    {#if lead}<p class="lead">{lead}</p>{/if}
  </div>
  {#if actions}<div class="actions">{@render actions()}</div>{/if}
</div>
