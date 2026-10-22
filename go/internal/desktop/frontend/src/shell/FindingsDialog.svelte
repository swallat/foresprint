<script lang="ts">
  import { app, saveAnyway } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';

  // Save found errors in the changed data (flows.md D2): fix them or save anyway.
  let first = $state<HTMLButtonElement>();

  $effect(() => {
    if (app.findings) first?.focus();
  });

  function close(): void {
    app.findings = undefined;
  }

  async function anyway(): Promise<void> {
    close();
    await saveAnyway();
  }

  function keys(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  }
</script>

{#if app.findings}
  <div class="scrim" role="presentation" onclick={close}></div>
  <div class="dialog card" role="dialog" aria-modal="true" aria-labelledby="fd-title" tabindex="-1" onkeydown={keys}>
    <h2 id="fd-title"><Icon name="warning" /> {t('The changed data has errors')}</h2>
    <p class="muted">{t('Others who open the data may run into them. Fix them first, or save anyway.')}</p>
    <ul class="list">
      {#each app.findings as f (f)}
        <li>{f}</li>
      {/each}
    </ul>
    <div class="row end">
      <button class="btn primary" type="button" bind:this={first} onclick={close}>{t('Back and fix')}</button>
      <button class="btn" type="button" onclick={anyway}>{t('Save anyway')}</button>
    </div>
  </div>
{/if}

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--text) 40%, transparent);
    z-index: 70;
  }
  .dialog {
    position: fixed;
    z-index: 71;
    left: 50%;
    top: 20vh;
    transform: translateX(-50%);
    width: min(560px, calc(100vw - 32px));
    max-height: 60vh;
    overflow: auto;
    box-shadow: var(--shadow);
  }
  h2 {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .list {
    margin: 8px 0 16px;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .end {
    justify-content: flex-end;
  }
</style>
