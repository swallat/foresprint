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
    { id: 'prepare', label: t('Prepare'), missing: missing.prepare ?? '', known: missing.prepare !== undefined },
    { id: 'preplan', label: t('Pre-plan'), missing: missing.preplan ?? '', known: missing.preplan !== undefined },
    { id: 'plan', label: t('Plan'), missing: missing.plan ?? '', known: missing.plan !== undefined },
    { id: 'review', label: t('Review'), missing: '', known: false },
    { id: 'minutes', label: t('Minutes'), missing: '', known: false },
  ]);
  // A tick only where the page knows the stage is complete; no hint given means nothing is known.
  const check = (s: { known: boolean; missing: string }) => s.known && !s.missing;
</script>

<nav class="stepper" aria-label={t('Stages of the sprint')} data-tour="sprint-stepper">
  {#each steps as s, i (s.id)}
    <a href={`#/sprint/${s.id}`} class:active={s.id === stage} class:done={check(s)} aria-current={s.id === stage ? 'step' : undefined}>
      <span class="n">{#if check(s)}<Icon name="check" size={14} />{:else}{i + 1}{/if}</span>
      {s.label}
      {#if s.missing}<span class="chip warn" title={s.missing}>{t('still missing')}</span>{/if}
    </a>
  {/each}
</nav>
