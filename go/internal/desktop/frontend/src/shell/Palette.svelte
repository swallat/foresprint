<script lang="ts">
  import { tick } from 'svelte';
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { go, link } from '../lib/router.svelte';
  import { pages } from '../lib/routes';

  // The command palette (Ctrl+K). It lists the pages of the route table; tickets and actions
  // are added to `entries` by the packages that own them.
  let query = $state('');
  let index = $state(0);
  let input: HTMLInputElement | undefined = $state();

  interface Entry {
    label: string;
    hint?: string;
    run: () => void;
  }

  const entries = $derived<Entry[]>(
    pages
      .filter((p) => !p.path.includes(':') && !p.bare)
      .map((p) => ({ label: t(p.title), hint: p.path, run: () => go(p.path) })),
  );
  const shown = $derived(
    entries.filter((e) => e.label.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 12),
  );

  $effect(() => {
    if (app.paletteOpen) {
      query = '';
      index = 0;
      void tick().then(() => input?.focus());
    }
  });
  $effect(() => {
    void query;
    index = 0;
  });

  function choose(e: Entry | undefined): void {
    if (!e) return;
    app.paletteOpen = false;
    e.run();
  }

  function key(ev: KeyboardEvent): void {
    if (ev.key === 'Escape') app.paletteOpen = false;
    else if (ev.key === 'ArrowDown') {
      index = Math.min(index + 1, shown.length - 1);
      ev.preventDefault();
    } else if (ev.key === 'ArrowUp') {
      index = Math.max(index - 1, 0);
      ev.preventDefault();
    } else if (ev.key === 'Enter') choose(shown[index]);
  }
</script>

{#if app.paletteOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={() => (app.paletteOpen = false)}>
    <div class="box card" role="dialog" tabindex="-1" aria-modal="true" aria-label={t('Search and jump')} onclick={(e) => e.stopPropagation()}>
      <div class="row">
        <Icon name="search" />
        <input
          bind:this={input}
          bind:value={query}
          class="input grow"
          placeholder={t('Go to page')}
          aria-label={t('Go to page')}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          onkeydown={key}
        />
      </div>
      <ul id="palette-list" role="listbox">
        {#each shown as e, i (e.hint ?? e.label)}
          <li role="option" aria-selected={i === index}>
            <a href={link(e.hint ?? '/')} class:on={i === index} onclick={(ev) => { ev.preventDefault(); choose(e); }}>
              <span>{e.label}</span><span class="muted small data">{e.hint}</span>
            </a>
          </li>
        {:else}
          <li class="muted pad">{t('Nothing found.')}</li>
        {/each}
      </ul>
    </div>
  </div>
{/if}

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--bg) 60%, transparent);
    z-index: 70;
    display: flex;
    justify-content: center;
    padding-top: 12vh;
  }
  .box {
    width: min(560px, calc(100vw - 32px));
    align-self: flex-start;
    box-shadow: var(--shadow);
    padding: 8px;
  }
  .grow {
    flex: 1;
  }
  ul {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
    max-height: 50vh;
    overflow: auto;
  }
  a {
    display: flex;
    justify-content: space-between;
    padding: 6px 10px;
    border-radius: var(--r-ctl);
    color: var(--text);
    text-decoration: none;
  }
  a.on,
  a:hover {
    background: var(--primary-weak);
  }
  .pad {
    padding: 8px 10px;
  }
</style>
