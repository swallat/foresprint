<script lang="ts">
  // Plan (flows.md F4, decisions 6, 7, 10): with tickets two lanes, candidates left and sprint
  // right, filled from the earmarks; the team moves tickets until the sum, the products and the
  // projects fit, then freezes the agreement (ticket list, commitment, minutes). Without tickets
  // the team agrees on an amount per product and a commitment. Moving works by drag, by the
  // buttons and by Alt+arrow; nothing is locked before the agreement.
  import { api } from '../../lib/api';
  import { isNoopMove } from '../../lib/plan/moves';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { assumptions, fmt, fmtRate, itemWord, parseAmount, PlanModel, signed, touched, unitName, fmtVal } from '../../lib/plan/model.svelte';
  import Production from '../../lib/plan/Production.svelte';
  import SprintHead from '../../lib/plan/SprintHead.svelte';
  import Summary from '../../lib/plan/Summary.svelte';
  import TicketRow from '../../lib/plan/TicketRow.svelte';
  import WriteBack from '../../lib/plan/WriteBack.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { FreezeInput, PlanTicket } from '../../lib/types.plan';
  import CapacityBar from '../../lib/ui/CapacityBar.svelte';
  import DropGap from '../../lib/ui/DropGap.svelte';
  import { fits, group, sortTickets } from '../backlog/backlog';
  import TicketFilter from '../backlog/TicketFilter.svelte';
  import { ui } from '../backlog/store.svelte';

  let {}: PageProps = $props();

  const model = new PlanModel();
  /** Amounts and commitment without tickets, typed during the planning. */
  let amounts = $state<Record<string, number>>({});
  let commit = $state<number | null>(null);
  let over = $state(false);
  let overWhich = $state('');

  $effect(() => {
    void app.team;
    void app.sprint;
    amounts = {};
    commit = null;
    ctx = null;
    model.loading = true;
    void model.reload();
  });

  const d = $derived(model.data);

  /** Tickets the tracker still has in the sprint that the team took out (saved with the sprint). */
  const removed = $derived<string[]>(d?.removed ?? []);
  const noT = $derived(d?.source === 'none');
  const frozen = $derived(!!d?.frozen);
  /** Both lanes follow the filter, sort and grouping of the backlog (shared state, view only, nothing is saved). */
  const byRank = (list: PlanTicket[]): PlanTicket[] => sortTickets(list, ui.sort);
  /** Reordering by drag needs the order of the list: rank or planning order, not grouped. */
  const canReorder = $derived((ui.sort === 'rank' || ui.sort === 'order') && ui.group === 'none');
  const lane = $derived<PlanTicket[]>(byRank(d?.tickets ?? []));
  /** What the filter leaves of the sprint lane; the sums and the freeze use the whole lane. */
  const laneShown = $derived(lane.filter((x) => fits(x, ui.filter)));
  const allCandidates = $derived<PlanTicket[]>(d?.candidates ?? []);
  let showRunning = $state(false);
  const candidates = $derived(
    byRank(allCandidates).filter((x) => (showRunning || !d?.running || x.sprint !== d.running) && fits(x, ui.filter)),
  );
  const hidden = $derived(allCandidates.length - candidates.length);
  const laneHidden = $derived(lane.length - laneShown.length);
  const sections = <T extends PlanTicket>(list: T[]) => (d && ui.group !== 'none' ? group(list, ui.group, { products: d.products, projects: d.projects }) : []);
  const sizeSum = (l: PlanTicket[]) => l.reduce((a, x) => a + (x.size ?? 0), 0);
  const laneSum = $derived(sizeSum(lane));
  const unrefined = $derived(lane.filter((x) => !x.refined && x.size != null).length);
  const noEstimate = $derived(lane.filter((x) => x.size == null).length);

  const amountOf = (id: string, pre: number | null, def: number | null) => amounts[id] ?? pre ?? def ?? 0;
  const amountSum = $derived(d ? d.products.filter((p) => p.active).reduce((a, p) => a + amountOf(p.id, p.pre, p.default), 0) : 0);
  const commitment = $derived(noT ? (commit ?? amountSum) : laneSum);
  const used = $derived(noT ? commitment : laneSum);

  const adjust = $derived(
    d && d.source === 'tracker'
      ? allCandidates.filter((x) => x.inTracker === d.sprint && removed.includes(x.key))
      : [],
  );

  // --- Moving -----------------------------------------------------------------------------
  async function move(key: string, to: 'sprint' | 'candidates'): Promise<void> {
    if (!d || frozen) return;
    const x = [...d.tickets, ...d.candidates].find((q) => q.key === key);
    if (!x || isNoopMove(d, key, to)) return;
    const wasRemoved = removed.includes(key);
    const earmark = x.sprint;
    // A ticket the tracker has in a sprint is decided there: it is taken out with a mark, never earmarked.
    const free = x.inTracker === '';
    if (to === 'sprint') {
      await model.change(async () => {
        if (wasRemoved) await api.SetRemoved(app.team, d.sprint, key, false);
        if (free) await api.EarmarkTicket(app.team, key, d.sprint, '');
      });
    } else {
      await model.change(async () => {
        if (x.inTracker === d.sprint) await api.SetRemoved(app.team, d.sprint, key, true);
        if (free) await api.EarmarkTicket(app.team, key, '', '');
      });
    }
    toast(to === 'sprint' ? t('{key} taken into the sprint.', { key }) : t('{key} taken out of the sprint.', { key }), 'info', {
      label: t('Undo'),
      run: () => {
        void model.change(async () => {
          await api.SetRemoved(app.team, d.sprint, key, wasRemoved);
          if (free) await api.EarmarkTicket(app.team, key, earmark, '');
        });
      },
    });
  }

  let dragKey = $state('');
  let dragHeight = $state(40);
  /** The row a re-sorting drag hovers over, and on which half (the dragged ticket lands before or after it). */
  let overRow = $state<{ key: string; after: boolean; here: 'sprint' | 'candidates' } | null>(null);
  /** A drag over the lane itself (not a row), from the other lane: the ticket will be taken in. */
  function laneDrop(here: 'sprint' | 'candidates'): boolean {
    return over && overWhich === here && !overRow && !!dragKey && !frozen && !isNoopMove(d!, dragKey, here) && (listOf(here).length === 0 || endLands(here));
  }
  const listOf = (here: 'sprint' | 'candidates'): PlanTicket[] => (here === 'sprint' ? laneShown : candidates);
  /** A drop on the empty part of a list puts the ticket at its end (rank order, ungrouped). */
  const endLands = (here: 'sprint' | 'candidates'): boolean => canReorder && ui.sort === 'rank' && listOf(here).length > 0;
  /** A dragleave counts only when the pointer leaves the element, not when it moves onto a child of it. */
  function leaves(e: DragEvent): boolean {
    const el = e.currentTarget as HTMLElement;
    // Where the engine gives no target (WebView2 often does not), the pointer position decides.
    if (!(e.relatedTarget instanceof Node)) {
      const r = el.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    }
    return !el.contains(e.relatedTarget);
  }
  /** The pointer left a lane. The engine may report it after the next lane has taken over, so only this lane's own state is cleared. */
  function laneLeave(e: DragEvent, here: 'sprint' | 'candidates'): void {
    if (!leaves(e)) return;
    if (overWhich === here) over = false;
    if (overRow?.here === here) overRow = null;
  }
  function dragEnd(): void {
    dragKey = '';
    over = false;
    overRow = null;
  }
  function rowOver(e: DragEvent, key: string, here: 'sprint' | 'candidates'): void {
    if (frozen || !canReorder || !dragKey || dragKey === key || !positional(here)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    over = false;
    // The half is read from the ticket itself, not the slot: the gap sits in the slot and must not move the middle.
    const row = Array.from((e.currentTarget as HTMLElement).children).find((c) => !c.classList.contains('drop-gap'));
    if (!row) return;
    const r = row.getBoundingClientRect();
    if (e.clientY >= r.top && e.clientY <= r.bottom) overRow = { key, after: e.clientY > r.top + r.height / 2, here };
    else if (overRow?.key !== key) overRow = { key, after: e.clientY > r.top + r.height / 2, here };
  }
  async function rowDrop(e: DragEvent, key: string, here: 'sprint' | 'candidates'): Promise<void> {
    if (!canReorder || !overRow || overRow.key !== key || !dragKey || !positional(here)) return;
    e.preventDefault();
    e.stopPropagation();
    const moving = dragKey;
    const after = overRow.after;
    dragEnd();
    await landAt(moving, here, key, after);
  }
  /**
   * A ticket may be put at a chosen place of a list: inside its own list always (rank or planning
   * order), into the other list only in the rank order, which moves anywhere. In the planning order
   * the other list sorts it in by priority and project, so no place is promised there.
   */
  function positional(here: 'sprint' | 'candidates'): boolean {
    return isNoopMove(d!, dragKey, here) || ui.sort === 'rank';
  }
  /** Takes the ticket into the list (if it is in the other one), then puts it at the place. */
  async function landAt(key: string, here: 'sprint' | 'candidates', anchor: string, after: boolean): Promise<void> {
    if (!isNoopMove(d!, key, here)) {
      await move(key, here);
      if (!isNoopMove(d!, key, here)) return; // not taken in (refused or failed): no place in a list it is not in
    }
    await model.change(async () => void (await (ui.sort === 'rank' ? api.MoveTicketByRank : api.MoveWorkPackage)(app.team, key, anchor, after)));
  }
  // --- Right-click menu: "Move to", as in the backlog -------------------------------------
  let ctx = $state<{ key: string; x: number; y: number } | null>(null);
  function openMenu(e: MouseEvent, key: string): void {
    if (frozen || (e.target as HTMLElement).closest('a, input')) return; // keep the native menu on links
    e.preventDefault();
    ctx = { key, x: Math.max(0, Math.min(e.clientX, window.innerWidth - 260)), y: Math.max(0, Math.min(e.clientY, window.innerHeight - 220)) };
  }
  const ctxIn = $derived<'sprint' | 'candidates'>(ctx && lane.some((x) => x.key === ctx!.key) ? 'sprint' : 'candidates');
  async function ctxMove(to: 'sprint' | 'candidates'): Promise<void> {
    const key = ctx?.key;
    ctx = null;
    if (key) await move(key, to);
  }
  // Top or bottom of the list the ticket is in; the order only moves among tickets of the same
  // priority and project in the planning order, the app says so if refused.
  async function ctxEdge(top: boolean): Promise<void> {
    const key = ctx?.key;
    if (frozen) {
      ctx = null;
      return;
    }
    const list = ctxIn === 'sprint' ? lane : byRank(allCandidates);
    ctx = null;
    if (!canReorder) return;
    const others = list.filter((x) => x.key !== key);
    const anchor = top ? others[0] : others[others.length - 1];
    if (!key || !anchor) return;
    await model.change(async () => void (await (ui.sort === 'rank' ? api.MoveTicketByRank : api.MoveWorkPackage)(app.team, key, anchor.key, !top)));
  }

  function dragStart(e: DragEvent, key: string): void {
    dragKey = key;
    dragHeight = (e.currentTarget as HTMLElement | null)?.getBoundingClientRect().height || 40;
    e.dataTransfer?.setData('text/plain', key);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  function drop(to: 'sprint' | 'candidates'): void {
    const key = dragKey;
    const last = listOf(to).at(-1);
    const atEnd = !!key && !isNoopMove(d!, key, to) && endLands(to) && !!last;
    dragEnd();
    if (!key) return;
    if (atEnd) void landAt(key, to, last!.key, true);
    else void move(key, to);
  }
  function laneKey(e: KeyboardEvent, here: 'sprint' | 'candidates'): void {
    if (!e.altKey) return;
    const row = (e.target as HTMLElement).closest<HTMLElement>('[data-key]');
    if (!row) return;
    if (e.key === 'ArrowRight' && here === 'candidates') void move(row.dataset.key!, 'sprint');
    else if (e.key === 'ArrowLeft' && here === 'sprint') void move(row.dataset.key!, 'candidates');
    else return;
    e.preventDefault();
  }

  // --- Products and projects, live ----------------------------------------------------------
  const productRows = $derived(
    d
      ? d.products
          .filter((p) => p.active || p.pre != null)
          .map((p) => {
            const budget = p.pre ?? p.default ?? 0;
            const usedP = noT ? amountOf(p.id, p.pre, p.default) : sizeSum(lane.filter((x) => x.product === p.id));
            return { p, budget, usedP, diff: usedP - budget };
          })
      : [],
  );
  const projectRows = $derived.by(() => {
    if (!d) return [];
    const rate = d.rate ?? 0;
    return d.projects
      .map((p) => {
        const amount = noT ? p.amount : sizeSum(lane.filter((x) => x.project === p.id));
        const need = rate > 0 ? amount / rate : null;
        const rest = p.bookedPD != null && need != null ? p.bookedPD - (p.usedPD ?? 0) - need : null;
        return { p, amount, need, rest };
      })
      .filter((r) => r.amount > 0);
  });

  // --- Starting ------------------------------------------------------------------------------
  // The start of the sprint (in the head) freezes this agreement.
  const agreement = (): FreezeInput => ({
    tickets: lane.map((x) => x.key),
    commitment: noT ? commit : null,
    amounts: noT ? Object.fromEntries(d!.products.filter((p) => p.active).map((p) => [p.id, amountOf(p.id, p.pre, p.default)])) : {},
    removed: adjust.map((x) => x.key),
  });
  const reopen = () =>
    model.change(() => api.ReopenPlan(app.team, d!.sprint), t('Plan opened again. The planning minutes are marked as obsolete.'));
  // An invalid or empty entry keeps the stored value; the field shows it again, because the
  // state did not change and the typed text would otherwise stay in the box.
  const setAmount = (id: string, el: HTMLInputElement, current: number) => {
    const v = parseAmount(el.value);
    if (v != null) amounts[id] = v;
    el.value = String(v ?? current);
  };
  const setCommit = (el: HTMLInputElement) => {
    const v = parseAmount(el.value);
    if (v !== undefined) commit = v;
    el.value = String(commitment);
  };
</script>

{#if model.error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{model.error}</div></div>
{:else if d}
  <SprintHead {d} stage="plan" plan={agreement} onchange={() => model.reload()}>
    {#snippet actions()}
      {#if !noT}
        <a class="btn" href="#/present" id="present" data-tour="plan-present"><Icon name="fit_screen" />{t('Presentation view')}</a>
      {/if}
    {/snippet}
  </SprintHead>

  <Summary {d} used={used} commitment={frozen ? d.committed : null} count={lane.length} assumption={touched(assumptions.active, d.source !== 'none') ? assumptions.active?.label : ''} whatIf={model.running} {model} />

  {#if d.frozen}
    <div class="banner info" id="frozen">
      <Icon name="lock" />
      <div class="grow">
        {noT ? t('Frozen: commitment') : t('Frozen: {n} {items}, commitment', { n: d.frozen.tickets, items: itemWord(d) })}
        <span class="data">{fmtVal(d.frozen.commitment)}</span> {unitName(d)}. {t('The planning minutes are written.')}
        <div class="row gap">
          {#if d.stage === 'planned' || d.stage === 'open'}
            <button class="btn" type="button" id="reopen" onclick={reopen}><Icon name="lock_open" />{t('Open the plan again')}</button>
          {/if}
          <a class="btn" href="#/sprint/minutes"><Icon name="description" />{t('View minutes')}</a>
        </div>
      </div>
    </div>
  {/if}

  <p class="small muted mode">
    <span class="chip"><Icon name={noT ? 'inbox' : 'confirmation_number'} size={14} />{noT ? t('No tickets: amounts and commitment') : d.source === 'packages' ? t('Work packages in Foresprint') : t('Tickets from {tracker}', { tracker: d.trackerName || t('the tracker') })}</span>
    {t('Team setting, change it under Settings, Tickets and tracker.')}
  </p>

  {#if noT}
    <div class="card gapb">
      <div class="banner info"><Icon name="info" /><div class="grow">{t('Without tickets the team agrees on an amount per product and a commitment of its own. With a tracker the commitment follows from the chosen tickets.')}</div></div>
      {#if d.multiProduct}
        <div class="tw">
          <table class="t">
            <thead><tr><th>{t('Product')}</th><th class="num">{t('Pre-planned')}</th><th class="num">{t('Amount planned')}</th></tr></thead>
            <tbody>
              {#each productRows as r (r.p.id)}
                <tr>
                  <td>{r.p.name}</td>
                  <td class="num">{fmtVal(r.p.pre)}</td>
                  <td class="num edit"><input inputmode="decimal" value={r.usedP} disabled={frozen} aria-label={t('Amount {product}', { product: r.p.name })} onchange={(e) => setAmount(r.p.id, e.currentTarget, r.usedP)} /></td>
                </tr>
              {/each}
              <tr class="sum"><td>{t('Sum')}</td><td class="num">{fmtVal(d.preplanned)}</td><td class="num">{fmtVal(amountSum)}</td></tr>
            </tbody>
          </table>
        </div>
      {/if}
      <div class="row gap">
        <div class="field">
          <label for="commit">{t('Commitment in {unit}', { unit: unitName(d) })}</label>
          <input id="commit" class="input data num" inputmode="decimal" value={commitment} disabled={frozen} onchange={(e) => setCommit(e.currentTarget)} />
        </div>
        <div class="bar">
          <CapacityBar used={commitment} plan={d.plan} low={d.low} high={d.high} unit={unitName(d)} />
          <span class="small muted">{#if d.low !== null && d.high !== null}{t('Commitment against Forecast PLAN {plan} (range {low} to {high})', { plan: fmt(d.plan), low: fmt(d.low), high: fmt(d.high) })}{:else}{t('Commitment against Forecast PLAN {plan}', { plan: fmt(d.plan) })}{/if}</span>
        </div>
      </div>
    </div>
  {:else}
    <div class="filters" data-tour="plan-filters">
      <TicketFilter products={d.products} projects={d.projects} multi={d.multiProduct} />
    </div>
    <div id="lanes" class="grid cols-2 gapb" data-tour="plan-lanes">
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="lane"
        class:over={over && overWhich === 'candidates'}
        role="group"
        aria-label={t('Candidates')}
        ondragenter={(e) => { if (!frozen && dragKey) e.preventDefault(); }}
        ondragover={(e) => { if (!frozen) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; overRow = null; over = true; overWhich = 'candidates'; } }}
        ondragleave={(e) => laneLeave(e, 'candidates')}
        ondrop={(e) => { e.preventDefault(); drop('candidates'); }}
        onkeydown={(e) => laneKey(e, 'candidates')}
      >
        <div class="lane-head">
          <div class="row"><strong class="grow">{t('Candidates')}</strong><span class="small muted data">{candidates.length} {itemWord(d)} · {fmtVal(sizeSum(candidates))} {unitName(d)}</span></div>
          <span class="small muted">{t('Backlog and earmarked for later sprints')}</span>
          <div class="cand-filter" role="group" aria-label={t('Filter candidates')}>
            {#if d.running}
              <label class="small"><input type="checkbox" bind:checked={showRunning} /> {t('Running sprint too')}</label>
            {/if}
          </div>
          {#if hidden > 0}
            <span class="small muted">{t('{n} hidden by the filters', { n: hidden })}</span>
          {/if}
        </div>
        <div class="lane-body body" role="list">
          {@render laneList(candidates, 'candidates', hidden > 0 ? t('All candidates are hidden by the filters.') : t('No candidates left.'))}
        </div>
      </div>

      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="lane"
        class:over={over && overWhich === 'sprint'}
        role="group"
        aria-label={t('Sprint {sprint}', { sprint: d.sprint })}
        ondragenter={(e) => { if (!frozen && dragKey) e.preventDefault(); }}
        ondragover={(e) => { if (!frozen) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; overRow = null; over = true; overWhich = 'sprint'; } }}
        ondragleave={(e) => laneLeave(e, 'sprint')}
        ondrop={(e) => { e.preventDefault(); drop('sprint'); }}
        onkeydown={(e) => laneKey(e, 'sprint')}
      >
        <div class="lane-head">
          <div class="row">
            <strong class="grow">{t('Sprint {sprint}', { sprint: d.sprint })}</strong>
            <span class="data"><strong>{fmtVal(laneSum)}</strong> {t('of')} {fmt(d.plan)} {#if d.low !== null && d.high !== null}<span class="muted small">({fmt(d.low)} – {fmt(d.high)})</span>{/if}</span>
          </div>
          <CapacityBar used={laneSum} plan={d.plan} low={d.low} high={d.high} unit={unitName(d)} />
          <div class="row small">
            {#if d.high != null && laneSum > d.high}<span class="chip bad">{t('{n} over the range', { n: fmtVal(laneSum - d.high) })}</span>
            {:else if d.low != null && laneSum < d.low}<span class="chip fc">{t('{n} to the range', { n: fmtVal(d.low - laneSum) })}</span>
            {:else}<span class="chip ok">{t('within the range')}</span>{/if}
            {#if unrefined}<span class="chip warn">{t('{n} not refined', { n: unrefined })}</span>{/if}
            {#if noEstimate}<span class="chip warn">{t('{n} without estimate (count 0)', { n: noEstimate })}</span>{/if}
            {#if laneHidden > 0}<span class="muted">{t('{n} hidden by the filters', { n: laneHidden })}</span>{/if}
          </div>
        </div>
        <div class="lane-body body" role="list">
          {@render laneList(laneShown, 'sprint', lane.length === 0 ? t('Still empty. Drag {items} here.', { items: itemWord(d) }) : t('All tickets of the sprint are hidden by the filters.'))}
        </div>
      </div>
    </div>
    <p class="small muted hint">{t('Drag, or use the buttons; Alt+arrow left or right moves between the lanes. A click on the key opens the details.')}</p>
  {/if}

  <div class="grid cols-2 gapb" id="live" data-tour="plan-live">
    {#if d.multiProduct}
      <div class="card">
        <h2>{t('Product against budget')}</h2>
        <div class="tw">
          <table class="t">
            <thead><tr><th>{t('Product')}</th><th class="num">{t('Budget')}</th><th class="num">{noT ? t('Amount') : itemWord(d)}</th><th class="num">{t('Difference')}</th></tr></thead>
            <tbody>
              {#each productRows as r (r.p.id)}
                <tr>
                  <td>{r.p.name}</td><td class="num">{fmtVal(r.budget)}</td><td class="num">{fmtVal(r.usedP)}</td>
                  <td class="num">{#if r.diff > 0}<span class="chip warn">+{fmtVal(r.diff)}</span>{:else if r.diff < 0}<span class="muted">{signed(r.diff)} {t('free')}</span>{:else}<span class="chip ok">{t('fits')}</span>{/if}</td>
                </tr>
              {/each}
              <tr class="sum"><td>{t('Total')}</td><td class="num">{fmtVal(productRows.reduce((a, r) => a + r.budget, 0))}</td><td class="num">{fmtVal(productRows.reduce((a, r) => a + r.usedP, 0))}</td><td></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    {/if}
    <div class="card">
      <h2>{t('Project against contingent')} <span class="chip">{t('estimate')}</span></h2>
      {#if projectRows.length}
        <div class="tw">
          <table class="t">
            <thead><tr><th>{t('Project')}</th><th class="num">{unitName(d)}</th><th class="num">{t('PD')}</th><th class="num">{t('Rest')}</th><th></th></tr></thead>
            <tbody>
              {#each projectRows as r (r.p.id)}
                <tr>
                  <td>{r.p.name}</td><td class="num">{fmtVal(r.amount)}</td><td class="num">≈ {fmtVal(r.need)}</td><td class="num">{fmtVal(r.rest)}</td>
                  <td>
                    {#if r.rest != null && r.rest < 0}<span class="chip bad"><Icon name="cancel" size={14} />{t('{n} PD over contingent', { n: fmtVal(Math.max(-r.rest, 0.1)) })}</span>{:else if r.rest != null && r.p.bookedPD && r.rest < r.p.bookedPD * 0.15}<span class="chip warn"><Icon name="error" size={14} />{t('tight, rest {n} PD', { n: fmtVal(r.rest) })}</span>{:else if r.rest != null}<span class="chip ok"><Icon name="check_circle" size={14} />{t('on plan, rest {n} PD', { n: fmtVal(r.rest) })}</span>{/if}
                    <Calc label={r.p.name} topic="units"><div class="data">{fmtVal(r.amount)} ÷ {fmtRate(d.rate)} = {fmtVal(r.need)} {t('PD')}</div></Calc>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <p class="muted">{noT ? t('No project amounts in the sprint.') : t('No project tickets in the sprint.')}</p>
      {/if}
      <p class="small muted">{t('Daily business without a project: {n} {unit}. Conversion with the rate {rate} per PD.', { n: fmtVal(noT ? 0 : sizeSum(lane.filter((x) => !x.project))), unit: unitName(d), rate: fmtRate(d.rate) })}</p>
    </div>
  </div>

  <Production {d} {model} readonly={frozen} />

  {#if !noT && d.source === 'tracker'}
    <div class="card gapb" id="adjust" data-tour="plan-jira">
      <h2>{t('Adjust in {tracker}', { tracker: d.trackerName || t('the tracker') })}</h2>
      {#if adjust.length}
        <p class="small muted">{t('These tickets are still in the {tracker} sprint but were taken out here. The tracker ticket stays unchanged; the list goes into the planning minutes.', { tracker: d.trackerName || t('the tracker') })}</p>
        {#each adjust as x (x.key)}
          <div class="row line">
            <span class="data">{x.key}</span><span class="grow">{x.title}</span>
            <button class="btn" type="button" onclick={() => move(x.key, 'sprint')}><Icon name="undo" />{t('Back into the sprint')}</button>
          </div>
        {/each}
      {:else}
        <p class="muted small">{t('Nothing to adjust: the tracker and the plan agree.')}</p>
      {/if}
    </div>
    {#if d.writeBack}<WriteBack {d} />{/if}
  {/if}
{:else if model.loading}
  <p class="muted">{t('Loading …')}</p>
{:else}
  <div class="banner info"><Icon name="info" /><div class="grow">{t('Choose a team and a sprint first.')}</div></div>
{/if}

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') ctx = null; }} onscroll={() => (ctx = null)} onresize={() => (ctx = null)} />

{#if ctx && d && !frozen}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="ctx-backdrop" onclick={() => (ctx = null)} oncontextmenu={(e) => { e.preventDefault(); ctx = null; }}></div>
  <div class="ctx" role="menu" aria-label={t('Move to')} style:left={`${ctx.x}px`} style:top={`${ctx.y}px`}>
    <div class="ctx-title">{t('Move to')}</div>
    <button class="ctx-item" type="button" role="menuitem" disabled={ctxIn === 'sprint'} onclick={() => ctxMove('sprint')}>
      <span class="data">{t('Sprint {sprint}', { sprint: d.sprint })}</span>
    </button>
    <button class="ctx-item" type="button" role="menuitem" disabled={ctxIn === 'candidates'} onclick={() => ctxMove('candidates')}>{t('Candidates')}</button>
    <button class="ctx-item" type="button" role="menuitem" disabled={!canReorder} onclick={() => ctxEdge(true)}>{t('Top of the list')}</button>
    <button class="ctx-item" type="button" role="menuitem" disabled={!canReorder} onclick={() => ctxEdge(false)}>{t('Bottom of the list')}</button>
  </div>
{/if}

{#snippet laneList(list: PlanTicket[], here: 'sprint' | 'candidates', empty: string)}
  {#if list.length === 0 && !laneDrop(here)}
    <div class="small muted pad">{empty}</div>
  {:else if ui.group === 'none'}
    {#each list as x (x.key)}{@render laneRow(x, here)}{/each}
  {:else}
    {#each sections(list) as g (g.id)}
      <div class="gh small">
        <Icon name={g.kind === 'product' ? 'inventory_2' : g.id ? 'flag' : 'inventory_2'} size={14} />
        <strong>{g.name || (g.kind === 'project' ? t('Daily business') : t('No product'))}</strong>
        <span class="muted data">{fmtVal(sizeSum(g.items))} {unitName(d!)}, {g.items.length}</span>
      </div>
      {#each g.items as x (x.key)}{@render laneRow(x, here)}{/each}
    {/each}
  {/if}
  {#if laneDrop(here)}<DropGap height={dragHeight} />{/if}
{/snippet}

{#snippet laneRow(x: PlanTicket, here: 'sprint' | 'candidates')}
  {#if d}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="slot"
      class:dragging={dragKey === x.key}
      ondragenter={(e) => { if (!frozen && dragKey) e.preventDefault(); }}
      ondragover={(e) => rowOver(e, x.key, here)}
            ondrop={(e) => rowDrop(e, x.key, here)}
      oncontextmenu={(e) => openMenu(e, x.key)}
    >
      {#if overRow?.key === x.key && !overRow.after}<DropGap height={dragHeight} />{/if}
      <TicketRow
        ticket={x}
        {d}
        drag={!frozen}
        moveLabel={here === 'sprint' ? t('Take out of the sprint') : t('Take into the sprint')}
        moveIcon={here === 'sprint' ? 'arrow_back' : 'arrow_forward'}
        onmove={frozen ? undefined : () => move(x.key, here === 'sprint' ? 'candidates' : 'sprint')}
        ondragstart={(e) => dragStart(e, x.key)}
        ondragend={dragEnd}
      />
      {#if overRow?.key === x.key && overRow.after}<DropGap height={dragHeight} />{/if}
    </div>
  {/if}
{/snippet}

<style>
  .ctx-backdrop { position: fixed; inset: 0; z-index: 50; }
  .ctx {
    position: fixed;
    z-index: 51;
    width: 250px;
    padding: 4px 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  }
  .ctx-title { padding: 6px 12px; font-weight: 600; }
  .ctx-item {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 6px 12px;
    background: none;
    border: 0;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .ctx-item:hover:not(:disabled),
  .ctx-item:focus-visible { background: var(--surface-2); }
  .ctx-item:disabled { opacity: 0.45; cursor: default; }
  .cand-filter { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .gh { display: flex; gap: 8px; align-items: center; padding: 6px 12px; background: var(--surface-2); border-bottom: 1px solid var(--border); }
  .filters { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
  .gapb {
    margin-bottom: 16px;
  }
  .gap {
    margin-top: 8px;
  }
  .mode {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin: 0 0 12px;
  }
  .body {
    max-height: 460px;
    overflow: auto;
  }
  .pad {
    padding: 12px;
  }
  .hint {
    margin: -8px 0 16px;
  }
  .bar {
    flex: 1;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .line {
    border-top: 1px solid var(--border);
    padding: 6px 0;
  }
  #commit {
    width: 120px;
  }
</style>
