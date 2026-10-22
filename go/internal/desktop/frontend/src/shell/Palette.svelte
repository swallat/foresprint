<script lang="ts">
  import { tick } from 'svelte';
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { commandsFor, loadTicketIndex, type Command } from '../lib/commands';

  // The command palette (Ctrl+K). The entries come from lib/commands.ts: pages, actions, and
  // whatever a package registers there (tickets, guided flows).
  let query = $state('');
  let index = $state(0);
  let input: HTMLInputElement | undefined = $state();

  let ticketsLoaded = $state(0); // the ticket list arrives after the palette opened
  const shown = $derived(app.paletteOpen ? (void ticketsLoaded, commandsFor(query)) : []);
  const labels: Record<Command['group'], () => string> = {
    page: () => t('Page'),
    action: () => t('Action'),
    help: () => t('Help'),
    ticket: () => t('Ticket'),
    sprint: () => t('Sprint'),
  };

  $effect(() => {
    if (app.paletteOpen) {
      void loadTicketIndex().then(() => ticketsLoaded++);
      query = '';
      index = 0;
      void tick().then(() => input?.focus());
    }
  });
  $effect(() => {
    void query;
    index = 0;
  });
  $effect(() => {
    // Keep the active entry in view while stepping with the arrow keys.
    if (app.paletteOpen) document.getElementById(`pal-${index}`)?.scrollIntoView?.({ block: 'nearest' });
  });

  function choose(e: Command | undefined): void {
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
          aria-activedescendant={shown.length > 0 ? `pal-${index}` : undefined}
          onkeydown={key}
        />
      </div>
      <ul id="palette-list" role="listbox">
        {#each shown as e, i (e.id)}
          <li id={`pal-${i}`} role="option" aria-selected={i === index}>
            <button type="button" tabindex="-1" class:on={i === index} onclick={() => choose(e)} onmousemove={() => (index = i)}>
              <span class="grow">{e.label}</span>
              {#if e.hint}<span class="muted small data">{e.hint}</span>{/if}
              <span class="chip">{labels[e.group]()}</span>
            </button>
          </li>
        {:else}
          <li class="muted pad" role="option" aria-selected="false" aria-disabled="true">{t('Nothing found.')}</li>
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
  button {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    border: 0;
    background: transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
    padding: 6px 10px;
    border-radius: var(--r-ctl);
    color: var(--text);
    text-decoration: none;
  }
  button.on,
  button:hover {
    background: var(--primary-weak);
  }
  .pad {
    padding: 8px 10px;
  }
</style>
