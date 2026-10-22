<script lang="ts">
  // The stage steps of the sprint workspace on Prepare, Review and Minutes (Pre-plan and Plan
  // carry the same steps in their own header). The steps are links, never gates: every stage
  // opens at any time and "still missing" is only a hint.
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    stage: 'prepare' | 'review' | 'minutes';
    /** Hints per stage id; an empty text means nothing is missing. */
    missing?: Partial<Record<'prepare' | 'preplan' | 'plan', string>>;
  }
  let { stage, missing = {} }: Props = $props();

  const steps = $derived([
    { id: 'prepare', label: t('Prepare'), missing: missing.prepare ?? '' },
    { id: 'preplan', label: t('Pre-plan'), missing: missing.preplan ?? '' },
    { id: 'plan', label: t('Plan'), missing: missing.plan ?? '' },
    { id: 'review', label: t('Review'), missing: '' },
    { id: 'minutes', label: t('Minutes'), missing: '' },
  ]);
  const check = (id: string, hint: string) => !hint && id !== 'review' && id !== 'minutes';
</script>

<nav class="stepper" aria-label={t('Stages of the sprint')} data-tour="sprint-stepper">
  {#each steps as s, i (s.id)}
    <a href={`#/sprint/${s.id}`} class:active={s.id === stage} class:done={check(s.id, s.missing)} aria-current={s.id === stage ? 'step' : undefined}>
      <span class="n">{#if check(s.id, s.missing)}<Icon name="check" size={14} />{:else}{i + 1}{/if}</span>
      {s.label}
      {#if s.missing}<span class="chip warn" title={s.missing}>{t('still missing')}</span>{/if}
    </a>
  {/each}
</nav>
