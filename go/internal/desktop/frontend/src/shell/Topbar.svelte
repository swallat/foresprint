<script lang="ts">
  import { app, refresh, save, selectSprint, selectTeam, setTheme, toast } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import Logo from './Logo.svelte';
  import StatusChip from './StatusChip.svelte';
  import TrackerChip from './TrackerChip.svelte';

  const next: Record<string, string> = { system: 'light', light: 'dark', dark: 'system' };

  async function cycleTheme(): Promise<void> {
    try {
      await setTheme(next[app.prefs?.theme ?? 'system'] ?? 'system');
    } catch (e) {
      toast(String(e), 'bad');
    }
  }
</script>

<header class="topbar">
  <button class="btn icon ghost rail-toggle" type="button" aria-label={t('Navigation')} onclick={() => (app.railOpen = !app.railOpen)}>
    <Icon name="menu" />
  </button>
  <div class="brand"><Logo /><span>Foresprint</span></div>

  {#if app.teams.length > 0}
    <label class="sel hide-narrow" title={t('Switch team')}>
      <Icon name="groups" />
      <select aria-label={t('Team')} value={app.team} onchange={(e) => selectTeam(e.currentTarget.value)}>
        {#each app.teams as team (team.key)}
          <option value={team.key} disabled={!!team.problem}>{team.name}</option>
        {/each}
      </select>
      <Icon name="keyboard_arrow_down" />
    </label>
  {/if}
  {#if app.sprints.length > 0}
    <label class="sel" title={t('Choose sprint')}>
      <Icon name="date_range" />
      <select class="data" aria-label={t('Sprint')} value={app.sprint} onchange={(e) => selectSprint(e.currentTarget.value)}>
        {#each app.sprints as s (s.id)}
          <option value={s.id}>{s.id}</option>
        {/each}
      </select>
      <Icon name="keyboard_arrow_down" />
    </label>
  {/if}

  <div class="spacer"></div>

  <button class="search" type="button" title={t('Search and jump (Ctrl+K)')} onclick={() => (app.paletteOpen = true)}>
    <Icon name="search" /><span class="txt hide-mid">{t('Search')}</span><span class="small data hide-narrow hide-mid">Ctrl+K</span>
  </button>
  <TrackerChip />
  <StatusChip />
  <button class="btn hide-narrow" type="button" title={t('Fetch changes of others')} aria-label={t('Refresh')} disabled={!!app.busy} onclick={refresh}>
    <Icon name="download" /><span class="hide-mid">{t('Refresh')}</span>
  </button>
  <button class="btn primary" type="button" title={t('Save and share with the team (Ctrl+S)')} aria-label={t('Save')} disabled={!!app.busy} onclick={save}>
    <Icon name="save" /><span class="hide-narrow">{t('Save')}</span>
  </button>
  <button class="btn icon ghost" type="button" aria-label={t('Theme')} title={t('Theme: {name}', { name: app.prefs?.themes.find((x) => x.code === app.prefs?.theme)?.label ?? '' })} onclick={cycleTheme}>
    <Icon name="contrast" />
  </button>
</header>

<style>
  .sel {
    position: relative;
  }
  .sel select {
    appearance: none;
    border: 0;
    background: transparent;
    padding: 0 20px 0 2px;
    height: 24px;
    cursor: pointer;
    max-width: 18ch;
    color: inherit;
  }
  .sel :global(.ic:last-child) {
    position: absolute;
    right: 4px;
    pointer-events: none;
  }
</style>
