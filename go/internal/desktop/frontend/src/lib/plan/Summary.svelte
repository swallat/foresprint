<script lang="ts">
  // The figures of the sprint at the top of Pre-plan and Plan: capacity, Forecast PLAN,
  // plannable, planned (against the range), production and the contingents of projects.
  import { api } from '../api';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import type { PlanSprint, WhatIf } from '../types.plan';
  import CapacityBar from '../ui/CapacityBar.svelte';
  import Calc from '../calc/Calc.svelte';
  import { fmt, fmtCap, fmtRate, itemWord, other, parseAmount, unitName, type PlanModel, fmtVal } from './model.svelte';

  interface Props {
    d: PlanSprint;
    /** What is planned so far, in the unit of the team. */
    used: number;
    /** The commitment, if the plan is frozen or a number was entered. */
    commitment?: number | null;
    /** The active assumption about the running sprint, if it changes anything. */
    assumption?: string;
    whatIf?: WhatIf | null;
    /** Number of tickets in the sprint, if the page changes the lane locally. */
    count?: number;
    /** The model of the page; with it a team without history can enter a start rate here. */
    model?: PlanModel;
  }
  let { d, used, commitment = null, assumption = '', whatIf = null, count, model }: Props = $props();
  const fromStart = $derived(d.planSource === 'start');
  const askStart = $derived(model != null && d.plan == null && d.capacity != null && !d.startRate);
  async function setStart(text: string): Promise<void> {
    const v = parseAmount(text);
    if (v === undefined || v === null || !model) return;
    await model.change(() => api.SetStartRate(app.team, v), t('Start rate saved.'));
  }
  const n = $derived(count ?? d.tickets.length);

  const stateName = (s: string) => ({ confirmed: t('confirmed'), announced: t('announced'), unknown: t('unknown') })[s] ?? s;
  const ratio = $derived(d.plan != null && d.capacity ? d.plan / d.capacity : null);
  const unit = $derived(unitName(d));
  const split = $derived(d.split);
  const free = $derived(split ? split.plannable : null);
  const smallStuff = $derived(split ? split.smallStuff : null);
  const prod = $derived(d.prod);
  const freeLeft = $derived(free == null ? null : free - used);
  const prodNote = $derived(
    prod && prod.status !== 'ok'
      ? prod.status === 'over'
        ? t('{n} PD too much', { n: fmtVal(prod.demand - prod.available) })
        : t('tight')
      : t('fits'),
  );
</script>

