<script lang="ts">
  // Sprint > Prepare (flows.md F3, decisions 1 and 23): the absences of this and the next
  // sprints, the readiness list and the preview of the capacity. Nothing here is a gate: open
  // points show what is missing and planning works with the data at hand.
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import { days } from '../../lib/absences/format';
  import AbsenceGrid from '../../lib/absences/AbsenceGrid.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import type { AbsenceColumn, ReadyItem, SprintPrepare } from '../../lib/types.sprints';

  let { params }: PageProps = $props();
  void params;

  let info = $state<SprintPrepare | undefined>();
  let error = $state('');

  let seq = 0;
  async function load() {
    if (!app.team || !app.sprint) return;
    const mine = ++seq;
    try {
      const next = await api.SprintPrepare(app.team, app.sprint);
      if (mine !== seq) return; // the sprint changed meanwhile
      info = next;
      error = '';
    } catch (e) {
      if (mine === seq) error = String(e);
    }
  }

  $effect(() => {
    void [app.team, app.sprint];
    void load();
  });

  /** An edit in the grid changes this page's figures only when it is the sprint in focus. */
  function changed(column: AbsenceColumn) {
    if (column.id === app.sprint) void load();
  }

  const unit = $derived(info?.unit === 'PT' ? t('PD') : t('points'));
  const signed = (v: number) => (v > 0 ? `+${days(v)}` : v < 0 ? `−${days(-v)}` : '0');

  function title(r: ReadyItem): string {
    return r.kind === 'absences' ? t('Absences') : r.kind === 'refinement' ? t('Refinement') : t('Pre-planning per product');
  }

  function text(r: ReadyItem): string {
    if (r.kind === 'absences') {
      if (r.state === 'done') return t('Allocation frozen.');
      return r.count > 0
        ? t('{n} people announced, not yet confirmed. Freeze the allocation in the table above.', { n: r.count })
        : t('Nothing entered yet. Enter absences, or freeze the allocation: then nobody is absent.');
    }
    if (r.kind === 'refinement') {
      return r.state === 'done'
        ? t('All earmarked tickets are refined and estimated.')
        : t('{n} earmarked tickets are not refined: {keys}.', { n: r.count, keys: r.names.join(', ') });
    }
    if (r.state === 'done') return t('Every product has an amount.');
    return t('No amount for {names}.', { names: r.names.join(', ') });
  }

  function target(r: ReadyItem): { to: string; label: string } | undefined {
    if (r.kind === 'refinement' && r.state === 'open') return { to: '/backlog', label: t('Open in the backlog') };
    if (r.kind === 'preplan') return { to: '/sprint/preplan', label: t('Open pre-plan') };
    return undefined;
  }
</script>

<PageHead title={t('Prepare sprint')} lead={t('Enter the absences of the next sprints, then check what is still open. Nothing is locked.')} />

{#if error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
{/if}

{#if !app.team || !app.sprint}
  <div class="card"><p class="muted">{t('No sprint selected.')}</p></div>
{:else}
  <section class="card block">
    <h2>{t('Absences in person days')}</h2>
    <p class="small muted hint">
      {t('Type days directly (half days with a comma), Enter moves down. New entries are announced; the lock freezes the sprint and makes empty cells count as 0 days. Only days are stored, never a reason.')}
    </p>
    <AbsenceGrid team={app.team} from={app.sprint} count={4} focus={app.sprint} onchange={changed} />
  </section>

  {#if info}
    <div class="grid cols-2">
      <section class="card" aria-labelledby="ready-h">
        <h2 id="ready-h">{t('Ready for planning?')}</h2>
        <ul class="ready">
          {#each info.ready as r (r.kind)}
            {@const go = target(r)}
            <li>
              <span class="chip {r.state === 'done' ? 'ok' : 'warn'}">
                <Icon name={r.state === 'done' ? 'check_circle' : 'warning'} size={16} />{r.state === 'done' ? t('Done') : t('Open')}
              </span>
              <span class="grow"><strong>{title(r)}</strong><br /><span class="small muted">{text(r)}</span></span>
              {#if go}<a class="btn" href={link(go.to)}>{go.label}</a>{/if}
            </li>
          {/each}
        </ul>
        <p class="small muted">{t('Open points block nothing. You can plan at any time with the data that is there.')}</p>
      </section>

      <section class="card" aria-labelledby="prev-h">
        <h2 id="prev-h">{t('Preview for {sprint}', { sprint: info.sprint.name })}</h2>
        <dl class="kv">
          <dt>{t('Without absence')}</dt>
          <dd class="data">{days(info.capacityBase)} {t('PD')}{#if info.planBase !== null}{' · '}{days(info.planBase)} {unit}{/if}</dd>
          <dt>{t('With absence')}</dt>
          <dd class="data">
            <strong>{days(info.sprint.capacity)} {t('PD')}</strong>{#if info.sprint.plan !== null}{' · '}<strong class="fc">{days(info.sprint.plan)} {unit}</strong>{/if}
          </dd>
          <dt>{t('Change')}</dt>
          <dd class="data">
            {signed(info.sprint.capacity - info.capacityBase)} {t('PD')}{#if info.sprint.plan !== null && info.planBase !== null}{' · '}{signed(info.sprint.plan - info.planBase)} {unit}{/if}
          </dd>
          <dt>{t('Pre-planned')}</dt>
          <dd class="data">{days(info.preplanned)} {unit}</dd>
        </dl>
        {#if info.sprint.state !== 'confirmed'}
          <p class="small muted">{t('The Forecast PLAN is still a projection until the absences are frozen.')}</p>
        {/if}
      </section>
    </div>
  {/if}
{/if}

<style>
  .block {
    margin-bottom: 16px;
  }
  .block h2,
  .card h2 {
    margin: 0 0 8px;
    font: 600 16px/24px var(--font-ui);
  }
  .hint {
    margin: 0 0 12px;
    max-width: 80ch;
  }
  .ready {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .ready li {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 160px;
  }
  .fc {
    color: var(--forecast);
  }
</style>
