<script lang="ts">
  // The line under the title of every sprint page: sprint ID, first and last day. Pre-plan and
  // Plan add the state and the working days; the other pages only know the sprint in focus.
  import type { Snippet } from 'svelte';
  import { app } from '../app.svelte';
  import { formatPeriod } from '../format';
  import { t } from '../i18n.svelte';

  interface Props {
    /** The sprint's own figures, if the page has them; else the selected sprint of the app. */
    sprint?: { id: string; start: string; end: string };
    extra?: Snippet;
  }
  let { sprint, extra }: Props = $props();

  const s = $derived(sprint ?? app.sprints.find((x) => x.id === app.sprint));
</script>

{#if s}
  <p class="small muted sprint-meta">
    <span class="data">{t('Sprint')} {s.id}</span>
    <span aria-hidden="true">·</span>
    <span class="data">{formatPeriod(s.start, s.end)}</span>
    {@render extra?.()}
  </p>
{/if}

<style>
  .sprint-meta {
    margin: -8px 0 12px;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
</style>
