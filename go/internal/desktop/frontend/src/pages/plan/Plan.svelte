<script lang="ts">
  // Plan (flows.md F4, decisions 6, 7, 10): with tickets two lanes, candidates left and sprint
  // right, filled from the earmarks; the team moves tickets until the sum, the products and the
  // projects fit, then freezes the agreement (ticket list, commitment, minutes). Without tickets
  // the team agrees on an amount per product and a commitment. Moving works by drag, by the
  // buttons and by Alt+arrow; nothing is locked before the agreement.
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { assumptions, fmt, itemWord, parseAmount, PlanModel, signed, touched, unitName } from '../../lib/plan/model.svelte';
  import Production from '../../lib/plan/Production.svelte';
  import SprintHead from '../../lib/plan/SprintHead.svelte';
  import Summary from '../../lib/plan/Summary.svelte';
  import TicketRow from '../../lib/plan/TicketRow.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { PlanTicket } from '../../lib/types.plan';
  import CapacityBar from '../../lib/ui/CapacityBar.svelte';

  let { params }: PageProps = $props();
  void params;

  const model = new PlanModel();
  /** Tickets the tracker still has in the sprint that the team took out. */
  let removed = $state<string[]>([]);
  /** Amounts and commitment without tickets, typed during the planning. */
  let amounts = $state<Record<string, number>>({});
  let commit = $state<number | null>(null);
  let over = $state(false);
  let overWhich = $state('');

  $effect(() => {
    void app.team;
    void app.sprint;
    removed = [];
    amounts = {};
    commit = null;
    model.loading = true;
    void model.reload();
  });

  const d = $derived(model.data);
  const noT = $derived(d?.source === 'none');
  const frozen = $derived(!!d?.frozen);
  const lane = $derived<PlanTicket[]>(d ? d.tickets.filter((x) => !removed.includes(x.key)) : []);
  const candidates = $derived<PlanTicket[]>(d ? [...d.tickets.filter((x) => removed.includes(x.key)), ...d.candidates] : []);
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
      ? d.tickets.filter((x) => x.inTracker === d.sprint && removed.includes(x.key))
      : [],
  );

  // --- Moving -----------------------------------------------------------------------------
  async function move(key: string, to: 'sprint' | 'candidates'): Promise<void> {
    if (!d || frozen) return;
    const x = [...d.tickets, ...d.candidates].find((q) => q.key === key);
    if (!x) return;
    const wasRemoved = removed.includes(key);
    const earmark = x.sprint;
    if (to === 'sprint') {
      removed = removed.filter((k) => k !== key);
      await model.change(() => api.SetEarmark(app.team, key, d.sprint));
    } else {
      if (x.inTracker === d.sprint) removed = [...removed, key];
      await model.change(() => api.SetEarmark(app.team, key, ''));
    }
    toast(to === 'sprint' ? t('{key} taken into the sprint.', { key }) : t('{key} taken out of the sprint.', { key }), 'info', {
      label: t('Undo'),
      run: () => {
        removed = wasRemoved ? [...removed.filter((k) => k !== key), key] : removed.filter((k) => k !== key);
        void model.change(() => api.SetEarmark(app.team, key, earmark));
      },
    });
  }

  let dragKey = '';
  function dragStart(e: DragEvent, key: string): void {
    dragKey = key;
    e.dataTransfer?.setData('text/plain', key);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  function drop(to: 'sprint' | 'candidates'): void {
    over = false;
    if (dragKey) void move(dragKey, to);
    dragKey = '';
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

  // --- Freezing -----------------------------------------------------------------------------
  async function freeze(): Promise<void> {
    if (!d) return;
    const ok = await model.change(async () => {
      const file = await api.FreezePlan(app.team, d.sprint, {
        tickets: lane.map((x) => x.key),
        commitment: noT ? commit : null,
        amounts: noT ? Object.fromEntries(d.products.filter((p) => p.active).map((p) => [p.id, amountOf(p.id, p.pre, p.default)])) : {},
        removed: adjust.map((x) => x.key),
      });
      toast(t('Plan {sprint} frozen. Planning minutes written: {file}', { sprint: d.sprint, file }), 'ok');
    });
    if (ok) removed = [];
  }
  const reopen = () =>
    model.change(() => api.ReopenPlan(app.team, d!.sprint), t('Plan opened again. The next freeze marks the old minutes as obsolete.'));
  const setAmount = (id: string, text: string) => {
    const v = parseAmount(text);
    if (v != null) amounts[id] = v;
  };
  const setCommit = (text: string) => {
    const v = parseAmount(text);
    if (v !== undefined) commit = v;
  };
</script>

{#if model.error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{model.error}</div></div>
{:else if d}
  <SprintHead {d} stage="plan">
    {#snippet actions()}
      {#if !noT}
        <a class="btn" href="#/present" id="present"><Icon name="fit_screen" />{t('Presentation view')}</a>
      {/if}
      <button class="btn primary" type="button" id="freeze" disabled={frozen || d.stage === 'past' || d.stage === 'current'} onclick={freeze}>
        <Icon name="lock" />{t('Record the agreement and freeze')}
      </button>
    {/snippet}
  </SprintHead>

  <Summary {d} used={used} commitment={frozen ? d.committed : null} count={lane.length} assumption={touched(assumptions.active) ? assumptions.active?.label : ''} whatIf={model.running} />

  {#if d.absences !== 'confirmed'}
    <div class="banner warn">
      <Icon name="event_busy" />
      <div class="grow">
        <strong>{t('Absences for {sprint} are not confirmed yet.', { sprint: d.sprint })}</strong>
        {t('Capacity and Forecast PLAN can still change. This blocks nothing.')}
        <div class="row gap"><a class="btn" href="#/sprint/prepare">{t('Confirm in Prepare')}</a></div>
      </div>
    </div>
  {/if}

  {#if d.frozen}
    <div class="banner info" id="frozen">
      <Icon name="lock" />
      <div class="grow">
        {noT ? t('Frozen: commitment') : t('Frozen: {n} {items}, commitment', { n: d.frozen.tickets, items: itemWord(d) })}
        <span class="data">{fmt(d.frozen.commitment)}</span> {unitName(d)}. {t('The planning minutes are written.')}
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
                  <td class="num">{fmt(r.p.pre)}</td>
                  <td class="num edit"><input inputmode="decimal" value={r.usedP} disabled={frozen} aria-label={t('Amount {product}', { product: r.p.name })} onchange={(e) => setAmount(r.p.id, e.currentTarget.value)} /></td>
                </tr>
              {/each}
              <tr class="sum"><td>{t('Sum')}</td><td class="num">{fmt(d.preplanned)}</td><td class="num">{fmt(amountSum)}</td></tr>
            </tbody>
          </table>
        </div>
      {/if}
      <div class="row gap">
        <div class="field">
          <label for="commit">{t('Commitment in {unit}', { unit: unitName(d) })}</label>
          <input id="commit" class="input data num" inputmode="decimal" value={commitment} disabled={frozen} onchange={(e) => setCommit(e.currentTarget.value)} />
        </div>
        <div class="bar">
          <CapacityBar used={commitment} plan={d.plan} low={d.low} high={d.high} unit={unitName(d)} />
          <span class="small muted">{t('Commitment against Forecast PLAN {plan} (range {low} to {high})', { plan: fmt(d.plan), low: fmt(d.low), high: fmt(d.high) })}</span>
        </div>
      </div>
    </div>
  {:else}
    <div id="lanes" class="grid cols-2 gapb">
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="lane"
        class:over={over && overWhich === 'candidates'}
        role="group"
        aria-label={t('Candidates')}
        ondragover={(e) => { if (!frozen) { e.preventDefault(); over = true; overWhich = 'candidates'; } }}
        ondragleave={() => (over = false)}
        ondrop={(e) => { e.preventDefault(); drop('candidates'); }}
        onkeydown={(e) => laneKey(e, 'candidates')}
      >
        <div class="lane-head">
          <div class="row"><strong class="grow">{t('Candidates')}</strong><span class="small muted data">{candidates.length} {itemWord(d)} · {fmt(sizeSum(candidates), 1)} {unitName(d)}</span></div>
          <span class="small muted">{t('Backlog and earmarked for later sprints')}</span>
        </div>
        <div class="lane-body body" role="list">
          {#each candidates as x (x.key)}
            <TicketRow ticket={x} {d} drag={!frozen} moveLabel={t('Take into the sprint')} moveIcon="arrow_forward" onmove={frozen ? undefined : () => move(x.key, 'sprint')} ondragstart={(e) => dragStart(e, x.key)} />
          {:else}
            <div class="small muted pad">{t('No candidates left.')}</div>
          {/each}
        </div>
      </div>

      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="lane"
        class:over={over && overWhich === 'sprint'}
        role="group"
        aria-label={t('Sprint {sprint}', { sprint: d.sprint })}
        ondragover={(e) => { if (!frozen) { e.preventDefault(); over = true; overWhich = 'sprint'; } }}
        ondragleave={() => (over = false)}
        ondrop={(e) => { e.preventDefault(); drop('sprint'); }}
        onkeydown={(e) => laneKey(e, 'sprint')}
      >
        <div class="lane-head">
          <div class="row">
            <strong class="grow">{t('Sprint {sprint}', { sprint: d.sprint })}</strong>
            <span class="data"><strong>{fmt(laneSum, 1)}</strong> {t('of')} {fmt(d.plan)} <span class="muted small">({fmt(d.low)} – {fmt(d.high)})</span></span>
          </div>
          <CapacityBar used={laneSum} plan={d.plan} low={d.low} high={d.high} unit={unitName(d)} />
          <div class="row small">
            {#if d.high != null && laneSum > d.high}<span class="chip bad">{t('{n} over the range', { n: fmt(laneSum - d.high, 1) })}</span>
            {:else if d.low != null && laneSum < d.low}<span class="chip fc">{t('{n} to the range', { n: fmt(d.low - laneSum, 1) })}</span>
            {:else}<span class="chip ok">{t('within the range')}</span>{/if}
            {#if unrefined}<span class="chip warn">{t('{n} not refined', { n: unrefined })}</span>{/if}
            {#if noEstimate}<span class="chip warn">{t('{n} without estimate (count 0)', { n: noEstimate })}</span>{/if}
          </div>
        </div>
        <div class="lane-body body" role="list">
          {#each lane as x (x.key)}
            <TicketRow ticket={x} {d} drag={!frozen} moveLabel={t('Take out of the sprint')} moveIcon="arrow_back" onmove={frozen ? undefined : () => move(x.key, 'candidates')} ondragstart={(e) => dragStart(e, x.key)} />
          {:else}
            <div class="small muted pad">{t('Still empty. Drag {items} here.', { items: itemWord(d) })}</div>
          {/each}
        </div>
      </div>
    </div>
    <p class="small muted hint">{t('Drag, or use the buttons; Alt+arrow left or right moves between the lanes. A click on the key opens the details.')}</p>
  {/if}

  <div class="grid cols-2 gapb" id="live">
    {#if d.multiProduct}
      <div class="card">
        <h2>{t('Product against budget')}</h2>
        <div class="tw">
          <table class="t">
            <thead><tr><th>{t('Product')}</th><th class="num">{t('Budget')}</th><th class="num">{noT ? t('Amount') : itemWord(d)}</th><th class="num">{t('Difference')}</th></tr></thead>
            <tbody>
              {#each productRows as r (r.p.id)}
                <tr>
                  <td>{r.p.name}</td><td class="num">{fmt(r.budget)}</td><td class="num">{fmt(r.usedP, 1)}</td>
                  <td class="num">{#if r.diff > 0}<span class="chip warn">+{fmt(r.diff, 1)}</span>{:else if r.diff < 0}<span class="muted">{signed(r.diff)} {t('free')}</span>{:else}<span class="chip ok">{t('fits')}</span>{/if}</td>
                </tr>
              {/each}
              <tr class="sum"><td>{t('Total')}</td><td class="num">{fmt(productRows.reduce((a, r) => a + r.budget, 0))}</td><td class="num">{fmt(productRows.reduce((a, r) => a + r.usedP, 0), 1)}</td><td></td></tr>
            </tbody>
          </table>
        </div>
        <p class="small muted">{t('Budget is the pre-planned amount. Deviations warn and lock nothing.')}</p>
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
                  <td>{r.p.name}</td><td class="num">{fmt(r.amount, 1)}</td><td class="num">≈ {fmt(r.need, 1)}</td><td class="num">{fmt(r.rest, 1)}</td>
                  <td>
                    {#if r.rest != null && r.rest < 0}<span class="chip bad">{t('over contingent')}</span>{:else if r.rest != null && r.p.bookedPD && r.rest < r.p.bookedPD * 0.15}<span class="chip warn">{t('tight')}</span>{:else if r.rest != null}<span class="chip ok">{t('on plan')}</span>{/if}
                    <Calc label={r.p.name} topic="projects"><div class="data">{fmt(r.amount, 1)} ÷ {fmt(d.rate, 2)} = {fmt(r.need, 1)} {t('PD')}</div></Calc>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <p class="muted">{noT ? t('No project amounts in the sprint.') : t('No project tickets in the sprint.')}</p>
      {/if}
      <p class="small muted">{t('Daily business without a project: {n} {unit}. Conversion with the rate {rate} per PD.', { n: fmt(noT ? 0 : sizeSum(lane.filter((x) => !x.project)), 1), unit: unitName(d), rate: fmt(d.rate, 2) })}</p>
    </div>
  </div>

  <Production {d} {model} readonly={frozen} />

  {#if !noT && d.source === 'tracker'}
    <div class="card gapb" id="adjust">
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
  {/if}
{:else if model.loading}
  <p class="muted">{t('Loading …')}</p>
{:else}
  <div class="banner info"><Icon name="info" /><div class="grow">{t('Choose a team and a sprint first.')}</div></div>
{/if}

<style>
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
