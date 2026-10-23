<script lang="ts">
  // What-if for the running sprint (flows.md decision 14): which tickets will finish, which
  // carry over with how much rest and where they continue. The expected velocity joins the rate
  // history and changes the Forecast PLAN of the next sprint; carried-over rest lowers what is
  // plannable there. Several assumptions (A, B, ...) are kept side by side; none is final
  // before the review.
  import { api } from '../../lib/api';
  import { app, openTicket, selectSprint, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { assumptions, fmt, itemWord, parseAmount, touched, type PlanModel } from '../../lib/plan/model.svelte';
  import type { Assumption, CarryInput, PlanSprint, RunningHint, RunningTicket, WhatIf } from '../../lib/types.plan';

  interface Props {
    d: PlanSprint;
    model: PlanModel;
  }
  let { d, model }: Props = $props();

  let tickets = $state<RunningTicket[]>([]);
  let hint = $state<RunningHint | null>(null);
  $effect(() => {
    const team = app.team;
    const sprint = d.sprint;
    if (d.running && d.source !== 'none') {
      api.RunningTickets(team, sprint).then((l) => (tickets = l), () => (tickets = []));
      api.RunningHint(team, sprint).then((h) => (hint = h), () => (hint = null));
    } else {
      tickets = [];
      hint = null;
    }
  });

  const a = $derived(assumptions.active);
  const r = $derived(model.running);
  const noT = $derived(d.source === 'none');
  const planned = $derived(tickets.filter((x) => !x.added));
  const added = $derived(tickets.filter((x) => x.added));
  const carried = (key: string): CarryInput | undefined => a?.carry.find((c) => c.ticket === key);
  const restOf = (x: RunningTicket) => x.remaining ?? x.size ?? 0;
  const targets = $derived.by(() => {
    const i = app.sprints.findIndex((s) => s.id === d.sprint);
    const later = app.sprints.slice(i + 1, i + 3).map((s) => ({ value: s.id, label: s.id }));
    return [{ value: '', label: d.sprint }, ...later, { value: 'backlog', label: t('Backlog') }];
  });
  const fromTracker = (x: RunningTicket) => d.source === 'tracker' && x.remaining != null && x.remaining !== x.size;

  function setCarry(x: RunningTicket, on: boolean): void {
    if (!a) return;
    if (on) a.carry.push({ ticket: x.key, rest: restOf(x), target: '' });
    else a.carry = a.carry.filter((c) => c.ticket !== x.key);
    void model.reload();
  }
  function setRest(x: RunningTicket, text: string): void {
    const c = carried(x.key);
    const v = parseAmount(text);
    if (!c || v == null) return void model.reload();
    c.rest = Math.min(v, x.size ?? v);
    void model.reload();
  }
  function setTarget(x: RunningTicket, value: string): void {
    const c = carried(x.key);
    if (c) c.target = value;
    void model.reload();
  }
  function setNumber(field: 'commitment' | 'notDone' | 'extra' | 'restNext', text: string): void {
    const v = parseAmount(text);
    if (!a || v === undefined) return void model.reload();
    a[field] = v;
    void model.reload();
  }
  function addAssumption(): void {
    assumptions.add();
    toast(t('Assumption {label} created as a copy of {from}.', { label: assumptions.active?.label ?? '', from: assumptions.list[assumptions.index - 1]?.label ?? '' }));
    void model.reload();
  }
  async function save(): Promise<void> {
    if (!a) return;
    await model.change(
      () => api.SaveAssumption(app.team, d.sprint, $state.snapshot(a) as Assumption),
      t('Assumption {label} saved as a prognosis. The review of {sprint} compares it with the result.', { label: a.label, sprint: d.running }),
    );
  }
  const nextId = $derived.by(() => {
    const i = app.sprints.findIndex((s) => s.id === d.sprint);
    return i >= 0 ? (app.sprints[i + 1]?.id ?? '') : '';
  });
  const delta = $derived(r && r.plan != null && r.planOriginal != null ? r.plan - r.planOriginal : 0);
  const carriedCount = $derived(a?.carry.length ?? 0);
</script>

{#if !d.running && d.stage === 'current' && nextId}
  <div class="banner info" id="whatif-next">
    <Icon name="info" />
    <div class="grow">
      {t('{sprint} is running. The what-if analysis (what will probably be finished here, and so how much fits into the next sprint) is on the pre-planning of {next}.', { sprint: d.sprint, next: nextId })}
    </div>
    <button type="button" class="btn" onclick={() => selectSprint(nextId)}><Icon name="arrow_forward" />{t('Open pre-planning of {next}', { next: nextId })}</button>
  </div>
{/if}

{#if d.running}
  <section class="card whatif" id="whatif" data-tour="preplan-whatif">
    <div class="row head">
      <h2>{t('What if: running sprint {sprint}', { sprint: d.running })}</h2>
      <span class="chip">{t('Assumption, final only in the review')}</span>
    </div>
    <p class="small muted lead">
      {t('What will probably be finished in {sprint}?', { sprint: d.running })}
      {noT
        ? t('Enter what the team expects. What is not finished is missing in full from the velocity; only the rest you enter for {next} occupies {next}.', { next: d.sprint })
        : t('Mark {items} the team will not finish and estimate their rest. Unfinished ones are missing in full from the velocity, their rest continues where you choose or goes back to the backlog; only rest in {next} occupies {next}.', { items: itemWord(d), next: d.sprint })}
      {t('You enter the real values in the review of {sprint}.', { sprint: d.running })}
    </p>

    <div class="row sets" role="group" aria-label={t('Assumptions')}>
      {#each assumptions.list as x, i (x.label)}
        <button type="button" class="chip filter" class:on={i === assumptions.index} aria-pressed={i === assumptions.index} onclick={() => { assumptions.select(i); void model.reload(); }}>
          {t('Assumption {label}', { label: x.label })}
        </button>
      {/each}
      <button type="button" class="chip filter" onclick={addAssumption} title={t('Copies the active assumption')}>
        <Icon name="add" size={14} />{t('Assumption')}
      </button>
    </div>

    {#if a}
      {#if noT}
        <div class="row nums">
          {@render num('wi-commit', t('Commitment {sprint} ({unit})', { sprint: d.running, unit: t('points') }), r?.commitment ?? null, 'commitment', '')}
          {@render num('wi-nd', t('Expected not finished ({unit})', { unit: t('points') }), a.notDone, 'notDone', '0')}
          {@render num('wi-rest', t('of which rest in {sprint} ({unit})', { sprint: d.sprint, unit: t('points') }), a.restNext, 'restNext', fmt(a.notDone ?? 0), !a.notDone)}
          {@render num('wi-extra', t('Additionally finished ({unit})', { unit: t('points') }), a.extra, 'extra', '0')}
        </div>
      {:else if tickets.length === 0}
        <p class="muted small">{t('No {items} in the running sprint.', { items: itemWord(d) })}</p>
        {#if hint && hint.unresolved > 0}
          <div class="banner warn">
            <Icon name="warning" />
            <div class="grow">
              {t('{n} open {items} sit in tracker sprints that Foresprint cannot match to a sprint: {names}. Fetch again after naming them under Tickets and tracker, sprint names.', { n: hint.unresolved, items: itemWord(d, true), names: hint.names.join(', ') })}
              <a href="#/settings/tickets">{t('Open Tickets and tracker')}</a>
            </div>
          </div>
        {/if}
      {:else}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{itemWord(d, false)}</th>
                <th>{t('Status')}</th>
                <th class="num">{t('Size')}</th>
                <th>{t('Expectation')}</th>
                <th class="num">{t('Rest')}</th>
                <th>{t('Continues in')}</th>
              </tr>
            </thead>
            <tbody>
              {#each planned as x (x.key)}{@render trow(x)}{/each}
              {#if added.length}
                <tr class="sum"><td colspan="6"><Icon name="call_received" size={14} /> {t('Pulled in after the planning')} <span class="small muted">{t('(new in the sprint since freezing, not part of the commitment)')}</span></td></tr>
                {#each added as x (x.key)}{@render trow(x)}{/each}
              {/if}
            </tbody>
          </table>
        </div>
      {/if}

      {#if r}
        <div class="res">
          <div>
            <div class="small muted">{t('Expected velocity {sprint}', { sprint: d.running })}</div>
            <div class="data big">{fmt(r.velocity, 1)}</div>
            <div class="small muted">{fmt(r.commitment, 1)} − {fmt(r.notDone, 1)} {t('not finished')} + {fmt(r.extra, 1)} {noT ? t('additionally') : t('pulled in')}</div>
          </div>
          <div>
            <div class="small muted">{t('Forecast PLAN {sprint}', { sprint: d.sprint })}</div>
            <div class="data big">
              {#if touched(a, !noT)}{fmt(r.planOriginal)} <Icon name="arrow_forward" size={16} /> <span class="fc">{fmt(r.plan)}</span>{:else}<span class="fc">{fmt(r.plan)}</span>{/if}
            </div>
            <div class="small muted">
              {#if touched(a, !noT)}{delta > 0 ? '+' : ''}{fmt(delta)} · {/if}{#if r.low != null}{t('range')} {fmt(r.low)} – {fmt(r.high)}{:else}{t('unchanged')}{/if}
            </div>
          </div>
          <div>
            <div class="small muted">{t('Carry-over to {sprint} (rest)', { sprint: d.sprint })}</div>
            <div class="data big">{fmt(r.rest, 1)}</div>
            <div class="small muted">
              {#if r.later}<span class="data">{fmt(r.later, 1)}</span> {t('later or back to the backlog')}{:else if carriedCount}{t('{n} {items}', { n: carriedCount, items: itemWord(d) })}{:else}{noT ? t('points') : t('nothing marked')}{/if}
            </div>
          </div>
          <div>
            <div class="small muted">{t('Plannable in {sprint}', { sprint: d.sprint })}</div>
            <div class="data big">{fmt(r.plannable)}</div>
            <div class="small muted">{t('(PLAN − rest) × {pct} % · small stuff', { pct: fmt(d.share * 100) })} <span class="data">{fmt(r.smallStuff)}</span></div>
          </div>
        </div>
      {/if}

      <div class="row foot">
        <button class="btn" type="button" id="wi-save" disabled={!touched(a, !noT)} onclick={save}>
          <Icon name="bookmark_add" />{t('Save as prognosis')}
        </button>
        <button class="btn ghost" type="button" disabled={!touched(a, !noT)} onclick={() => { assumptions.reset(); void model.reload(); }}>
          {t('Clear assumption {label}', { label: a.label })}
        </button>
      </div>
    {/if}
  </section>
{/if}

{#snippet num(id: string, label: string, value: number | null, field: 'commitment' | 'notDone' | 'extra' | 'restNext', ph: string, disabled = false)}
  <div class="field">
    <label for={id}>{label}</label>
    <input {id} class="input data num" inputmode="decimal" value={value ?? ''} placeholder={ph} {disabled} onchange={(e) => setNumber(field, e.currentTarget.value)} />
  </div>
{/snippet}

{#snippet trow(x: RunningTicket)}
  {@const c = carried(x.key)}
  <tr>
    <td class="wrap">
      <button class="linkbtn data" type="button" onclick={() => openTicket(x.key)}>{x.key}</button> {x.title}
    </td>
    <td><span class="chip">{x.status}</span></td>
    <td class="num">{fmt(x.size, 1)}</td>
    <td>
      {#if x.done}
        <span class="chip ok"><Icon name="check" size={14} />{t('done')}</span>
      {:else}
        <div class="seg" role="group" aria-label={t('Expectation for {key}', { key: x.key })}>
          <button type="button" class="seg-b" class:on={!c} aria-pressed={!c} onclick={() => setCarry(x, false)}><Icon name="check" size={14} />{t('will finish')}</button>
          <button type="button" class="seg-b warn" class:on={!!c} aria-pressed={!!c} onclick={() => setCarry(x, true)}><Icon name="redo" size={14} />{t('carry-over')}</button>
        </div>
      {/if}
    </td>
    <td class="num">
      {#if c}
        <input class="input data num rest" inputmode="decimal" value={c.rest} aria-label={t('Rest of {key} in {unit}', { key: x.key, unit: t('points') })} onchange={(e) => setRest(x, e.currentTarget.value)} />
        {#if fromTracker(x) && c.rest === x.remaining}<div class="small muted">{t('from {tracker}', { tracker: d.trackerName || t('the tracker') })}</div>{/if}
      {:else}<span class="muted">–</span>{/if}
    </td>
    <td>
      {#if c}
        <select class="input to" aria-label={t('{key} continues in', { key: x.key })} onchange={(e) => setTarget(x, e.currentTarget.value)}>
          {#each targets as o (o.value)}<option value={o.value} selected={o.value === c.target}>{o.label}</option>{/each}
        </select>
      {:else}<span class="muted">–</span>{/if}
    </td>
  </tr>
{/snippet}

<style>
  .whatif {
    margin-bottom: 16px;
  }
  .head h2 {
    margin: 0;
    flex: 1;
  }
  .lead {
    margin: 4px 0 8px;
  }
  .sets {
    margin-bottom: 12px;
    gap: 6px;
  }
  .nums {
    gap: 16px;
    align-items: flex-end;
  }
  .nums :global(input) {
    width: 96px;
  }
  td.wrap {
    white-space: normal;
    min-width: 200px;
  }
  .rest {
    width: 64px;
    height: 28px;
  }
  .to {
    height: 28px;
    width: auto;
    min-width: 120px;
    max-width: 260px;
    padding-top: 0;
    padding-bottom: 0;
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--border-control);
    border-radius: var(--r-ctl);
    overflow: hidden;
  }
  .seg-b {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 0;
    background: var(--surface);
    color: var(--text-muted);
    padding: 3px 10px;
    font-size: 13px;
    cursor: pointer;
  }
  .seg-b + .seg-b {
    border-left: 1px solid var(--border-control);
  }
  .seg-b.on {
    background: var(--ok-weak);
    color: var(--ok);
    font-weight: 600;
  }
  .seg-b.on.warn {
    background: var(--warn-weak);
    color: var(--warn);
  }
  .res {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-top: 12px;
    padding: 12px;
    background: var(--surface-2);
    border-radius: var(--r-ctl);
  }
  .big {
    font-size: 20px;
    line-height: 28px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .fc {
    color: var(--forecast);
  }
  .foot {
    margin-top: 12px;
  }
</style>
