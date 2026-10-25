<script lang="ts">
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { ProjectsView, ProjectView } from '../../lib/types.projects';
  import { num } from './format';
  import SidePanel from './SidePanel.svelte';

  interface Props {
    view: ProjectsView;
    project: ProjectView;
    onclose: () => void;
    /** Called after the project was closed or deleted. */
    ondone: () => void;
  }
  let { view, project, onclose, ondone }: Props = $props();

  // A project with history is closed, not deleted: reports, minutes and past sprints keep it.
  let how = $state<'finished' | 'cancelled'>('finished');
  /* svelte-ignore state_referenced_locally */
  let at = $state(view.today);
  let moveTo = $state('');
  let error = $state('');
  let busy = $state(false);

  const others = $derived(view.projects.filter((p) => p.id !== project.id));
  const rest = $derived((project.booked ?? 0) - (project.done ?? 0));
  const unit = $derived(view.source === 'packages' ? t('work packages') : t('tickets'));

  async function go(): Promise<void> {
    busy = true;
    error = '';
    const name = project.name;
    try {
      if (project.history) {
        await api.CloseProject(app.team, { id: project.id, how, at, moveTo });
        toast(how === 'finished' ? t('{name} finished.', { name }) : t('{name} cancelled.', { name }), 'ok', {
          label: t('Undo'),
          run: () => void api.UndoProjects(app.team).then(ondone),
        });
      } else {
        await api.DeleteProject(app.team, project.id);
        toast(t('{name} deleted.', { name }), 'ok', { label: t('Undo'), run: () => void api.UndoProjects(app.team).then(ondone) });
      }
      ondone();
    } catch (e) {
      error = String(e).replace(/^Error: /, '');
    } finally {
      busy = false;
    }
  }
</script>

<SidePanel title={project.history ? t('Finish project') : t('Delete project')} {onclose}>
  {#if project.history}
    <p style="margin:0">
      {t('{name} has history. It is finished, not deleted: reports, minutes and past sprints keep it. Finished projects are listed on the projects page and can be reopened.', { name: project.name })}
    </p>
    <fieldset>
      <legend class="small muted">{t('How does the project end?')}</legend>
      <div class="row">
        <label class="row"><input type="radio" name="how" value="finished" bind:group={how} />{t('finished')}</label>
        <label class="row"><input type="radio" name="how" value="cancelled" bind:group={how} />{t('cancelled')}</label>
      </div>
    </fieldset>
    <div class="field">
      <label for="cl-at">{t('End date')}</label>
      <input class="input data" id="cl-at" type="date" bind:value={at} style="max-width:180px" />
    </div>
    {#if view.source === 'none'}
      <p class="small muted" style="margin:0">{t('The open scope drops out. Amounts in future sprints go to daily business.')}</p>
    {:else if project.open > 0}
      <div class="field">
        <label for="cl-to">{t('Open {unit} ({n}) go to', { unit, n: project.open })}</label>
        <select class="input" id="cl-to" bind:value={moveTo} style="max-width:280px">
          <option value="">{t('Daily business')}</option>
          {#each others as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
        </select>
      </div>
    {/if}
    {#if project.booked !== null}
      <p class="small muted" style="margin:0">
        {t('The remaining contingent of {n} PD is reported, not planned further.', { n: num(Math.max(0, rest), 1) })}
      </p>
    {/if}
  {:else}
    <p style="margin:0">{t('{name} has no history yet. It will be deleted.', { name: project.name })}</p>
  {/if}
  {#if error}<div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>{/if}
  <div class="row">
    <button class="btn danger" type="button" disabled={busy} onclick={go}>
      <Icon name={project.history ? 'archive' : 'delete'} />{project.history ? t('Finish project') : t('Delete')}
    </button>
    <button class="btn ghost" type="button" onclick={onclose}>{t('Cancel')}</button>
  </div>
</SidePanel>

<style>
  fieldset {
    border: 0;
    padding: 0;
    margin: 0;
  }
</style>
