<script lang="ts">
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { ProjectsView, ProjectView } from '../../lib/types.projects';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import Amount from './Amount.svelte';
  import CloseProject from './CloseProject.svelte';
  import ConflictView from './ConflictView.svelte';
  import { date, num, productColor } from './format';
  import LightChip from './LightChip.svelte';
  import Meter from './Meter.svelte';
  import ProjectCalc from './ProjectCalc.svelte';
  import ProjectForm from './ProjectForm.svelte';
  import { loadRange, saveRange } from './store';
  import Timeline from './Timeline.svelte';
  import { addDays, windowOf, type Range } from './timeline';

  let { params }: PageProps = $props();
  void params;

  let view = $state<ProjectsView | undefined>();
  let problem = $state('');
  let panel = $state<{ kind: 'new' } | { kind: 'close'; id: string } | undefined>();
  const saved = loadRange();
  let range = $state<Range>(saved.range);
  let customTo = $state(saved.customTo);

  let loadSeq = 0; // answers of an earlier team must not replace the current one
  async function load(): Promise<void> {
    if (!app.team) return;
    const mine = ++loadSeq;
    try {
      const answer = await api.Projects(app.team);
      if (mine !== loadSeq) return;
      view = answer;
      problem = '';
    } catch (e) {
      if (mine === loadSeq) problem = String(e);
    }
  }

  $effect(() => {
    void app.team;
    void load();
  });

  function pick(r: Range): void {
    range = r;
    saveRange(range, customTo);
  }

  function pickDate(value: string): void {
    if (!value) return;
    customTo = value;
    range = 'custom';
    saveRange(range, customTo);
  }

  async function reopen(p: ProjectView): Promise<void> {
    try {
      await api.ReopenProject(app.team, p.id);
      toast(t('{name} is open again. Please check end date and contingent.', { name: p.name }), 'ok', {
        label: t('Undo'),
        run: () => void api.UndoProjects(app.team).then(load),
      });
      await load();
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  const ranges: [Range, string][] = [
    ['2', '2 months'],
    ['3', '3 months'],
    ['6', '6 months'],
    ['all', 'Until project end'],
  ];
  const rangeLabel = (r: Range) => (r === '2' ? t('2 months') : r === '3' ? t('3 months') : r === '6' ? t('6 months') : t('Until project end'));
  const estimated = $derived(view?.unit === 'SP');
  const attention = $derived(view ? view.projects.filter((p) => p.light === 'warn' || p.light === 'bad').length : 0);
  const productName = (id: string) => view?.products.find((p) => p.id === id)?.name ?? id;
  const productIndex = (id: string) => view?.products.findIndex((p) => p.id === id) ?? 0;
  const closing = $derived.by(() => {
    const open = panel;
    return open?.kind === 'close' && view ? view.projects.find((p) => p.id === open.id) : undefined;
  });
</script>

<PageHead
  title={t('Projects')}
  lead={t('All projects on one timeline with milestones, lights and contingent. You keep projects and milestones here yourself, also without a tracker and offline.')}
>
  {#snippet actions()}
    <button class="btn primary" type="button" id="pf-new" data-tour="projects-new" disabled={!view?.enabled} onclick={() => (panel = { kind: 'new' })}>
      <Icon name="add" />{t('New project')}
    </button>
  {/snippet}
</PageHead>

{#if problem}
  <Banner tone="bad">{problem}</Banner>
{:else if !view}
  <p class="muted">{t('Loading ...')}</p>
{:else if !view.enabled}
  <Banner>{t('This team keeps no projects. Switch them on under Settings > Team.')}</Banner>
{:else}
  {#if view.problem}
    <Banner tone="warn">{t('The lights could not be calculated: {reason}', { reason: view.problem })}</Banner>
  {/if}
  {#if attention > 0}
    <Banner tone="warn">
      <strong>{t('{n} of {total} projects', { n: attention, total: view.projects.length })}</strong>
      {t('are tight or at risk. Details in the table and in the conflict view below.')}
    </Banner>
  {/if}
  {#if estimated && view.rate === null}
    <Banner>{t('Amounts in person days need the team rate. It can be measured once three sprints are finished.')}</Banner>
  {/if}

  <section class="card" data-tour="projects-timeline">
    <div class="row head">
      <h2 style="margin:0;flex:1">{t('Project timeline')}</h2>
      <div class="row" role="group" aria-label={t('Visible period')}>
        <span class="small muted">{t('Period')}</span>
        {#each ranges as [r] (r)}
          <button type="button" class="chip filter" class:on={range === r} aria-pressed={range === r} onclick={() => pick(r)}>{rangeLabel(r)}</button>
        {/each}
        <label class="small muted" for="pf-to">{t('until')}</label>
        <input
          class="input data"
          type="date"
          id="pf-to"
          style="width:150px"
          value={windowOf(view.today, view.sprints, view.projects, range, customTo).to}
          min={addDays(view.today, 14)}
          onchange={(e) => pickDate(e.currentTarget.value)}
        />
      </div>
    </div>
    <p class="small muted" style="margin:8px 0">
      {t('Sprints in italics are not in the calendar yet and follow the usual cadence. The choice is yours alone and is kept for the next start.')}
    </p>
    {#if view.projects.length === 0}
      <p class="muted">{t('No open projects yet. Create one with "New project".')}</p>
    {:else}
      <div class="scroll"><Timeline {view} {range} {customTo} /></div>
      <div class="legend small muted">
        <span><i class="sw"></i>{t('Runtime to the end')}</span>
        <span><Icon name="check_circle" size={14} />{t('Milestone on track')}</span>
        <span><Icon name="error" size={14} />{t('tight')}</span>
        <span><Icon name="cancel" size={14} />{t('at risk')}</span>
        <span>{t('Grey diamond: milestone without tickets, no light')}</span>
        <span>{t('A click on a row opens the project')}</span>
      </div>
    {/if}
  </section>

  {#if view.projects.length > 0}
    <h2 style="margin:24px 0 8px">{t('Contingent')}</h2>
    <div class="tw" data-tour="projects-table">
      <table class="t">
        <thead>
          <tr>
            <th>{t('Project')}</th>
            {#if view.products.length > 1}<th>{t('Products')}</th>{/if}
            <th>{t('End')}</th>
            <th>{t('Traffic light')}</th>
            <th class="num">{t('booked (PD)')}</th>
            <th class="num">{t('done (PD)')}</th>
            <th class="num">{t('planned (PD)')}</th>
            <th>{t('Use')}</th>
          </tr>
        </thead>
        <tbody>
          {#each view.projects as p (p.id)}
            <tr>
              <td class="name">
                <span class="row nowrap">
                  <a href={link('/projects/:id', { id: p.id })}><strong>{p.name}</strong></a>
                  <button
                    class="btn icon ghost"
                    type="button"
                    aria-label={p.history ? t('Finish {name}', { name: p.name }) : t('Delete {name}', { name: p.name })}
                    title={p.history ? t('Finish (history is kept)') : t('Delete')}
                    disabled={panel !== undefined}
                    onclick={() => (panel = { kind: 'close', id: p.id })}
                  >
                    <Icon name={p.history ? 'archive' : 'delete'} />
                  </button>
                </span>
              </td>
              {#if view.products.length > 1}
                <td class="wrap">
                  {#each p.products as id (id)}<span class="chip"><span class="dot" style:background={productColor(productIndex(id))}></span>{productName(id)}</span>{' '}{/each}
                </td>
              {/if}
              <td class="data">{date(p.end)}</td>
              <td><LightChip light={p.light} /></td>
              <td class="num"><Amount value={p.booked} digits={1} /></td>
              <td class="num"><Amount value={p.done} est={estimated} /><ProjectCalc project={p} rate={view.rate} kind="done" /></td>
              <td class="num"><Amount value={p.planned} est={estimated} /><ProjectCalc project={p} rate={view.rate} kind="planned" /></td>
              <td><Meter booked={p.booked} done={p.done} planned={p.planned} /></td>
            </tr>
          {/each}
          {#if view.daily.length > 0}
            <tr class="sub">
              <td colspan={view.products.length > 1 ? 8 : 7}>
                {view.products.length > 1
                  ? t('Daily business per product, no light: the budget comes from the pre-planning, not from a project')
                  : t('Daily business, no light: the budget comes from the pre-planning, not from a project')}
              </td>
            </tr>
            {#each view.daily as r (r.product)}
              <tr>
                <td class="name"><span class="chip">{t('Daily business')}</span></td>
                {#if view.products.length > 1}
                  <td class="wrap">
                    <span class="chip"><span class="dot" style:background={productColor(productIndex(r.product))}></span>{productName(r.product)}</span>
                  </td>
                {/if}
                <td class="muted">{t('ongoing')}</td>
                <td class="muted">{t('no light')}</td>
                <td class="num"><Amount value={r.budget} est={estimated} /></td>
                <td class="num"><Amount value={r.done} est={estimated} /></td>
                <td class="num"><Amount value={r.planned} est={estimated} /></td>
                <td class="small muted">
                  {t('Budget of sprint {sprint}; done = sprint {done}', { sprint: view.conflictSprint, done: view.dailyDoneSprint || '–' })}
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
    {#if estimated}
      <p class="small muted" style="margin:8px 0 0">
        {t('Values with ≈ are estimates: points converted with the rate of each sprint (mean {rate} points per person day). Booked amounts are entered values.', { rate: num(view.rate, 2) })}
      </p>
    {/if}
  {/if}

  {#if view.conflict.length > 0}
    <ConflictView {view} />
  {/if}

  {#if view.closed.length > 0}
    <details class="card" style="margin-top:16px">
      <summary><strong>{t('Finished projects')}</strong> <span class="muted small">{view.closed.length}</span></summary>
      <div class="tw" style="margin-top:8px">
        <table class="t">
          <thead>
            <tr>
              <th>{t('Project')}</th>
              <th>{t('Closed as')}</th>
              <th>{t('End')}</th>
              <th class="num">{t('done (PD)')}</th>
              <th class="num">{t('booked (PD)')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each view.closed as p (p.id)}
              <tr>
                <td><a href={link('/projects/:id', { id: p.id })}>{p.name}</a></td>
                <td><LightChip light={p.state === 'cancelled' ? 'warn' : 'ok'} label={p.state === 'cancelled' ? t('cancelled') : t('finished')} /></td>
                <td class="data">{date(p.closedAt || p.end)}</td>
                <td class="num"><Amount value={p.done} est={estimated} /></td>
                <td class="num"><Amount value={p.booked} /></td>
                <td><button class="btn" type="button" onclick={() => reopen(p)}><Icon name="unarchive" />{t('Reopen')}</button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="small muted" style="margin:8px 0 0">{t('Reports, minutes and past sprints keep finished projects. Their rules no longer apply.')}</p>
    </details>
  {/if}

  {#if panel?.kind === 'new'}
    <ProjectForm
      {view}
      onclose={() => (panel = undefined)}
      onsaved={() => {
        panel = undefined;
        void load();
      }}
    />
  {:else if closing}
    <CloseProject
      {view}
      project={closing}
      onclose={() => (panel = undefined)}
      ondone={() => {
        panel = undefined;
        void load();
      }}
    />
  {/if}
{/if}

<style>
  .head {
    margin-bottom: 8px;
  }
  .scroll {
    overflow-x: auto;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    margin-top: 8px;
    align-items: center;
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .sw {
    width: 18px;
    height: 10px;
    border: 1px solid var(--primary);
    background: var(--primary-weak);
    border-radius: 2px;
    display: inline-block;
  }
  td.name,
  td.wrap {
    white-space: normal;
    min-width: 200px;
  }
  tr.sub td {
    background: var(--surface-2);
    font-weight: 600;
    font-size: 0.9em;
  }
  .nowrap {
    flex-wrap: nowrap;
    gap: 4px;
  }
  summary {
    cursor: pointer;
  }
</style>
