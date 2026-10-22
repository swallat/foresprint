<script lang="ts">
  // The side panel for one ticket, open on every page (app.ticket holds the key). Owned by the
  // package P1 Backlog; it replaces this placeholder with the real panel (flows.md section 5,
  // "ticket panel").
  import { app } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
</script>

<aside class="panel" aria-label={t('Ticket')}>
  <div class="panel-head">
    <strong class="data">{app.ticket}</strong>
    <span class="grow"></span>
    <button class="btn icon ghost" type="button" aria-label={t('Close')} title={t('Close')} onclick={() => (app.ticket = '')}>
      <Icon name="close" />
    </button>
  </div>
  <div class="panel-body">
    <p class="muted">{t('The ticket panel is not built yet.')}</p>
  </div>
</aside>

<style>
  .grow {
    flex: 1;
  }
</style>
