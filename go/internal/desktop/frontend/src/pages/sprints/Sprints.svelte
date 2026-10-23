<script lang="ts">
  // Sprint overview (flows.md section 5): every sprint on one line, with the state, absences,
  // capacity, Forecast PLAN, commitment, velocity and what it needs next. From here any stage of
  // any sprint opens; nothing is locked.
  import { api } from '../../lib/api';
  import { days } from '../../lib/absences/format';
  import { formatPeriod } from '../../lib/format';
  import { app, selectSprint } from '../../lib/app.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { IconName } from '../../lib/icons';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import type { NextStep, SprintOverview, SprintRow } from '../../lib/types.sprints';

  let { params }: PageProps = $props();
  void params;

  let data = $state<SprintOverview | undefined>();
  let error = $state('');
  let all = $state(false);

  let seq = 0;
  async function load() {
    if (!app.team) return;
    const mine = ++seq;
    try {
      const next = await api.SprintOverview(app.team, all ? -1 : 6);
      if (mine !== seq) return;
      data = next;
      error = '';
    } catch (e) {
      if (mine === seq) error = String(e);
    }
  }

  $effect(() => {
    void [app.team, all];
    void load();
  });

  const stages: { to: string; icon: IconName; label: string }[] = [
    { to: '/sprint/prepare', icon: 'event_available', label: 'Prepare' },
    { to: '/sprint/preplan', icon: 'low_priority', label: 'Pre-plan' },
    { to: '/sprint/plan', icon: 'checklist', label: 'Plan' },
    { to: '/sprint/review', icon: 'task_alt', label: 'Review' },
    { to: '/sprint/minutes', icon: 'description', label: 'Minutes' },
  ];

  const unit = $derived(data?.unit === 'PT' ? t('PD') : t('points'));
  const nextText = (n: NextStep) =>
    ({
      none: '–',
      review: t('Prepare the review'),
      frozen: t('Plan is frozen'),
      absences: t('Confirm absences'),
      preplan: t('Pre-plan'),
      plan: t('Plan'),
    })[n];
  const stateText = (r: SprintRow) =>
    ({ past: t('Finished'), current: t('Running'), planned: t('Planned'), future: t('Coming') })[r.state];
  const absenceText = (r: SprintRow) =>
    ({ confirmed: t('Confirmed'), announced: t('Announced'), unknown: t('Not entered') })[r.absences];
  const num = (v: number | null) => (v === null ? '–' : days(v));
  const span = (r: { plan: number | null; planLow: number | null; planHigh: number | null }) =>
    r.plan === null ? '–' : r.planLow !== null && r.planHigh !== null && r.planLow < r.planHigh
      ? `${days(r.plan)} (${days(r.planLow)}–${days(r.planHigh)})` : days(r.plan);
  const stage = (label: string) => t(label);
  const open = (id: string) => selectSprint(id);
</script>

<PageHead title={t('Sprint overview')} lead={t('All sprints at a glance. Open any stage of any sprint from here; nothing is locked.')}>
  {#snippet actions()}
    <button class="btn" type="button" aria-pressed={all} onclick={() => (all = !all)}>
      <Icon name="history" size={18} />{all ? t('Show fewer finished sprints') : t('Show all finished sprints')}
    </button>
  {/snippet}
</PageHead>

{#if error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
{:else if !data}
  <p class="muted">{t('Loading …')}</p>
{:else}
  <div class="tw">
    <table class="t" aria-label={t('Sprint overview')}>
      <thead>
        <tr>
          <th scope="col">{t('Sprint')}</th>
          <th scope="col">{t('Period')}</th>
          <th scope="col">{t('Status')}</th>
          <th scope="col">{t('Absences of the sprint')}</th>
          <th scope="col" class="num">{t('Capacity')} ({t('PD')})</th>
          <th scope="col" class="num">{t('Forecast PLAN')}</th>
          <th scope="col" class="num">{t('Commitment')}</th>
          <th scope="col" class="num">{t('Velocity')}</th>
          <th scope="col" class="num">{t('Normalized velocity')}</th>
          <th scope="col">{t('Next step')}</th>
          <th scope="col"><span class="sr">{t('Open stage')}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each data.rows as r (r.id)}
          <tr class:cur={r.id === app.sprint}>
            <td><span class="data"><strong>{r.name}</strong></span></td>
            <td class="data">{formatPeriod(r.start, r.end)}</td>
            <td><span class="chip {r.state === 'current' ? 'ok' : ''}">{stateText(r)}</span></td>
            <td>
              <span class="chip {r.absences === 'confirmed' ? 'ok' : r.absences === 'announced' ? 'warn' : ''}">
                {#if r.absences !== 'unknown'}<Icon name={r.absences === 'confirmed' ? 'lock' : 'lock_open'} size={14} />{/if}{absenceText(r)}
              </span>
            </td>
            <td class="num">{num(r.capacity)}</td>
            <td class="num fc">{span(r)}</td>
            <td class="num">{num(r.commitment)}</td>
            <td class="num">{num(r.velocity)}</td>
            <td class="num">
              {num(r.normalized)}{#if r.rate !== null}<span class="muted small rate">({days(r.rate)} {t('per PD')})</span>{/if}{#if r.factor != null}<span class="muted small rate">{t('factor {factor}', { factor: days(r.factor) })}</span>{/if}
              {#if r.normalized !== null && r.velocity !== null && r.capacity !== null}
                <Calc label={t('Normalized velocity')} topic="rate">
                  {days(r.velocity)} ÷ {days(r.capacity)} {t('PD')} × {days(data.reference)} {t('PD')} = {days(r.normalized)}
                </Calc>
              {/if}
            </td>
            <td class="next">{nextText(r.next)}</td>
            <td>
              <div class="row stages">
                {#each stages as s (s.to)}
                  <a class="btn icon ghost" href={link(s.to)} onclick={() => open(r.id)} title="{stage(s.label)}: {r.name}" aria-label="{stage(s.label)}: {r.name}">
                    <Icon name={s.icon} size={18} />
                  </a>
                {/each}
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="small muted note">
    {t('Normalized velocity is the velocity at the full team capacity without absences ({ref} {unit}), so sprints with and without absences can be compared. In brackets the rate per person day that the forecast calculates with.', { ref: days(data.reference), unit: data.unit === 'PT' ? t('PD') : t('person days') })}
  </p>
  <p class="small muted">{t('The selected sprint is highlighted. Capacity and Forecast PLAN follow the absences at once.')}</p>
{/if}

<style>
  tr.cur td {
    background: var(--primary-weak);
  }
  .fc {
    color: var(--forecast);
  }
  .next {
    white-space: normal;
    min-width: 84px;
  }
  .rate {
    display: block;
    text-align: right;
  }
  table.t :global(th),
  table.t :global(td) {
    padding-inline: 6px;
  }
  table.t :global(th) {
    white-space: normal;
    vertical-align: bottom;
  }
  .stages :global(.btn.icon) {
    width: 24px;
  }
  .stages {
    gap: 2px;
    flex-wrap: nowrap;
  }
  .note {
    margin-top: 12px;
    max-width: 90ch;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
</style>
