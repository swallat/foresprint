<script lang="ts">
  // Pre-plan (flows.md F3, decisions 14, 17, 20): the plannable amount of a sprint, the amount
  // per product, the production against its time, earmarked tickets by project and the what-if
  // for the running sprint. Works for any sprint at any time; nothing here is a gate.
  import { api } from '../../lib/api';
  import { app, openTicket, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { assumptions, fmt, itemWord, parseAmount, PlanModel, signed, touched, unitName } from '../../lib/plan/model.svelte';
  import Matrix from '../../lib/plan/Matrix.svelte';
  import Production from '../../lib/plan/Production.svelte';
  import SprintHead from '../../lib/plan/SprintHead.svelte';
  import Summary from '../../lib/plan/Summary.svelte';
  import TicketRow from '../../lib/plan/TicketRow.svelte';
  import type { PlanProduct, PlanSprint } from '../../lib/types.plan';
  import WhatIfCard from './WhatIfCard.svelte';
  import type { PageProps } from '../../lib/routes';

  let { params }: PageProps = $props();
  void params;

  const model = new PlanModel();
  $effect(() => {
    void app.team;
    void app.sprint;
    model.loading = true;
    void model.reload();
  });

  const d = $derived(model.data);
  const noT = $derived(d?.source === 'none');
  const used = $derived(d ? (noT ? d.preplanned : d.earmarked) : 0);
  const over = $derived(d && d.high != null && Math.max(d.preplanned, d.earmarked) > d.high);

  type Group = { po: string; rows: PlanProduct[] };
  const groups = $derived.by<Group[]>(() => {
    if (!d) return [];
    const rows = d.products.filter((p) => p.active || p.pre != null || p.earmark > 0);
    if (!d.multiPO) return [{ po: '', rows }];
    const by = new Map<string, PlanProduct[]>();
    for (const p of rows) by.set(p.poName, [...(by.get(p.poName) ?? []), p]);
    return [...by].map(([po, list]) => ({ po, rows: list }));
  });
  const total = (rows: PlanProduct[], f: (p: PlanProduct) => number | null) => rows.reduce((a, p) => a + (f(p) ?? 0), 0);
  const all = $derived(groups.flatMap((g) => g.rows));
  const anyPre = $derived(all.some((p) => p.pre != null));

  /** Puts the stored text back into a field whose input was refused: the data did not change, so the field would keep the bad text. */
  const restore = (el: HTMLInputElement, shown: number | string) => void (el.value = String(shown));

  async function setPre(p: PlanProduct, el: HTMLInputElement): Promise<void> {
    const v = parseAmount(el.value);
    if (v === undefined) return restore(el, p.pre ?? '');
    await model.change(() => api.SetPreplanned(app.team, d!.sprint, p.id, v));
  }
  async function setProject(id: string, el: HTMLInputElement): Promise<void> {
    const v = parseAmount(el.value);
    if (v === undefined) return restore(el, d?.projects.find((q) => q.id === id)?.amount || '');
    await model.change(() => api.SetProjectAmount(app.team, d!.sprint, id, v));
  }
  async function setSprintPre(el: HTMLInputElement): Promise<void> {
    const v = parseAmount(el.value);
    if (v === undefined) return restore(el, d?.sprintPre ?? '');
    await model.change(() => api.SetSprintPreplanned(app.team, d!.sprint, v));
  }
  const takeEarmarks = () => model.change(() => api.TakeEarmarks(app.team, d!.sprint), t('Amounts taken from the earmarks.'));
  const writeMinutes = () =>
    model.change(async () => {
      const file = await api.SavePreplanMinutes(app.team, d!.sprint);
      toast(t('Pre-planning minutes written: {file}', { file }), 'ok');
    });
  const useDefaults = () => model.change(() => api.UseDefaults(app.team, d!.sprint), t('Standard amounts taken over.'));

  /** Earmarked tickets by project; daily business (no project) last. */
  const byProject = $derived.by(() => {
    if (!d) return [];
    const ids = [...d.projects.map((p) => p.id), ''];
    return ids
      .map((id) => ({ id, project: d.projects.find((p) => p.id === id), list: d.tickets.filter((x) => (x.project || '') === id) }))
      .filter((g) => g.list.length);
  });
  const sumOf = (list: { size: number | null }[]) => list.reduce((a, x) => a + (x.size ?? 0), 0);
</script>

{#if model.error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{model.error}</div></div>
{:else if d}
  <SprintHead {d} stage="preplan">
    {#snippet actions()}
      {#if d.stage === 'open' || d.stage === 'planned'}
        <button class="btn" type="button" id="minutes" onclick={writeMinutes}><Icon name="description" />{t('Write minutes')}</button>
      {/if}
      {#if !noT && d.multiProduct}
        <button class="btn" type="button" id="take" onclick={takeEarmarks}><Icon name="playlist_add" />{t('Take over earmarks')}</button>
      {/if}
      {#if d.multiProduct}
        <button class="btn" type="button" id="defaults" onclick={useDefaults}><Icon name="restart_alt" />{t('Take over standard')}</button>
      {/if}
    {/snippet}
  </SprintHead>

  <Summary {d} {used} assumption={touched(assumptions.active, d.source !== 'none') ? assumptions.active?.label : ''} whatIf={model.running} />
  <WhatIfCard {d} {model} />

  {#if over}
    <div class="banner warn" id="overcap">
      <Icon name="warning" />
      <div class="grow">
        {t('Pre-planned {pre} and earmarked {ear} are above the upper end {high} of the Forecast PLAN ({plan}). This is only a warning; the team decides in the planning.', { pre: fmt(d.preplanned), ear: fmt(d.earmarked), high: fmt(d.high), plan: fmt(d.plan) })}
      </div>
    </div>
  {/if}

  {#if d.multiProduct}
    <h2>{t('Amount per product')}</h2>
    <div class="tw" data-tour="preplan-table">
      <table class="t" id="product-table">
        <thead>
          <tr>
            <th>{t('Product')}</th>
            <th class="num">{t('Standard')}</th>
            <th class="num">{t('Pre-planned')}</th>
            {#if !noT}<th class="num">{t('Earmarks')}</th><th class="num">{t('Deviation')}</th>{/if}
            <th class="num">{t('Planned')}</th>
            {#if d.production}<th class="num">{t('of it prod')}</th>{/if}
            <th class="num">{t('Done')}</th>
          </tr>
        </thead>
        <tbody>
          {#each groups as g (g.po)}
            {#if d.multiPO}<tr class="po"><td colspan="9">{t('PO')} {g.po || t('without PO')}</td></tr>{/if}
            {#each g.rows as p (p.id)}
              {@const dev = p.pre == null ? null : p.pre - p.earmark}
              <tr>
                <td>{p.name}</td>
                <td class="num">{fmt(p.default)}</td>
                <td class="num edit">
                  <input aria-label={t('Pre-planned {product}', { product: p.name })} inputmode="decimal" value={p.pre ?? ''} placeholder="–" onchange={(e) => setPre(p, e.currentTarget)} />
                </td>
                {#if !noT}
                  <td class="num">{fmt(p.earmark, 1)}</td>
                  <td class="num">{#if dev == null}–{:else}<span class:chip={dev < 0} class:warn={dev < 0}>{signed(dev)}</span>{/if}</td>
                {/if}
                <td class="num">{fmt(p.planned)}</td>
                {#if d.production}<td class="num">{fmt(p.prodPlanned)}</td>{/if}
                <td class="num">{fmt(p.done)}</td>
              </tr>
            {/each}
            {#if d.multiPO}
              <tr class="sum">
                <td>{t('Sum {po}', { po: g.po })}</td>
                <td class="num">{fmt(total(g.rows, (p) => p.default))}</td>
                <td class="num">{g.rows.some((p) => p.pre != null) ? fmt(total(g.rows, (p) => p.pre)) : '–'}</td>
                {#if !noT}<td class="num">{fmt(total(g.rows, (p) => p.earmark), 1)}</td><td class="num">{g.rows.some((p) => p.pre != null) ? signed(total(g.rows, (p) => p.pre) - total(g.rows, (p) => p.earmark)) : '–'}</td>{/if}
                <td class="num">{fmt(total(g.rows, (p) => p.planned))}</td>
                {#if d.production}<td class="num">{fmt(total(g.rows, (p) => p.prodPlanned))}</td>{/if}
                <td class="num">{fmt(total(g.rows, (p) => p.done))}</td>
              </tr>
            {/if}
          {/each}
          <tr class="sum">
            <td>{t('Total')}</td>
            <td class="num">{fmt(total(all, (p) => p.default))}</td>
            <td class="num">{anyPre ? fmt(total(all, (p) => p.pre)) : '–'}</td>
            {#if !noT}<td class="num">{fmt(total(all, (p) => p.earmark), 1)}</td><td class="num">{anyPre ? signed(total(all, (p) => p.pre) - total(all, (p) => p.earmark)) : '–'}</td>{/if}
            <td class="num">{fmt(total(all, (p) => p.planned))}</td>
            {#if d.production}<td class="num">{fmt(total(all, (p) => p.prodPlanned))}</td>{/if}
            <td class="num">{fmt(total(all, (p) => p.done))}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="small muted gap">
      {[
        t('Editable here: pre-planned.'),
        t('Standard comes from the budget share.'),
        noT ? '' : t('Earmarks are the sum of the earmarked tickets (a suggestion).'),
        t('Planned and done are filled by the planning and the review and are read-only here.'),
      ]
        .filter(Boolean)
        .join(' ')}
    </p>
  {:else}
    <div class="banner info">
      <Icon name="info" />
      <div class="grow">
        {t('Your team plans without products, so there is no amount per product. The plannable amount above is what the team can take on.')}
      </div>
    </div>
    <div class="row gap">
      <label for="sprint-pre">{t('Pre-planned amount of the sprint ({unit})', { unit: unitName(d) })}</label>
      <input id="sprint-pre" class="num" inputmode="decimal" value={d.sprintPre ?? ''} placeholder="–" onchange={(e) => setSprintPre(e.currentTarget)} />
    </div>
  {/if}

  <Matrix {d} {model} />

  <Production {d} {model} />

  {#if noT && d.projects.length}
    <section id="project-amounts" class="gap">
      <h2>{t('Of it for projects')}</h2>
      <div class="tw">
        <table class="t">
          <thead>
            <tr><th>{t('Project')}</th><th class="num">{unitName(d)}</th><th class="num">≈ {t('PD')}</th><th class="num">{t('Contingent')}</th></tr>
          </thead>
          <tbody>
            {#each d.projects as p (p.id)}
              <tr>
                <td>{p.name}</td>
                <td class="num edit">
                  <input inputmode="decimal" value={p.amount || ''} placeholder="–" aria-label={t('{project} in {unit}', { project: p.name, unit: unitName(d) })} onchange={(e) => setProject(p.id, e.currentTarget)} />
                </td>
                <td class="num">{p.needPD == null ? '–' : fmt(p.needPD, 1)}</td>
                <td class="num">{p.bookedPD == null ? '–' : `${fmt(p.bookedPD)} ${t('PD')}`}</td>
              </tr>
            {/each}
            <tr class="sum"><td>{t('Daily business')}</td><td class="num">{fmt(Math.max(0, d.preplanned - d.projects.reduce((a, p) => a + p.amount, 0)))}</td><td></td><td></td></tr>
          </tbody>
        </table>
      </div>
      <p class="small muted gap">
        {t('Without tickets you split the amount into projects by hand. What is left is daily business. Contingents and project lights use these numbers.')}
      </p>
    </section>
  {/if}

  {#if !noT}
    <section id="earmarks" class="gap" data-tour="preplan-earmarks">
      <div class="row head">
        <h2>{t('Earmarked {items} by project', { items: itemWord(d) })}</h2>
        <a class="btn" href="#/backlog"><Icon name="view_list" />{t('Earmark in the backlog')}</a>
      </div>
      {#if byProject.length === 0}
        <div class="banner">
          <Icon name="inbox" />
          <div class="grow">
            {t('Nothing earmarked for {sprint} yet. In the backlog, drag {items} into the column of this sprint.', { sprint: d.sprint, items: itemWord(d) })}
            {#if d.source === 'packages'}{t('Work packages are created in the backlog with “Create work package”.')}{/if}
          </div>
        </div>
      {:else}
        <div class="stack groups">
          {#each byProject as g (g.id)}
            <div class="card flush">
              <div class="row group-head">
                <span class="chip"><Icon name="flag" size={14} />{g.project?.name ?? t('Daily business')}</span>
                <span class="small muted">{g.list.length} {itemWord(d, g.list.length !== 1)} · <span class="data">{fmt(sumOf(g.list), 1)}</span> {unitName(d)}</span>
                <span class="spacer"></span>
                {#if g.project}
                  <span class="small">
                    {g.project.needPD == null ? '' : `≈ ${fmt(g.project.needPD, 1)} ${t('PD')}`}
                    <span class="chip">{t('estimate')}</span>
                    {g.project.bookedPD == null ? t('no contingent') : t('of {n} PD booked', { n: fmt(g.project.bookedPD) })}
                  </span>
                  <Calc label={g.project.name} topic="units">
                    <div class="data">{fmt(g.project.amount, 1)} {unitName(d)} ÷ {fmt(d.rate, 2)} = {fmt(g.project.needPD, 1)} {t('PD')}</div>
                  </Calc>
                {:else}
                  <span class="small muted">{t('Daily business: no contingent, runs through the product amounts')}</span>
                {/if}
              </div>
              <div role="list">
                {#each g.list as x (x.key)}<TicketRow ticket={x} {d} showProject={false} />{/each}
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </section>
  {/if}
{:else if model.loading}
  <p class="muted">{t('Loading …')}</p>
{:else}
  <div class="banner info"><Icon name="info" /><div class="grow">{t('Choose a team and a sprint first.')}</div></div>
{/if}

<style>
  .gap {
    margin-top: 16px;
  }
  .head {
    margin-bottom: 8px;
  }
  .head h2 {
    margin: 0;
    flex: 1;
  }
  .groups {
    gap: 16px;
  }
  .flush {
    padding: 0;
  }
  .group-head {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }
  .spacer {
    flex: 1;
  }
  tr.po td {
    background: var(--surface-2);
    font-size: 12px;
    color: var(--text-muted);
    font-weight: 600;
  }
</style>
