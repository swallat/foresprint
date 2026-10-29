<script lang="ts">
  import { app, refresh, selectSprint, syncTracker } from '../../lib/app.svelte';
  import { formatDay, formatPeriod } from '../../lib/format';
  import { language, t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { IconName } from '../../lib/icons';
  import { api } from '../../lib/api';
  import { go, link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { StepKey, TodayData, TodaySprint, TodayStep } from '../../lib/types.today';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  
  let { params }: PageProps = $props();
  void params;

  // The start page (flows.md section 5): what comes next per sprint, what others changed, what
  // the data check found. Every item leads to the page that handles it; nothing is required and
  // nothing blocks a page.
  let data = $state<TodayData>();
  let failure = $state('');
  let latest = 0;

  async function load(team: string): Promise<void> {
    const mine = ++latest;
    try {
      const got = await api.Today(team);
      if (mine === latest) {
        data = got;
        failure = '';
      }
    } catch (e) {
      if (mine === latest) {
        data = undefined;
        failure = String(e);
      }
    }
  }

  // Reload when the team changes and after a save or refresh (the status values change then).
  // The values are derived first: the status object is replaced every few seconds, and an
  // unchanged value must not reload the page.
  const team = $derived(app.team);
  const storage = $derived(app.status.storage);
  const incoming = $derived(app.status.incoming);
  $effect(() => {
    void storage;
    void incoming;
    if (team) void load(team);
    else {
      latest++;
      data = undefined;
    }
  });
  $effect.pre(() => {
    // Show nothing of the old team while the new one loads.
    if (data && data.team !== team) data = undefined;
  });

  const steps: Record<StepKey, { icon: IconName; label: () => string; to: string }> = {
    absences: { icon: 'event_busy', label: () => t('Absences (people away)'), to: '/sprint/prepare' },
    preplan: { icon: 'low_priority', label: () => t('Pre-plan'), to: '/sprint/preplan' },
    plan: { icon: 'checklist', label: () => t('Plan'), to: '/sprint/plan' },
    review: { icon: 'task_alt', label: () => t('Review'), to: '/sprint/review' },
  };

  function open(sprint: TodaySprint, to: string): void {
    selectSprint(sprint.id);
    go(to);
  }

  function stateText(s: TodayStep): string {
    if (s.detail) return s.detail;
    return s.state === 'done' ? t('done') : t('open');
  }

  function when(s: TodaySprint): string {
    switch (s.state) {
      case 'running':
        return t('in progress');
      case 'past':
        return t('completed');
      case 'next':
        return t('next');
      default:
        return t('later');
    }
  }

  function left(n: number): string {
    return n === 1 ? t('1 day left.') : t('{n} days left.', { n });
  }

  function startsIn(n: number): string {
    if (n <= 0) return t('Starts today.');
    return n === 1 ? t('Starts tomorrow.') : t('Starts in {n} days.', { n });
  }

  const tracker = $derived(app.status.tracker);
  const lastSync = $derived(tracker.last ? new Date(tracker.last).toLocaleString(language(), { dateStyle: 'short', timeStyle: 'short' }) : '');
  const sourceName = $derived(data?.source === 'packages' ? t('Work packages') : t('Tickets'));
  const trackerName = $derived(tracker.name || t('Tracker'));
  const unreviewed = $derived(data?.sprints.find((s) => s.state === 'past'));
</script>

<PageHead
  title={data ? t('Today, {date}', { date: formatDay(data.date) }) : t('Today')}
  lead={t('What comes next, what others changed and what stands out. Every item leads to the right page; nothing is required and nothing locks a page.')}
/>

{#if failure}
  <Banner tone="bad">{t('The start page could not be loaded: {problem}', { problem: failure })}</Banner>
{:else if !app.team}
  <div class="card stack narrow">
    <h2>{t('No team yet')}</h2>
    <p class="muted">{t('Create a team or open the demo team to see what is next.')}</p>
    <div class="row"><a class="btn primary" href={link('/setup')}><Icon name="add_circle" />{t('Set up Foresprint')}</a></div>
  </div>
{:else if data}
  {#if unreviewed}
    <div class="gap">
      <Banner tone="warn">
        <strong>{t('Review of sprint {id} is missing.', { id: unreviewed.id })}</strong>
        {t('Velocity and scope change are entered there; the forecast needs them.')}
        {#snippet action()}
          <button class="btn" type="button" onclick={() => open(unreviewed, '/sprint/review')}>{t('Go to Review')}<Icon name="arrow_forward" /></button>
        {/snippet}
      </Banner>
    </div>
  {/if}

  <div class="grid cols-2 gap">
    {#each data.sprints.filter((s) => s.state !== 'past') as s (s.id)}
      <section class="card stack" aria-labelledby={`td-${s.id}`} data-tour={s.state === 'running' ? 'today-running' : s.state === 'next' ? 'today-next' : undefined}>
        <div class="row">
          <h2 id={`td-${s.id}`}>{t('Sprint')} <span class="data">{s.id}</span></h2>
          <span class="chip" class:fc={s.state === 'running'}>{when(s)}</span>
          <span class="muted small data">{formatPeriod(s.start, s.end)}</span>
        </div>
        {#if s.state === 'running'}
          <Banner tone={s.steps[0]?.state === 'done' ? 'info' : 'warn'}>
            <strong>{t('Review on {date}', { date: formatDay(s.end) })}</strong>
            <span class="block">
              {s.daysLeft > 0 ? left(s.daysLeft) : t('Today is the last day.')}
              {t('Enter velocity, scope change and what was done per product.')}
            </span>
          </Banner>
        {/if}
        {#if s.startDue}
          <Banner tone="warn">
            <strong>{t('Sprint {id} is not started yet.', { id: s.id })}</strong>
            {t('Start it on the Plan page, together with the commitment.')}
            {#snippet action()}
              <button class="btn" type="button" onclick={() => open(s, '/sprint/plan')}>{t('Go to Plan')}<Icon name="arrow_forward" /></button>
            {/snippet}
          </Banner>
        {/if}
        <ul class="steps">
          {#each s.steps.filter((x) => x.state !== 'none') as step (step.key)}
            {@const def = steps[step.key]}
            <li>
              <span class="grow"><Icon name={def.icon} size={16} /> {def.label()}</span>
              <span class="chip" class:ok={step.state === 'done'} class:warn={step.state === 'open'}>
                <Icon name={step.state === 'done' ? 'check_circle' : 'radio_button_unchecked'} size={14} />{stateText(step)}
              </span>
              <button
                class="btn icon"
                type="button"
                aria-label={t('{action}: {step}', { action: step.state === 'done' ? t('Open') : t('Continue'), step: def.label() })}
                title={step.state === 'done' ? t('Open') : t('Continue')}
                onclick={() => open(s, def.to)}
              >
                <Icon name="arrow_forward" />
              </button>
            </li>
          {/each}
        </ul>
        {#if s.state !== 'running'}
          <p class="small muted">
            {startsIn(s.daysToStart)}
            {t('You can pre-plan at any time; planning works with the data of now.')}
          </p>
        {:else}
          <div class="row"><a class="btn" href={link('/sprints')}>{t('Sprint overview')}</a></div>
        {/if}
      </section>
    {:else}
      <section class="card stack">
        <h2>{t('No sprint ahead')}</h2>
        <p class="muted">{t('The sprint calendar has no running or coming sprint. Add sprints there.')}</p>
        <div class="row"><a class="btn" href={link('/team/calendar')}>{t('Sprint calendar')}</a></div>
      </section>
    {/each}
  </div>

  <div class="grid cols-3 gap">
    <section class="card stack" aria-labelledby="td-in">
      <h2 id="td-in"><Icon name="cloud_download" /> {t('Changes from others')}</h2>
      {#if app.status.incoming > 0}
        <p>{app.status.incoming === 1 ? t('One new change is waiting on the server.') : t('{n} new changes are waiting on the server.', { n: app.status.incoming })}</p>
        <div class="row">
          <button class="btn primary" type="button" disabled={!!app.busy} onclick={refresh}><Icon name="download" />{t('Refresh')}</button>
          <a class="small" href={link('/data')}>{t('Details under Data')}</a>
        </div>
      {:else}
        <p class="muted">{t('Everything is up to date. Nothing new from others.')}</p>
      {/if}
    </section>

    {#if data.source === 'tracker'}
      <section class="card stack" aria-labelledby="td-sync">
        <h2 id="td-sync"><Icon name="sync" /> {t('{name} sync', { name: trackerName })}</h2>
        <dl class="kv">
          <dt>{t('Last sync')}</dt>
          <dd>{lastSync || t('not yet')}</dd>
        </dl>
        {#if tracker.failed}<Banner tone="bad">{tracker.failed}</Banner>{/if}
        <div class="row">
          <button class="btn" type="button" disabled={!!app.busy} onclick={syncTracker}><Icon name="sync" />{t('Sync now')}</button>
          <a class="small" href={link('/settings/tickets')}>{t('Tickets and tracker')}</a>
        </div>
      </section>
    {/if}

    {#if data.source !== 'none'}
      <section class="card stack" aria-labelledby="td-bl">
        <h2 id="td-bl"><Icon name="view_list" /> {t('Backlog')}</h2>
        <p class="muted">{t('Order and earmark {what}, open one for its details.', { what: sourceName })}</p>
        <div class="row"><a class="btn" href={link('/backlog')}>{t('Open backlog')}<Icon name="arrow_forward" /></a></div>
      </section>
    {/if}
  </div>

  <section class="card" aria-labelledby="td-f" data-tour="today-findings">
    <h2 id="td-f">
      <Icon name="fact_check" /> {t('Findings')}
      <span class="chip data" class:bad={data.errors > 0} class:warn={data.errors === 0 && data.notices > 0}>{data.errors + data.notices}</span>
    </h2>
    {#if data.findings.length === 0}
      <p class="muted">{t('The data check found nothing.')}</p>
    {:else}
      <ul class="findings">
        {#each data.findings as f, i (i)}
          <li>
            <span class="chip" class:bad={f.level === 'error'} class:warn={f.level === 'notice'}>
              <Icon name={f.level === 'error' ? 'error' : 'warning'} size={14} />{f.level === 'error' ? t('Error') : t('Notice')}
            </span>
            <span class="grow">{f.message} <span class="muted small data">{f.where}</span></span>
            <a class="btn" href={link(f.route)}>{t('Open')}<Icon name="arrow_forward" /></a>
          </li>
        {/each}
      </ul>
      {#if data.errors + data.notices > data.findings.length}
        <p class="small muted">{t('{n} more findings are not listed here.', { n: data.errors + data.notices - data.findings.length })}</p>
      {/if}
    {/if}
  </section>
{:else}
  <p class="muted">{t('Loading…')}</p>
{/if}

<style>
  h2 {
    margin: 0;
    font-size: 16px;
    line-height: 24px;
  }
  .gap {
    margin-bottom: 16px;
  }
  .narrow {
    max-width: 560px;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .steps,
  .findings {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .steps li,
  .findings li {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
  }
  .steps li {
    flex-wrap: nowrap;
  }
  .steps li > .grow {
    min-width: 0;
  }
  .block {
    display: block;
  }
  a.btn {
    text-decoration: none;
    color: var(--text);
  }
  .findings li {
    align-items: flex-start;
  }
  .findings .grow {
    min-width: 200px;
  }
  p {
    margin: 0;
  }
</style>
