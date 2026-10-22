<script lang="ts">
  import { onMount } from 'svelte';
  import { app, refresh, save, start } from './lib/app.svelte';
  import { t } from './lib/i18n.svelte';
  import { current, go, match } from './lib/router.svelte';
  import { pages } from './lib/routes';
  import Banner from './lib/ui/Banner.svelte';
  import TicketPanel from './pages/backlog/TicketPanel.svelte';
  import Palette from './shell/Palette.svelte';
  import Rail from './shell/Rail.svelte';
  import Toasts from './shell/Toasts.svelte';
  import Topbar from './shell/Topbar.svelte';

  const found = $derived.by(() => {
    for (const def of pages) {
      const params = match(def.path, current.path);
      if (params) return { def, params };
    }
    return undefined;
  });

  $effect(() => {
    document.title = `${found ? t(found.def.title) : 'Foresprint'} – Foresprint`;
  });

  onMount(async () => {
    await start();
    if (current.path === '/') go(app.teams.length > 0 ? '/today' : '/setup');
  });

  function keys(e: KeyboardEvent): void {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      app.paletteOpen = !app.paletteOpen;
    } else if (mod && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void save();
    } else if (mod && e.shiftKey && e.key.toLowerCase() === 'r') {
      e.preventDefault();
      void refresh();
    } else if (e.key === 'Escape') {
      app.railOpen = false;
    }
  }
</script>

<svelte:window onkeydown={keys} />

{#if app.ready}
  {#if found?.def.bare}
    <main class="bare">
      {#key found.def.path}
        {#await found.def.load() then mod}
          {@const Page = mod.default}
          <Page params={found.params} />
        {/await}
      {/key}
    </main>
  {:else}
    <div class="app">
      <Topbar />
      <Rail />
      <main class="main" id="main">
        <div class="page">
          {#if app.problem}
            <Banner tone="bad">{t('The data folder could not be read: {problem}', { problem: app.problem })}</Banner>
          {/if}
          <svelte:boundary>
            {#if found}
              {#key found.def.path + JSON.stringify(found.params)}
                {#await found.def.load()}
                  <p class="muted">{t('Loading…')}</p>
                {:then mod}
                  {@const Page = mod.default}
                  <Page params={found.params} />
                {:catch error}
                  <Banner tone="bad">{String(error)}</Banner>
                {/await}
              {/key}
            {:else}
              <h1>{t('Page not found')}</h1>
              <p><a href="#/today">{t('Go to Today')}</a></p>
            {/if}
            {#snippet failed(error, reset)}
              <Banner tone="bad">
                {t('This page failed: {message}', { message: String((error as Error)?.message ?? error) })}
                {#snippet action()}
                  <button class="btn" type="button" onclick={reset}>{t('Try again')}</button>
                {/snippet}
              </Banner>
            {/snippet}
          </svelte:boundary>
        </div>
      </main>
      {#if app.ticket}<TicketPanel />{/if}
    </div>
  {/if}
  <Palette />
  <Toasts />
{:else}
  <p class="boot muted">Foresprint …</p>
{/if}

<style>
  .bare {
    min-height: 100%;
    overflow: auto;
  }
  .boot {
    padding: 24px;
  }
</style>
