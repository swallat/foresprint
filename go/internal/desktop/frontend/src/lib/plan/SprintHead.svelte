<script lang="ts">
  // Title, lead and stage steps of the sprint workspace for Pre-plan and Plan. The steps are
  // links, never gates: every stage opens at any time and says what is missing.
  import type { Snippet } from 'svelte';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { PlanSprint } from '../types.plan';
  import SprintMeta from '../sprints/SprintMeta.svelte';
  import PageHead from '../ui/PageHead.svelte';
  import { itemWord } from './model.svelte';
  import StartSprint from './StartSprint.svelte';

  interface Props {
    d: PlanSprint;
    stage: 'preplan' | 'plan';
    actions?: Snippet;
    /** Called after the sprint was started or its start taken back, to read the page again. */
    onchange?: () => void | Promise<void>;
  }
  let { d, stage, actions, onchange }: Props = $props();

  const steps = $derived([
    { id: 'prepare', label: t('Prepare'), missing: d.absences !== 'confirmed' ? t('Absences are not confirmed.') : '' },
    {
      id: 'preplan',
      label: t('Pre-plan'),
      missing:
        d.multiProduct && d.products.some((p) => p.active && p.pre == null)
          ? t('An amount is missing for some products.')
          : '',
    },
    { id: 'plan', label: t('Plan'), missing: d.stage === 'open' ? t('The plan is not frozen yet.') : '' },
    { id: 'review', label: t('Review'), missing: '' },
    { id: 'minutes', label: t('Minutes'), missing: '' },
  ]);

  const stageChip = $derived(
    { past: t('closed'), current: t('running'), planned: t('planned'), open: t('open') }[d.stage],
  );
  const lead = $derived(
    stage === 'preplan'
      ? d.source === 'none'
        ? t('Set the amount per product and project. Works at any time, also for later sprints.')
        : t('Earmark {items} and set the amount per product. Works at any time, also for later sprints.', {
            items: itemWord(d),
          })
      : d.source === 'none'
        ? t('Agree on the amounts and the commitment together.')
        : t('Take {items} into the sprint together until the sum, products and projects fit.', { items: itemWord(d) }),
  );
  const hint = $derived(steps.find((s) => s.id === stage)?.missing ?? '');
</script>

<PageHead title={stage === 'preplan' ? t('Pre-plan') : t('Plan')} {lead} {actions} />
<SprintMeta>
  {#snippet extra()}
    {#if d.sprint === app.sprint}
      <span aria-hidden="true">·</span>
      <span class="chip">{stageChip}</span>
      <span>{t('{n} working days', { n: d.days })}</span>
    {/if}
  {/snippet}
</SprintMeta>
{#if d.sprint === app.sprint}
  <StartSprint sprint={d.sprint} start={d.start} end={d.end} startedOn={d.startedOn} due={d.startDue} running={d.stage === 'current'} {onchange} />
{/if}
<nav class="stepper" aria-label={t('Stages of the sprint')}>
  {#each steps as s, i (s.id)}
    <a
      href={`#/sprint/${s.id}`}
      class:active={s.id === stage}
      class:done={!s.missing && s.id !== 'minutes' && s.id !== 'review'}
      aria-current={s.id === stage ? 'step' : undefined}
    >
      <span class="n">{#if !s.missing && s.id !== 'minutes' && s.id !== 'review'}<Icon name="check" size={14} />{:else}{i + 1}{/if}</span>
      {s.label}
      {#if s.missing}<span class="chip warn" title={s.missing}>{t('still missing')}</span>{/if}
    </a>
  {/each}
</nav>
{#if hint && stage !== 'plan'}
  <div class="banner info"><Icon name="info" /><div class="grow">{hint} {t('The page works with the data at hand.')}</div></div>
{/if}
