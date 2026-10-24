<script lang="ts">
  import { onMount } from 'svelte';
  import { app, loadTeams, toast } from '../../lib/app.svelte';
  import { api } from '../../lib/api';
  import { t } from '../../lib/i18n.svelte';
  import type { TeamSummary } from '../../lib/types';
  import Icon from '../../lib/Icon.svelte';

  let archived = $state<TeamSummary[]>([]);
  let typed = $state('');
  let busy = $state(false);

  const current = $derived(app.teams.find((x) => x.key === app.team));
  const matches = $derived(!!current && typed.trim().toLowerCase() === current.name.toLowerCase());

  async function load(): Promise<void> {
    try {
      archived = await api.ArchivedTeams();
    } catch (e) {
      toast(String(e), 'bad');
    }
  }
  onMount(load);

  async function archive(): Promise<void> {
    if (!current || busy) return;
    busy = true;
    try {
      await api.ArchiveTeam(current.key, typed);
      toast(t('{name} is archived. It stays in the data folder and can be restored here.', { name: current.name }));
      typed = '';
      await loadTeams();
      await load();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }

  async function restore(key: string): Promise<void> {
    busy = true;
    try {
      await api.RestoreTeam(key);
      await loadTeams();
      await load();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }
</script>

<div class="card wide">
  <h2>{t('Archive team')}</h2>
  <p class="small muted lead">
    {t('The team disappears from the list, nothing is deleted: its whole folder (people, sprints, projects with contingents, minutes) moves to the folder “_archiv” in the data folder. Git shows it as a move, so the history stays. Other people see the team gone after the next update.')}
  </p>
  {#if current}
    <form class="row" onsubmit={(e) => { e.preventDefault(); void archive(); }}>
      <input class="input" aria-label={t('Type the name of the team to archive it.')} placeholder={current.name} bind:value={typed} />
      <button class="btn danger" type="submit" disabled={!matches || busy}><Icon name="archive" />{t('Archive team')}</button>
    </form>
    <p class="small muted">{t('Type the name of the team to archive it.')}</p>
  {/if}
  {#if archived.length}
    <h3>{t('Archived teams')}</h3>
    <ul class="names">
      {#each archived as a (a.key)}
        <li class="row">
          <span>{a.name}</span>
          <button class="btn" type="button" disabled={busy} onclick={() => restore(a.key)}><Icon name="unarchive" />{t('Restore')}</button>
        </li>
      {/each}
    </ul>
  {/if}
</div>
