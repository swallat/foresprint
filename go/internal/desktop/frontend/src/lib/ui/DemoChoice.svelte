<script lang="ts">
  import { demoChoice } from '../app.svelte';
  import { t } from '../i18n.svelte';

  // The two choices for the demo: which team (every feature, or the simple one) and where its
  // work comes from. They apply the next time the demo is opened.
  let { id = 'demo' }: { id?: string } = $props();
</script>

<div class="choice">
  <span class="field">
    <label for="{id}-team">{t('Demo team')}</label>
    <select id="{id}-team" class="input" bind:value={demoChoice.team}>
      <option value="atlas">{t('Team Atlas (all features)')}</option>
      <option value="simple">{t('Simple team (products only)')}</option>
    </select>
  </span>
  <span class="field">
    <label for="{id}-source">{t('Ticket mode')}</label>
    <select id="{id}-source" class="input" bind:value={demoChoice.source}>
      <option value="packages">{t('Work packages in Foresprint')}</option>
      <option value="tracker">{t('Tracker (Jira)')}</option>
      <option value="none">{t('No tickets')}</option>
    </select>
  </span>
</div>

<style>
  .choice {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 16px;
    margin: 12px 0 0;
  }
  .field {
    display: grid;
    gap: 4px;
  }
</style>
