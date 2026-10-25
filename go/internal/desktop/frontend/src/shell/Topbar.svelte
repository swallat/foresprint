<script lang="ts">
  import { app, refresh, save, selectSprint, selectTeam, setTheme, toast } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import { go, link } from '../lib/router.svelte';
  import BrowserMenu from './BrowserMenu.svelte';
  import Logo from './Logo.svelte';
  import NewMenu from './NewMenu.svelte';
  import StatusChip from './StatusChip.svelte';
  import TrackerChip from './TrackerChip.svelte';

  const NEW_TEAM = '\u0000new-team'; // not a team key

  const readyTags = $derived(app.pendingTags.filter((x) => x.ready).map((x) => x.name));

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
  <a class="brand" href={link('/today')} title={t('Go to Today')}> <Logo /><span>Foresprint</span></a>

  {#if app.teams.length > 0}
    <NewMenu />
    <label class="sel hide-narrow" title={t('Switch team')}>
      <Icon name="groups" />
      <select aria-label={t('Team')} value={app.team} onchange={(e) => {
          if (e.currentTarget.value === NEW_TEAM) {
            e.currentTarget.value = app.team;
            go('/setup', {}, { add: 'team' });
          } else void selectTeam(e.currentTarget.value);
        }}>
        {#each app.teams as team (team.key)}
          <option value={team.key} disabled={!!team.problem}>{team.name}</option>
        {/each}
        <option value={NEW_TEAM}>+ {t('Create a new team')}</option>
      </select>
      <Icon name="keyboard_arrow_down" />
    </label>
  {/if}
  {#if app.sprints.length > 0}
    <label class="sel sprint" title={t('Choose sprint')}>
      <Icon name="date_range" />
      <select class="data" aria-label={t('Sprint')} title={`${t('Choose sprint')}: ${app.sprint}`} value={app.sprint} onchange={(e) => selectSprint(e.currentTarget.value)}>
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
  {#if app.update}
    <a class="chip-status ok" href={link('/settings/updates')} title={t('Version {latest} is available (installed: {version}).', { latest: app.update.latest, version: app.update.version })}>
      <Icon name="cloud_download" /><span class="hide-narrow hide-mid">{t('Update {latest}', { latest: app.update.latest })}</span>
    </a>
  {/if}
  <TrackerChip />
  <StatusChip />
  <button class="btn hide-narrow" type="button" data-tour="topbar-refresh" title={t('Fetch changes of others')} aria-label={t('Refresh')} disabled={!!app.busy} onclick={refresh}>
    <Icon name="download" /><span class="hide-mid">{t('Refresh')}</span>
  </button>
  {#if readyTags.length > 0}
    <a class="chip fc" href={link('/data/history')} title={t('The next Save sets these tags.')} aria-label={t('The next Save sets these tags: {names}', { names: readyTags.join(', ') })}>
      <Icon name="sell" /><span class="data">{readyTags.join(', ')}</span>
    </a>
  {/if}
  <button class="btn primary" type="button" data-tour="topbar-save" title={t('Save and share with the team (Ctrl+S)')} aria-label={t('Save')} disabled={!!app.busy} onclick={save}>
    <Icon name="save" /><span class="hide-narrow hide-compact">{t('Save')}</span>
  </button>
  <BrowserMenu />
  <a class="btn icon ghost" href={link('/help/guided')} aria-label={t('Help')} title={t('Help: guided flows and calculations')}>
    <Icon name="help" />
  </a>
  <button class="btn icon ghost" type="button" aria-label={t('Theme')} title={t('Theme: {name}', { name: app.prefs?.themes.find((x) => x.code === app.prefs?.theme)?.label ?? '' })} onclick={cycleTheme}>
    <Icon name="contrast" />
  </button>
</header>

<style>
  .sel {
    position: relative;
    /* the pickers give way last: the search field shrinks before them */
    flex: 0 1 auto;
    min-width: 0;
  }
  .sel select {
    appearance: none;
    border: 0;
    /* not transparent: the open list of the select takes this color (white on Windows otherwise) */
    background: var(--surface);
    padding: 0 20px 0 2px;
    height: 24px;
    cursor: pointer;
    min-width: 4ch;
    width: 100%;
    max-width: min(40ch, 30vw);
    text-overflow: ellipsis;
    color: inherit;
  }
  /* the sprint name is short and must stay readable: the team picker shrinks first */
  .sprint {
    flex: 0 0 auto;
  }
  .sprint select {
    width: auto;
    min-width: 9ch;
  }
  .sel select option {
    background-color: var(--surface);
    color: var(--text);
  }
  .sel :global(.ic:last-child) {
    position: absolute;
    right: 4px;
    pointer-events: none;
  }
</style>
