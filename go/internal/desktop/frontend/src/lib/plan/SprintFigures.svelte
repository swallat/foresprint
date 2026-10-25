<script lang="ts">
  // The figures strip of Pre-plan and Plan (capacity, Forecast PLAN, plannable, planned,
  // production, contingents) for the pages around them: Prepare, Review and Minutes show the
  // same numbers of the selected sprint (mock of flows.md F3, F5).
  import { app } from '../app.svelte';
  import { assumptions, PlanModel, touched } from './model.svelte';
  import Summary from './Summary.svelte';

  interface Props {
    /** Changes when the page changed something that moves the figures (absences, review). */
    reload?: unknown;
  }
  let { reload = null }: Props = $props();

  const model = new PlanModel();
  $effect(() => {
    void [app.team, app.sprint, reload];
    void model.reload();
  });

  const d = $derived(model.data);
  const used = $derived(d ? (d.source === 'none' ? d.preplanned : d.earmarked) : 0);
</script>

<!-- Only the figures of the selected sprint: after a switch or a failed load the old ones are not shown. -->
{#if d && d.sprint === app.sprint && !model.error}
  <Summary {d} {used} commitment={d.frozen ? d.committed : null} assumption={touched(assumptions.active, d.source !== 'none') ? assumptions.active?.label : ''} whatIf={model.running} {model} />
{/if}
