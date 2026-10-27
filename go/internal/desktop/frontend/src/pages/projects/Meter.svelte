<script lang="ts">
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { num } from './format';

  interface Props {
    booked: number | null;
    done: number | null;
    planned: number | null;
  }
  let { booked, done, planned }: Props = $props();

  const d = $derived(done ?? 0);
  const p = $derived(planned ?? 0);
  const max = $derived(Math.max(booked ?? 0, d + p) * 1.02 || 1);
  const pct = (v: number) => (v / max) * 100;
  const over = $derived(booked !== null ? d + p - booked : 0);
</script>

{#if booked === null}
  <span class="small muted">{t('No contingent booked')}</span>
{:else}
  <div class="wrap">
    <div
      class="meter"
      role="img"
      aria-label={t('Done {done} PD, planned {planned} PD of {booked} PD', { done: num(d), planned: num(p), booked: num(booked) })}
    >
      <i class="u" style:width="{pct(d)}%"></i>
      <i class="p" class:over={over > 0} style:left="{pct(d)}%" style:width="{pct(p)}%"></i>
      <b class="t" style:left="{pct(booked)}%" title={t('Booked {booked} PD', { booked: num(booked) })}></b>
    </div>
    {#if over > 0}
      <span class="small over-txt"><Icon name="warning" size={14} />{t('{n} PD over the contingent', { n: num(over) })}</span>
    {:else}
      <span class="small muted">{t('{n} PD free', { n: num(-over) })}</span>
    {/if}
  </div>
{/if}

<style>
  .wrap {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 130px;
    white-space: normal;
  }
  .meter {
    position: relative;
    height: 10px;
    border-radius: 5px;
    background: var(--surface-3);
  }
  .u {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    background: var(--primary);
    border-radius: 5px 0 0 5px;
  }
  .p {
    position: absolute;
    top: 0;
    bottom: 0;
    border: 1.5px dashed var(--forecast);
    background: var(--forecast-weak);
    box-sizing: border-box;
  }
  .p.over {
    border-color: var(--bad);
    background: var(--bad-weak);
  }
  .t {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 2px;
    background: var(--text);
  }
  .over-txt {
    color: var(--bad);
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
</style>
