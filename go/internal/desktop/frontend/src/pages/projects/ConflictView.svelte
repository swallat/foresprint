<script lang="ts">
  import { app, openTicket, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { ConflictRow, ProjectsView } from '../../lib/types.projects';
  import Banner from '../../lib/ui/Banner.svelte';
  import Amount from './Amount.svelte';
  import { noteText, type Note } from './conflict';
  import { num } from './format';
  import LightChip from './LightChip.svelte';
  import ProjectCalc from './ProjectCalc.svelte';

  interface Props {
    view: ProjectsView;
  }
  let { view }: Props = $props();

  const estimated = $derived(view.unit === 'SP');
  const productName = (id: string) => view.products.find((p) => p.id === id)?.name ?? id;
  const lightText = (l: string) => (l === 'ok' ? t('on track') : l === 'warn' ? t('tight') : l === 'bad' ? t('at risk') : t('no light'));
  // A conflict is a product that is tight or full, or a contingent that does not last.
  const hasConflict = $derived(view.conflict.some((r) => r.light !== 'ok') || view.fit.some((f) => f.status === 'over'));
  const fitOf = (id: string) => view.fit.find((f) => f.project === id);
  const fitted = $derived(view.projects.filter((p) => fitOf(p.id)));

  function rating(r: ConflictRow): string {
    return r.light === 'ok' ? t('room left') : r.light === 'warn' ? t('nearly full') : t('no room');
  }

  async function copy(kind: Note): Promise<void> {
    try {
      await navigator.clipboard.writeText(noteText(view, kind));
      toast(t('The note is on the clipboard.'), 'ok');
    } catch {
      toast(t('The note could not be copied.'), 'bad');
    }
  }
</script>

<section class="card" style="margin-top:16px" data-tour="projects-conflict">
  <div class="row">
    <h2 style="margin:0;flex:1">{t('Conflict view: demand and product budget')}</h2>
    <span class="chip"><Icon name="event_available" size={16} />{t('Sprint')} <span class="data">{view.conflictSprint}</span></span>
  </div>
  <p class="muted" style="margin:4px 0 12px">
    {t('What the projects ask of the next sprint, against the pre-planned budget of each product. Everything here is a recommendation. The PO decides.')}
  </p>
  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th>{t('Product')}</th>
          <th class="num">{t('Budget ({unit})', { unit: view.unit })}</th>
          {#each view.projects as p (p.id)}<th class="num wrapth">{p.name}</th>{/each}
          <th class="num">{t('Left for daily business')}</th>
          <th>{t('Rating')}</th>
          <th>{t('Recommendation')}</th>
        </tr>
      </thead>
      <tbody>
        {#each view.conflict as r (r.product)}
          <tr>
            <td>{r.product ? productName(r.product) : app.teams.find((x) => x.key === app.team)?.name}</td>
            <td class="num">{num(r.budget)}</td>
            {#each view.projects as p (p.id)}
              {@const points = r.demand.find((d) => d.project === p.id)?.points ?? 0}
              <td class="num">{points > 0 ? num(points) : '–'}</td>
            {/each}
            <td class="num"><strong>{num(r.rest)}</strong></td>
            <td><LightChip light={r.light} label={rating(r)} /></td>
            <td class="advice small">
              {#if r.suggest.kind === 'none'}
                {t('No action needed.')}
              {:else if r.suggest.kind === 'move'}
                <button type="button" class="link data" onclick={() => openTicket(r.suggest.ticket)}>{r.suggest.ticket}</button>
                {t('({project}, {light}) one sprint later makes room for {n} {unit}.', {
                  project: r.suggest.projectName,
                  light: lightText(r.suggest.light),
                  n: num(r.suggest.points),
                  unit: view.unit,
                })}
              {:else}
                {t('Every project with a ticket here is at risk or fixed in the sprint. Talk to the project lead.')}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if fitted.length > 0}
    <h2 style="margin:16px 0 8px">{t('Contingent of the projects')}</h2>
    <div class="tw">
      <table class="t">
        <thead>
          <tr>
            <th>{t('Project')}</th>
            <th class="num">{t('Left in the contingent (PD)')}</th>
            <th class="num">{t('Need from {sprint} (PD)', { sprint: view.conflictSprint })}</th>
            <th>{t('Rating')}</th>
          </tr>
        </thead>
        <tbody>
          {#each fitted as p (p.id)}
            {@const f = fitOf(p.id)!}
            <tr>
              <td><a href={link('/projects/:id', { id: p.id })}>{p.name}</a></td>
              <td class="num"><Amount value={f.remaining} /></td>
              <td class="num"><Amount value={f.need} est={estimated} /><ProjectCalc project={p} rate={view.rate} kind="planned" /></td>
              <td>
                {#if f.status === 'ok'}<LightChip light="ok" label={t('enough')} />
                {:else if f.status === 'tight'}<LightChip light="warn" label={t('barely enough')} />
                {:else if f.status === 'over'}<LightChip light="bad" label={t('{n} PD short', { n: num(f.missing) })} />
                {:else}<span class="muted">–</span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if hasConflict}
    <Banner>
      <strong>{t('The PO decides.')}</strong>
      {t('Foresprint changes nothing here. Ways out: move work to a later sprint, accept the risk, or talk to the project lead.')}
      {#snippet action()}
        <a class="btn" href={link('/sprint/preplan')}><Icon name="event_repeat" />{t('Move tickets')}</a>
        <button class="btn" type="button" onclick={() => void copy('accept')}><Icon name="warning" />{t('Accept the risk')}</button>
        <button class="btn" type="button" onclick={() => void copy('talk')}><Icon name="forum" />{t('Talk to the project lead')}</button>
      {/snippet}
    </Banner>
  {/if}
</section>

<style>
  .wrapth {
    white-space: normal;
    min-width: 90px;
  }
  td.advice {
    white-space: normal;
    min-width: 260px;
  }
  a.btn {
    text-decoration: none;
    color: var(--text);
  }
</style>
