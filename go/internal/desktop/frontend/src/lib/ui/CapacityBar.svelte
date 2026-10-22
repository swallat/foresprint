<script lang="ts">
  // Used amount against the forecast range: solid bar = used, dashed mint = range of the
  // Forecast PLAN. The colour is never the only signal: the label says it in words, and the
  // bar turns red only together with the text of the page ("over the range").
  import { t } from '../i18n.svelte';

  interface Props {
    used: number;
    plan: number | null;
    low: number | null;
    high: number | null;
    /** Unit word for the label, e.g. "points". */
    unit: string;
  }
  let { used, plan, low, high, unit }: Props = $props();

  const max = $derived(Math.max(high ?? plan ?? 0, used, 1) * 1.15);
  const pct = (v: number) => Math.max(0, Math.min(100, (v / max) * 100));
  const over = $derived(high != null && used > high);
  const label = $derived(
    low != null && high != null
      ? t('{used} of {plan} {unit}, range {low} to {high}', { used, plan: plan ?? 0, unit, low, high })
      : t('{used} of {plan} {unit}', { used, plan: plan ?? 0, unit }),
  );
</script>

<div class="cap" role="img" aria-label={label}>
  {#if low != null && high != null}
    <div class="fc" style:left="{pct(low)}%" style:width="{pct(high) - pct(low)}%"></div>
  {/if}
  <div class="used" class:over style:width="{pct(used)}%"></div>
</div>
