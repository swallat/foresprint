<script lang="ts">
  import { api } from '../../lib/api';
  import { app, openTicket, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { go, link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { ProjectDetail } from '../../lib/types.projects';
  import Banner from '../../lib/ui/Banner.svelte';
  import Amount from './Amount.svelte';
  import CloseProject from './CloseProject.svelte';
  import { date, month, num, productColor } from './format';
  import { inputOf } from './input';
  import LightChip from './LightChip.svelte';
  import Meter from './Meter.svelte';
  import ProjectCalc from './ProjectCalc.svelte';
  import ProjectForm from './ProjectForm.svelte';
  import { reportMarkdown } from './report';

  let { params }: PageProps = $props();

  let d = $state<ProjectDetail | undefined>();
  let problem = $state('');
  let panel = $state<'edit' | 'close' | undefined>();

  let loadSeq = 0; // answers for an earlier team or project must not replace the current one
  async function load(): Promise<void> {
    if (!app.team || !params.id) return;
    const mine = ++loadSeq;
    try {
      const answer = await api.Project(app.team, params.id);
      if (mine !== loadSeq) return;
      d = answer;
      problem = '';
    } catch (e) {
      if (mine !== loadSeq) return;
      d = undefined;
      problem = String(e).replace(/^Error: /, '');
    }
  }

  $effect(() => {
    void app.team;
    void params.id;
    void load();
  });

  const p = $derived(d?.project);
  const estimated = $derived(d?.unit === 'SP');
  const closed = $derived(p?.state !== '');
  const productIndex = (id: string) => d?.products.findIndex((x) => x.id === id) ?? 0;
  const productName = (id: string) => d?.products.find((x) => x.id === id)?.name ?? id;
  const nextMilestone = $derived(p?.milestones.filter((m) => m.date >= (d?.today ?? '')).sort((a, b) => a.date.localeCompare(b.date))[0]);
  // Consumption entered by hand wins over the estimate from finished tickets.
  const spent = $derived(p ? (p.used ?? p.done) : null);
  const spentEst = $derived(estimated && p?.used === null);
  const useLight = (s: string): 'ok' | 'warn' | 'bad' => (s === 'over' ? 'bad' : s === 'tight' ? 'warn' : 'ok');
  const hasUsedMonths = $derived(p?.months.some((m) => m.used !== null) ?? false);
  const rate = $derived(d?.rate === null || d?.rate === undefined ? '' : num(d.rate, 2));

  // Tickets grouped by sprint; tickets without a sprint come last.
  const lanes = $derived.by(() => {
    if (!d) return [];
    const ids = [...new Set(d.tickets.map((x) => x.sprint).filter(Boolean))].sort();
    const lanes = ids.map((id) => ({ id, tickets: d!.tickets.filter((x) => x.sprint === id) }));
    const rest = d.tickets.filter((x) => !x.sprint);
    return rest.length ? [...lanes, { id: '', tickets: rest }] : lanes;
  });

  async function saveScope(text: string): Promise<void> {
    if (!p) return;
    const value = text.trim() === '' ? null : Number(text.replace(',', '.'));
    if (value !== null && (!Number.isFinite(value) || value < 0)) {
      toast(t('Please enter the amounts as numbers from 0.'), 'bad');
      return;
    }
    try {
      await api.SaveProject(app.team, { ...inputOf(p), openScope: value });
      await load();
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  async function reopen(): Promise<void> {
    if (!p) return;
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

  async function copyReport(): Promise<void> {
    if (!d) return;
    try {
      await navigator.clipboard.writeText(reportMarkdown(d));
      toast(t('The report is on the clipboard as Markdown.'), 'ok');
    } catch {
      toast(t('The report could not be copied.'), 'bad');
    }
  }
</script>

{#if problem}
  <Banner tone="bad">{problem}</Banner>
  <a href={link('/projects')}>{t('Back to the projects')}</a>
{:else if !d || !p}
  <p class="muted">{t('Loading ...')}</p>
{:else}
  <div class="page-head">
    <div>
      <div class="small muted"><a href={link('/projects')}>{t('Projects')}</a> / {t('Project')}</div>
      <h1>{p.name} <LightChip light={p.light} label={closed ? (p.state === 'cancelled' ? t('cancelled') : t('finished')) : undefined} /></h1>
      <p class="lead">
        {t('Ends {date}.', { date: date(p.end) })}
        {#if d.source === 'tracker'}
          {#if p.rule}{t('Rule:')} <span class="data rule-txt">{p.rule}</span>{:else}{t('Without a rule you assign tickets by hand.')}{/if}
          {#if !closed}<button class="link" type="button" onclick={() => (panel = 'edit')}>{p.rule ? t('Change rule') : t('Add rule')}</button>{/if}
        {/if}
      </p>
    </div>
    <div class="actions">
      <select class="input" aria-label={t('Switch project')} value={p.id} onchange={(e) => go(`/projects/${encodeURIComponent(e.currentTarget.value)}`)}>
        {#each [...d.projects, ...d.closed] as x (x.id)}<option value={x.id}>{x.name}</option>{/each}
      </select>
      {#if closed}
        <button class="btn" type="button" onclick={reopen}><Icon name="unarchive" />{t('Reopen')}</button>
      {:else}
        <button class="btn" type="button" onclick={() => (panel = 'edit')}><Icon name="edit" />{t('Edit')}</button>
        <button class="btn" type="button" onclick={() => (panel = 'close')}>
          <Icon name={p.history ? 'archive' : 'delete'} />{p.history ? t('Finish') : t('Delete')}
        </button>
      {/if}
    </div>
  </div>

  {#if closed}
    <Banner>{t('This project is closed. Reports, minutes and past sprints keep it; its rules no longer apply.')}</Banner>
  {/if}
  {#if d.problem}<Banner tone="warn">{t('The lights could not be calculated: {reason}', { reason: d.problem })}</Banner>{/if}

  <div class="grid cols-3">
    <div class="card">
      {#if d.products.length > 1}
        <div class="small muted">{t('Products')}</div>
        <div class="row" style="margin-top:6px">
          {#each p.products as id (id)}<span class="chip"><span class="dot" style:background={productColor(productIndex(id))}></span>{productName(id)}</span>{/each}
        </div>
      {/if}
      {#if p.contact}
        <div class="small muted" style:margin-top={d.products.length > 1 ? '12px' : '0'}>{t('Contact person')}</div>
        <div style="margin-top:4px">{p.contact}</div>
      {/if}
      <div class="small muted" style:margin-top={d.products.length > 1 || p.contact ? '12px' : '0'}>{t('Next milestone')}</div>
      <div style="margin-top:4px">
        {#if nextMilestone}
          {nextMilestone.name} <span class="data">{date(nextMilestone.date)}</span> <LightChip light={nextMilestone.light} />
        {:else}{t('none left')}{/if}
      </div>
    </div>

    <div class="card">
      <div class="row">
        <div class="small muted" style="flex:1">{t('Contingent (PD)')}</div>
        {#if estimated}<span class="chip" title={t('Converted from points with the team rate')}>≈ {t('estimate')}</span>{/if}
      </div>
      <div class="big">
        <Amount value={spent === null && p.planned === null ? null : (spent ?? 0) + (p.planned ?? 0)} est={spentEst || (estimated && p.planned !== null)} inline />
        {#if p.booked !== null}<span class="muted" style="font-size:14px">{t('of {n}', { n: num(p.booked, 1) })}</span>{/if}
      </div>
      <Meter booked={p.booked} done={spent} planned={p.planned} />
      {#if p.used !== null && p.booked !== null}
        <div class="small" style="margin-top:8px">
          {t('Used {used} PD', { used: num(p.used, 1) })}{#if p.remaining !== null}, {t('{n} PD left', { n: num(p.remaining, 1) })}{/if}
          <LightChip light={useLight(p.usedStatus)} label={p.usedStatus === 'over' ? t('over the contingent') : p.usedStatus === 'tight' ? t('nearly used up') : t('within the contingent')} />
        </div>
      {/if}
      <div class="small muted" style="margin-top:8px">
        {t('done')} <Amount value={p.done} est={estimated} inline /><ProjectCalc project={p} rate={d.rate} kind="done" />, {t('planned')} <Amount value={p.planned} est={estimated} inline /><ProjectCalc project={p} rate={d.rate} kind="planned" />
        {#if estimated && rate}<span> · {t('rate {rate} points per PD', { rate })}</span>{/if}
      </div>
    </div>

    <div class="card">
      <div class="small muted">{t('Open scope')}</div>
      {#if d.source === 'none'}
        <div class="row" style="margin:4px 0">
          <input
            class="input data scope"
            inputmode="decimal"
            aria-label={t('Open scope in points')}
            value={p.openScope === null ? '' : String(p.openScope).replace('.', ',')}
            disabled={closed}
            onchange={(e) => void saveScope(e.currentTarget.value)}
          />
          <span class="muted">{t('points')}</span>
        </div>
        <div class="small muted">{t('Without tickets you keep it by hand, for example after each review.')}</div>
      {:else}
        <div class="big">{p.open} <span class="muted" style="font-size:14px">{d.source === 'packages' ? t('work packages') : t('tickets')}</span></div>
      {/if}
      <div style="margin-top:8px">
        <a href={link('/forecast', {}, { tab: 'when', project: p.id })}><Icon name="monitoring" size={18} />{t('When will it be done?')}</a>
      </div>
    </div>
  </div>

  <div class="grid cols-2" style="margin-top:16px">
    <div class="card">
      <h2>{t('Milestones')}</h2>
      {#if p.milestones.length === 0}
        <p class="muted" style="margin:0 0 8px">{t('No milestones yet.')}</p>
      {:else}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{t('Milestone')}</th>
                <th>{t('Date')}</th>
                {#if d.source !== 'none'}<th class="num">{t('Tickets')}</th>{/if}
                <th>{t('Traffic light')}</th>
              </tr>
            </thead>
            <tbody>
              {#each p.milestones as m (m.id)}
                <tr>
                  <td class="wrap">{m.name}</td>
                  <td class="data">{date(m.date)}</td>
                  {#if d.source !== 'none'}<td class="num">{m.total ? t('{done} of {total} done', { done: m.done, total: m.total }) : '–'}</td>{/if}
                  <td>
                    <LightChip light={m.light} />
                    {#if m.source === 'hand'}<span class="small muted"> {t('set by hand')}</span>{:else if m.late.length > 0}<span class="small muted" title={m.late.join(', ')}> {t('{n} tickets late', { n: m.late.length })}</span>{/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
      <p class="small muted" style="margin:8px 0">
        {t('A light set by hand always counts. Without one, a milestone with tickets gets its light from the state of its tickets.')}
      </p>
      {#if !closed}<button class="btn" type="button" onclick={() => (panel = 'edit')}><Icon name="add" />{t('Add milestone')}</button>{/if}
    </div>

    <div class="card">
      <h2>{t('Contingent per month')}</h2>
      {#if p.months.length > 0}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{t('Month')}</th>
                <th class="num">{t('booked')}</th>
                {#if hasUsedMonths}<th class="num">{t('used')}</th>{/if}
                <th class="num">{t('done')}</th>
                <th class="num">{t('planned')}</th>
                <th class="num">{t('Left')}</th>
              </tr>
            </thead>
            <tbody>
              {#each p.months as r (r.month)}
                {@const left = r.used !== null && r.remaining !== null ? r.remaining - (r.planned ?? 0) : r.booked - (r.done ?? 0) - (r.planned ?? 0)}
                <tr>
                  <td>
                    {month(r.month)}
                    {#if left < -0.05}<span class="over" title={t('Overbooked')}><Icon name="warning" size={14} /><span class="sr">{t('Overbooked')}</span></span>{/if}
                  </td>
                  <td class="num"><Amount value={r.booked} /></td>
                  {#if hasUsedMonths}<td class="num"><Amount value={r.used} /></td>{/if}
                  <td class="num"><Amount value={r.done} est={estimated} /></td>
                  <td class="num"><Amount value={r.planned} est={estimated} /></td>
                  <td class="num" class:over={left < -0.05}><Amount value={left} est={estimated} /></td>
                </tr>
              {/each}
              <tr class="sum">
                <td>{t('Total')}</td>
                <td class="num"><Amount value={p.months.reduce((a, r) => a + r.booked, 0)} /></td>
                {#if hasUsedMonths}<td class="num"><Amount value={p.months.reduce((a, r) => a + (r.used ?? 0), 0)} /></td>{/if}
                <td class="num"><Amount value={p.months.reduce((a, r) => a + (r.done ?? 0), 0)} est={estimated} /></td>
                <td class="num"><Amount value={p.months.reduce((a, r) => a + (r.planned ?? 0), 0)} est={estimated} /></td>
                <td class="num"></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="small muted" style="margin:8px 0 0">
          {t('All values in person days. Work is counted in the month in which its sprint ends. Early months overbooked while later ones have room is a hint to move work.')}
        </p>
      {:else}
        <Banner>
          {#if p.booked !== null}{t('Only a total of {n} PD is booked, with no split per month. That is fine.', { n: num(p.booked, 1) })}{:else}{t('No contingent booked yet.')}{/if}
        </Banner>
        {#if !closed}<button class="btn" type="button" onclick={() => (panel = 'edit')}><Icon name="add" />{t('Add a split per month')}</button>{/if}
      {/if}
    </div>
  </div>

  {#if d.source !== 'none'}
    <h2 style="margin:24px 0 8px" data-tour="project-tickets">{t('Tickets by sprint')}</h2>
    {#if lanes.length === 0}
      <Banner>{t('No tickets assigned yet. Assign tickets by hand in the backlog, or add a rule to the project.')}</Banner>
    {:else}
      {#each lanes as lane (lane.id)}
        <div class="lane" style="margin-bottom:12px">
          <div class="lane-head">
            <div class="row">
              <strong>{lane.id ? t('Sprint {id}', { id: lane.id }) : t('Not earmarked')}</strong>
              <span class="muted small">{t('{n} tickets', { n: lane.tickets.length })}</span>
            </div>
          </div>
          <div class="lane-body">
            {#each lane.tickets as tk (tk.key)}
              <div class="tk">
                <button type="button" class="link data" onclick={() => openTicket(tk.key)}>{tk.key}</button>
                <span class="title" class:done={tk.done}>{tk.title}</span>
                <span class="chip">{tk.status || '–'}</span>
                <span class="est">{num(tk.estimate, 1)}</span>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    {/if}
  {/if}

  <div class="card" style="margin-top:24px" data-tour="project-report">
    <div class="row">
      <h2 style="margin:0;flex:1">{t('Report for the project lead')}</h2>
      <button class="btn primary" type="button" onclick={copyReport}><Icon name="ios_share" />{t('Copy report')}</button>
    </div>
    <p style="margin:8px 0 12px">
      {t('As of {date}: {done} of {booked} PD done, another {planned} PD planned (estimate).', {
        date: date(d.today),
        done: num(p.done, 1),
        booked: p.booked === null ? '–' : num(p.booked, 1),
        planned: num(p.planned, 1),
      })}
      {#if nextMilestone}{t('Next milestone "{name}" on {date}.', { name: nextMilestone.name, date: date(nextMilestone.date) })}{/if}
    </p>
    {#if d.report.length > 0}
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th>{t('Sprint')}</th>
              <th class="num">{t('booked (PD)')}</th>
              <th class="num">{t('planned (PD)')}</th>
              <th class="num">{t('done (PD)')}</th>
              <th>{t('Ratio')}</th>
            </tr>
          </thead>
          <tbody>
            {#each d.report as r (r.sprint)}
              {@const used = (r.planned ?? 0) + (r.done ?? 0)}
              <tr>
                <td><span class="data">{r.sprint}</span> {#if r.state === 'current'}<span class="chip">{t('running now')}</span>{/if}</td>
                <td class="num"><Amount value={r.booked} /></td>
                <td class="num"><Amount value={r.planned} est={estimated} /></td>
                <td class="num"><Amount value={r.done} est={estimated} /></td>
                <td>
                  {#if r.booked + used === 0}<span class="muted">{t('nothing')}</span>
                  {:else if used > r.booked + 0.05}<span class="over"><Icon name="warning" size={14} />{t('{n} PD over booked', { n: num(used - r.booked, 1) })}</span>
                  {:else}<span class="muted">{t('{n} PD free', { n: num(r.booked - used, 1) })}</span>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="small muted" style="margin:8px 0 0">
        {t('Booked per sprint: the monthly value split over the sprints ending in that month. Planned and done: points divided by the team rate.')}
      </p>
    {/if}
  </div>

  {#if panel === 'edit'}
    <ProjectForm
      view={d}
      project={p}
      onclose={() => (panel = undefined)}
      onsaved={() => {
        panel = undefined;
        void load();
      }}
    />
  {:else if panel === 'close'}
    <CloseProject
      view={d}
      project={p}
      onclose={() => (panel = undefined)}
      ondone={() => {
        panel = undefined;
        go('/projects');
      }}
    />
  {/if}
{/if}

<style>
  .big {
    font: 600 22px/28px var(--font-data);
    margin: 4px 0 8px;
  }
  .scope {
    width: 96px;
    text-align: right;
    font-size: 20px;
    height: 40px;
  }
  td.wrap {
    white-space: normal;
    min-width: 140px;
  }
  .over {
    color: var(--bad);
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .tk {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) auto 48px;
    gap: 8px;
    align-items: center;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
  }
  .tk:last-child {
    border-bottom: 0;
  }
  .tk .title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tk .title.done {
    color: var(--text-muted);
    text-decoration: line-through;
  }
</style>
