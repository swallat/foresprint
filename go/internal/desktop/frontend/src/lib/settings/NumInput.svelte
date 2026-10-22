<script lang="ts">
  import { t } from '../i18n.svelte';
  import { parseNumber } from './diff';

  interface Props {
    id: string;
    label: string;
    value: number;
    /** Smallest and largest value; a value outside is shown as wrong and not taken. */
    min?: number;
    max?: number;
    unit?: string;
    width?: string;
  }
  let { id, label, value = $bindable(), min = 0, max = Number.MAX_SAFE_INTEGER, unit, width }: Props = $props();

  let text = $state('');
  let wrong = $state(false);
  let editing = false;

  $effect(() => {
    if (!editing) text = String(value).replace('.', ',');
  });

  function take(): void {
    const n = parseNumber(text);
    wrong = n === undefined || n < min || n > max;
    if (!wrong && n !== undefined) value = n;
  }
</script>

<div class="field" style:width>
  <label for={id}>{label}{#if unit} <span class="muted">({unit})</span>{/if}</label>
  <input
    {id}
    class="input data num"
    inputmode="decimal"
    bind:value={text}
    aria-invalid={wrong}
    oninput={() => {
      editing = true;
      take();
    }}
    onblur={() => {
      editing = false;
      if (wrong) wrong = false;
      text = String(value).replace('.', ',');
    }}
  />
  {#if wrong}<span class="small err">{t('Allowed: {min} to {max}', { min, max })}</span>{/if}
</div>

<style>
  input[aria-invalid='true'] {
    border-color: var(--bad);
  }
  .err {
    color: var(--bad);
  }
</style>
