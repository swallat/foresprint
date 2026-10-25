<script lang="ts">
  // The two-way switch "will finish / carry-over" of one ticket, shared by the what-if of the
  // pre-planning and the Review.
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';

  interface Props {
    ticket: string;
    carry: boolean;
    disabled?: boolean;
    // In the Review the outcome is known: "is done" instead of "will finish".
    review?: boolean;
    onchange: (carry: boolean) => void;
  }
  let { ticket, carry, disabled = false, review = false, onchange }: Props = $props();
</script>

<div class="seg" role="group" aria-label={review ? t('Result for {key}', { key: ticket }) : t('Expectation for {key}', { key: ticket })}>
  <button type="button" class="seg-b" class:on={!carry} aria-pressed={!carry} {disabled} onclick={() => onchange(false)}><Icon name="check" size={14} />{review ? t('is done') : t('will finish')}</button>
  <button type="button" class="seg-b warn" class:on={carry} aria-pressed={carry} {disabled} onclick={() => onchange(true)}><Icon name="redo" size={14} />{t('carry-over')}</button>
</div>

<style>
  .seg {
    display: inline-flex;
    border: 1px solid var(--border-control);
    border-radius: var(--r-ctl);
    overflow: hidden;
  }
  .seg-b {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 0;
    background: var(--surface);
    color: var(--text-muted);
    padding: 3px 10px;
    font-size: 13px;
    cursor: pointer;
  }
  .seg-b + .seg-b {
    border-left: 1px solid var(--border-control);
  }
  .seg-b.on {
    background: var(--ok-weak);
    color: var(--ok);
    font-weight: 600;
  }
  .seg-b.on.warn {
    background: var(--warn-weak);
    color: var(--warn);
  }
</style>