<div class="card sum" data-tour="plan-sumbar">
  <div class="tile">
    <h2>{t('Capacity')}</h2>
    <div class="row">
      <span class="big">{d.capacity == null ? '–' : fmtCap(d.capacity)} {t('PD')}</span>
      <Calc label={t('Capacity')} topic="capacity">
        <div>{t('Person days after calendar, FTE and overhead, minus absences.')}</div>
        <div class="data">{fmtCap(d.capacity)} {t('PD')}</div>
      </Calc>
    </div>
    <div class="small muted">
      {#if d.absenceDays}{t('{n} PD absence ({state})', { n: fmtCap(d.absenceDays), state: stateName(d.absences) })}{:else}{t('no absence entered')}{/if}
    </div>
    {#if prod}
      <div class="small muted">{t('with production access about {n} PD', { n: fmtCap(prod.time) })}</div>
    {/if}
  </div>

  <div class="tile">
    <h2>
      {t('Forecast PLAN')}
      {#if assumption}<span class="chip">{t('with assumption {label}', { label: assumption })}</span>{/if}
      {#if fromStart}<span class="chip warn">{t('start rate')}</span>{/if}
    </h2>
    <div class="row">
      <span class="big fc">{fmt(d.plan)} {unit}</span>
      <Calc label={t('Forecast PLAN')} topic="forecast">
        <div>{t('Capacity times the rate (trend of the normalized velocity).')}</div>
        {#if fromStart}
          <div>{t('No finished sprint yet: capacity times the start rate of the team. The history takes over once three sprints have a velocity.')}</div>
        {/if}
        <div class="data">{fmtCap(d.capacity)} {t('PD')} × {fmtRate(fromStart ? d.startRate : (d.trendRate ?? ratio))} = {fmt(d.plan)}</div>
      </Calc>
    </div>
    <div class="small muted">
      {#if d.low != null && d.high != null}
        {t('range')} <span class="data">{fmt(d.low)} – {fmt(d.high)}</span>
        {#if assumption && whatIf?.planOriginal != null}· {t('without assumption')} <span class="data">{fmt(whatIf.planOriginal)}</span>{/if}
      {:else if fromStart}
        {t('Estimate from the start rate {rate}, no range yet', { rate: fmtRate(d.startRate) })}
      {:else if askStart}
        <label class="start">
          {t('Start rate per PD')}
          <input
            class="input data num"
            inputmode="decimal"
            placeholder="0,7"
            aria-label={t('Start rate per PD')}
            onchange={(e) => setStart(e.currentTarget.value)}
          />
        </label>
        <span class="muted">{t('Expected amount per capacity PD until three sprints are finished, e.g. 0,7.')}</span>
      {:else}
        {t('range follows with more finished sprints')}
      {/if}
    </div>
  </div>

  {#if free != null}
    <div class="tile">
      <h2>{t('Plannable')}</h2>
      <div class="row">
        <span class="big">{fmt(free)} {unit}</span>
        <Calc label={t('Plannable')} topic="plannable">
          <div>{t('(Forecast PLAN − carried-over rest) × plannable share, rounded down.')}</div>
          <div class="data">({fmt(split?.plan)} − {fmt(split?.carryIn)}) × {fmt(d.share * 100, 1)} % = {fmt(free)}</div>
        </Calc>
      </div>
      <div class="small muted">
        {#if other(d, free) != null}≈ <span class="data">{fmt(other(d, free))}</span> {t('PD')} ·{' '}{/if}{t('small stuff')}
        <span class="data">{fmt(smallStuff)}</span>
      </div>
      {#if split?.carryIn}
        <div class="small muted">{t('carry-over')} <span class="data">{fmt(split.carryIn)}</span></div>
      {/if}
      {#if split?.overbooked}<div class="small"><span class="chip warn">{t('carry-over above the PLAN')}</span></div>{/if}
    </div>
  {/if}

  <div class="tile grow">
    <h2>{d.source === 'none' ? t('Pre-planned') : t('Planned')}</h2>
    <div class="row"><span class="big">{fmtVal(used)} {unit}</span></div>
    <CapacityBar {used} plan={d.plan} low={d.low} high={d.high} {unit} />
    <div class="small muted">
      {#if freeLeft != null}
        {#if freeLeft >= 0}{t('still free')} <span class="data">{fmt(freeLeft)}</span>{:else}<span class="data">{fmt(-freeLeft)}</span> {t('over plannable')}{/if}
        ·
      {/if}
      {#if d.source !== 'none' && d.preplanned > 0}{t('pre-planned')} <span class="data">{fmtVal(d.preplanned)}</span> · {/if}
      {#if commitment != null}{t('commitment')} <span class="data">{fmtVal(commitment)}</span> · {/if}
      {d.source === 'none' ? t('sum of the amounts per product') : `${n} ${itemWord(d, n !== 1)}`}
    </div>
    {#if d.high != null && used > d.high}<div class="small"><span class="chip bad">{t('above the range')}</span></div>{/if}
  </div>

  {#if prod}
    <div class="tile">
      <h2>{t('Production')}</h2>
      <div class="row">
        <span class="big">{prod.demandSet ? fmtVal(prod.demand) : '–'} {t('of')} {fmtCap(prod.available)} {t('PD')}</span>
        <Calc label={t('Production')} topic="units">
          {#if prod.scaled}
            <div>{t('The plannable amount times the share of the capacity that has production access, times the cap.')}</div>
            <div class="data">{fmtCap(prod.time)} ÷ {fmtCap(d.capacity)} {t('PD')} = {fmt(prod.share * 100, 1)} %</div>
            <div class="data">{fmtCap(prod.basis)} {t('PD')} × {fmt(prod.share * 100, 1)} % × {fmt(prod.capPercent, 1)} % = {fmtCap(prod.available)} {t('PD')}</div>
          {:else}
            <div>{t('Time of the people with production access, after absences, times the cap.')}</div>
            <div class="data">{fmtCap(prod.time)} {t('PD')} × {fmt(prod.capPercent, 1)} % = {fmtCap(prod.available)} {t('PD')}</div>
          {/if}
        </Calc>
      </div>
      <div class="small row">
        {#if prod.demandSet}
          <span class="chip {prod.status === 'over' ? 'bad' : prod.status === 'tight' ? 'warn' : 'ok'}">{prodNote}</span>
        {:else}
          <span class="chip">{t('no value yet')}</span>
        {/if}
        <span class="muted">{t('{n} people with access', { n: prod.people.length })}</span>
      </div>
    </div>
  {/if}

  {#if d.projects.length}
    <div class="tile">
      <h2>{t('Contingents per project')} <span class="chip">{t('estimate')}</span></h2>
      <div class="projs">
        {#each d.projects as p (p.id)}
          <span class="chip"><span class="name">{p.name}</span></span>
          <span class="data small">{p.needPD == null ? '–' : `≈ ${fmtVal(p.needPD)} ${t('PD')}`}</span>
          <span class="small muted">{p.bookedPD == null ? t('no contingent') : p.usedPD == null ? t('of {n} PD booked', { n: fmtVal(p.bookedPD) }) : t('of {n} PD booked, {u} used', { n: fmtVal(p.bookedPD), u: fmtVal(p.usedPD) })}</span>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .sum {
    display: flex;
    flex-wrap: wrap;
    gap: 16px 24px;
    margin-bottom: 16px;
  }
  .tile {
    flex: 1 1 190px;
    min-width: 0;
  }
  .tile.grow {
    flex: 2 1 260px;
  }
  .tile h2 {
    margin: 0 0 4px;
    font: 600 12px/16px var(--font-ui);
    color: var(--text-muted);
  }
  .start {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }
  .start .input {
    width: 80px;
  }
  .big {
    font: 600 22px/28px var(--font-data);
  }
  .big.fc {
    color: var(--forecast);
  }
  .projs {
    display: grid;
    grid-template-columns: minmax(0, max-content) auto auto;
    gap: 6px 8px;
    align-items: center;
    margin-top: 4px;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
