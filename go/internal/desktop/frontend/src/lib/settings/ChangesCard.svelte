<script lang="ts">
  import { t } from '../i18n.svelte';
  import type { Row } from './diff';

  interface Props {
    rows: Row[];
    busy?: boolean;
    onapply: () => void;
    onreset: () => void;
  }
  let { rows, busy = false, onapply, onreset }: Props = $props();
</script>

<div class="card" data-keep="1">
  <h2>{t('Changes before saving')}</h2>
  {#if rows.length}
    <div class="tw">
      <table class="t">
        <thead>
          <tr><th>{t('Setting')}</th><th>{t('Before')}</th><th>{t('After')}</th></tr>
        </thead>
        <tbody>
          {#each rows as row (row.label)}
            <tr>
              <td class="wrap">{row.label}</td>
              <td class="muted">{row.before}</td>
              <td><strong>{row.after}</strong></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="row actions">
      <button class="btn primary" type="button" disabled={busy} onclick={onapply}>{t('Apply changes')}</button>
      <button class="btn" type="button" disabled={busy} onclick={onreset}>{t('Discard')}</button>
    </div>
    <p class="small muted">{t('Applied changes then wait with the unsaved ones; Save in the top bar shares them with the team.')}</p>
  {:else}
    <p class="muted">{t('No changes.')}</p>
  {/if}
</div>

<style>
  .wrap {
    white-space: normal;
  }
  .actions {
    margin-top: 12px;
  }
  p {
    margin: 8px 0 0;
  }
</style>
