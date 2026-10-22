<script lang="ts">
  import Calc from '../../lib/calc/Calc.svelte';
  import { t } from '../../lib/i18n.svelte';
  import type { ProjectView } from '../../lib/types.projects';
  import { num } from './format';

  interface Props {
    project: ProjectView;
    /** Points per person day; no calculation is shown without it. */
    rate: number | null;
    kind: 'done' | 'planned';
  }
  let { project, rate, kind }: Props = $props();

  const points = $derived(kind === 'done' ? project.donePoints : project.plannedPoints);
  const pd = $derived(kind === 'done' ? project.done : project.planned);
</script>

{#if rate !== null && pd !== null}
  <Calc label={kind === 'done' ? t('Done work of {name}', { name: project.name }) : t('Planned work of {name}', { name: project.name })} topic="rate">
    {t('{points} points ÷ {rate} points per person day = {pd} PD (estimate)', { points: num(points, 1), rate: num(rate, 2), pd: num(pd, 1) })}
  </Calc>
{/if}
