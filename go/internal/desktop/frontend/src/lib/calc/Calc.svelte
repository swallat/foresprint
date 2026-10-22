<script lang="ts">
  import type { Snippet } from 'svelte';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    /** What the number is, for the button's name and the panel title ("Forecast PLAN"). */
    label: string;
    /** The short calculation with this sprint's numbers. */
    children: Snippet;
    /** Anchor of the full explanation on Help > Calculations ("rate"). */
    topic?: string;
  }
  let { label, children, topic }: Props = $props();

  let open = $state(false);
  const id = $props.id();
  const helpHref = $derived(`#/help/calculations${topic ? `?topic=${encodeURIComponent(topic)}` : ''}`);
</script>

<!-- The personal setting decides: hidden, a calculator button that opens the calculation in
     place, or the calculation always open below the number. -->
{#if app.calcMode === 'icon'}
  <button
    type="button"
    class="btn ghost icon calc-btn"
    aria-expanded={open}
    aria-controls={id}
    aria-label={t('Calculation of {name}', { name: label })}
    title={t('Calculation of {name}', { name: label })}
    onclick={() => (open = !open)}
  >
    <Icon name="calculate" size={18} />
  </button>
  {#if open}
    <div class="calc-panel" {id} role="group" aria-label={t('Calculation of {name}', { name: label })}>
      <div class="body">{@render children()}</div>
      <a class="small" href={helpHref}>{t('Formula and special cases')}</a>
    </div>
  {/if}
{:else if app.calcMode === 'inline'}
  <div class="calc-panel inline" {id} role="group" aria-label={t('Calculation of {name}', { name: label })}>
    <div class="small muted title"><Icon name="calculate" size={16} /> {t('Calculation of {name}', { name: label })}</div>
    <div class="body">{@render children()}</div>
    <a class="small" href={helpHref}>{t('Formula and special cases')}</a>
  </div>
{/if}

<style>
  .calc-btn {
    width: 28px;
    height: 28px;
    color: var(--text-muted);
  }
  .calc-btn[aria-expanded='true'] {
    color: var(--primary);
    background: var(--primary-weak);
  }
  .calc-panel {
    margin-top: 8px;
    padding: 8px 10px;
    border: 1px dashed var(--border-control);
    border-radius: var(--r-ctl);
    background: var(--surface-2);
    font-size: 12px;
    line-height: 16px;
    font-weight: normal;
    text-align: left;
    white-space: normal;
    display: grid;
    gap: 6px;
  }
  .title {
    display: flex;
    align-items: center;
    gap: 4px;
  }
</style>
