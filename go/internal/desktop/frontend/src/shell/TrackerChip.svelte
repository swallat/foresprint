<script lang="ts">
  import { app, syncTracker } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';

  const tr = $derived(app.status.tracker);

  function ago(iso: string): string {
    if (!iso) return t('never');
    const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (minutes < 1) return t('just now');
    if (minutes < 60) return t('{n} min ago', { n: minutes });
    const hours = Math.round(minutes / 60);
    return hours < 24 ? t('{n} h ago', { n: hours }) : t('{n} d ago', { n: Math.round(hours / 24) });
  }
</script>

{#if tr.enabled}
  <button
    type="button"
    class="chip-status {tr.failed ? 'bad' : ''}"
    title={tr.failed || t('Fetch tickets from {name} now', { name: tr.name })}
    disabled={app.busy === 'sync' || tr.syncing}
    onclick={syncTracker}
  >
    <Icon name="sync" />
    <span class="hide-narrow hide-mid">{tr.failed ? t('{name} failed', { name: tr.name }) : `${tr.name} ${ago(tr.last)}`}</span>
  </button>
{/if}
