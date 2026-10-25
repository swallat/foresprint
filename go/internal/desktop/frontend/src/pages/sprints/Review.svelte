<script lang="ts">
  // Sprint > Review (flows.md F5): velocity from commitment, not done and done in addition, done
  // per product, the person days frozen, the carry-over and a tag. Works for all three ticket
  // modes: with tickets the list of the commitment replaces the typed "not done".
  import { api } from '../../lib/api';
  import { app, refreshStatus, toast } from '../../lib/app.svelte';
  import { days, parseDays } from '../../lib/absences/format';
  import Calc from '../../lib/calc/Calc.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import ExpectSeg from '../../lib/plan/ExpectSeg.svelte';
  import SprintFigures from '../../lib/plan/SprintFigures.svelte';
  import StageNav from '../../lib/sprints/StageNav.svelte';
  import type { ReviewInput, ReviewTicket, SprintReview } from '../../lib/types.review';

  let { params }: PageProps = $props();
  void params;

  let info = $state<SprintReview | undefined>();
  let error = $state('');
  let busy = $state(false);

  // The form: typed text per field, so that a half-typed number is not rewritten.
  let notDone = $state('0');
  let additional = $state('0');
  let restNext = $state('0');
  let frozen = $state('0');
  let production = $state('0');
  let rows = $state<ReviewTicket[]>([]);
  let rests = $state<Record<string, string>>({});
  let commitment = $state('0');
  let done = $state<Record<string, string>>({});
  let prod = $state<Record<string, string>>({});
  let tagOn = $state(true);
  let tagName = $state('');

  const fmt = (v: number) => String(v).replace('.', ',');

  function fill(r: SprintReview) {
    info = r;
    notDone = fmt(r.notDone);
    additional = fmt(r.additionalDone);
    restNext = fmt(r.restNext);
    frozen = fmt(r.frozenDays);
    production = fmt(r.production);
    rows = r.list.map((x) => ({ ...x }));
    rests = Object.fromEntries(r.list.map((x) => [x.key, fmt(x.rest)]));
    commitment = fmt(r.commitment);
    done = Object.fromEntries(r.products.map((p) => [p.id, fmt(p.done)]));
    prod = Object.fromEntries(r.products.map((p) => [p.id, fmt(p.prodDone)]));
    tagName = r.tag;
  }

  let seq = 0;
  async function load() {
    if (!app.team || !app.sprint) return;
    const mine = ++seq;
    try {
      const next = await api.SprintReview(app.team, app.sprint);
      if (mine !== seq) return; // the sprint changed meanwhile
      fill(next);
      error = '';
    } catch (e) {
      if (mine === seq) error = String(e);
    }
  }

  $effect(() => {
    void [app.team, app.sprint];
    info = undefined; // the old sprint's numbers are not editable while the new one loads
    void load();
  });

  const unit = $derived(info?.unit === 'PT' ? t('PD') : t('points'));
  const locked = $derived(busy || info?.reviewed === true);
  const n = (text: string) => parseDays(text);
  const valid = (text: string) => Number.isFinite(n(text)) && n(text) >= 0;

  const commitmentNow = $derived(!info ? 0 : info.commitmentSet ? info.commitment : n(commitment));
  const notDoneNow = $derived(
    info?.reviewed
      ? info.notDone
      : info?.tickets
        ? Math.min(rows.filter((r) => !r.done && !r.added).reduce((sum, r) => sum + r.estimate, 0), info.frozen ? Infinity : commitmentNow)
        : n(notDone),
  );
  // With tickets the scope numbers follow the table: what was pulled in and is done counts as
  // done in addition; the rest that continues in the next sprint is the final carry-over.
  const additionalNow = $derived(
    info?.reviewed ? info.additionalDone : info?.tickets ? rows.filter((r) => r.added && r.done).reduce((sum, r) => sum + r.estimate, 0) : n(additional),
  );
  const restNow = $derived(
    info?.reviewed ? info.restNext : rows.filter((r) => !r.done && r.target === '').reduce((sum, r) => sum + n(rests[r.key] ?? '0'), 0),
  );
  const listed = $derived(rows.filter((r) => !r.added));
  const addedRows = $derived(rows.filter((r) => r.added));
  const pulledNow = $derived(info?.tickets ? rows.filter((r) => r.added && r.done) : []);
  const noEstimateNow = $derived(pulledNow.filter((r) => r.estimate === 0).map((r) => r.key));
  const listSum = $derived(listed.reduce((sum, r) => sum + r.estimate, 0));
  // A closed Review shows what was stored; only an open one calculates while typing.
  const velocity = $derived(!info ? 0 : info.reviewed ? info.velocity : commitmentNow - notDoneNow + additionalNow);
  const frozenDays = $derived(n(frozen));
  const rate = $derived(info?.reviewed ? info.rate : frozenDays > 0 ? velocity / frozenDays : null);
  const doneSum = $derived(info ? info.products.reduce((sum, p) => sum + n(done[p.id] ?? '0'), 0) : 0);
  const prodSum = $derived(info ? info.products.reduce((sum, p) => sum + n(prod[p.id] ?? '0'), 0) : 0);
  const plannedSum = $derived(info ? info.products.reduce((sum, p) => sum + p.planned, 0) : 0);
  const signed = (v: number) => (v > 0 ? `+${days(v)}` : v < 0 ? `−${days(-v)}` : '0');

  const problems = $derived.by(() => {
    if (!info) return [] as string[];
    const out: string[] = [];
    const typed = [notDone, additional, restNext, frozen, production, commitment, ...Object.values(done), ...Object.values(prod), ...rows.filter((r) => !r.done).map((r) => rests[r.key] ?? '0')];
    if (!typed.every(valid)) out.push(t('Enter numbers of 0 or more.'));
    if (!info.tickets && n(restNext) > n(notDone)) out.push(t('The rest that continues cannot be more than what was not done.'));
    if (notDoneNow > commitmentNow) out.push(t('Not done cannot be more than the commitment.'));
    return out;
  });

  async function close() {
    if (!info || problems.length > 0) return;
    const team = app.team;
    const sprint = app.sprint;
    const input: ReviewInput = {
      commitment: info.commitmentSet ? null : n(commitment),
      notDone: n(notDone),
      additionalDone: info.tickets ? additionalNow : n(additional),
      restNext: n(restNext),
      list: rows.map((r) => ({ ...r, rest: n(rests[r.key] ?? '0') })),
      frozenDays: frozenDays,
      products: info.products.map((p) => ({ ...p, done: n(done[p.id] ?? '0'), prodDone: n(prod[p.id] ?? '0') })),
      production: n(production),
      tag: tagOn ? tagName.trim() : '',
    };
    busy = true;
    try {
      const res = await api.CloseReview(team, sprint, input);
      if (team !== app.team || sprint !== app.sprint) return; // the page moved on; it loads its own sprint
      fill(res.review);
      error = '';
      toast(res.tag ? t('Sprint {id} closed. Minutes written; tag {tag} is set with the next save.', { id: res.review.sprint.name, tag: res.tag }) : t('Sprint {id} closed. Minutes written.', { id: res.review.sprint.name }), 'ok');
      await refreshStatus();
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  async function reopen() {
    const team = app.team;
    const sprint = app.sprint;
    busy = true;
    try {
      const res = await api.ReopenReview(team, sprint);
      if (team !== app.team || sprint !== app.sprint) return;
      fill(res.review);
      error = '';
      toast(t('Review reopened. Its minutes stay as an obsolete file.'));
      await refreshStatus();
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  const targetName = (id: string) => info?.targets.find((x) => x.id === id)?.name ?? id;
</script>

<PageHead title={t('Review sprint')} lead={t('Record what the sprint delivered. The velocity feeds the forecast of the next sprints.')}>
  {#snippet actions()}
    {#if info?.reviewed}
      <button type="button" class="btn" disabled={busy || !info.reopenable} title={info.reopenable ? '' : t('Only the latest reviewed sprint can be reopened.')} onclick={reopen}>
        <Icon name="lock_open" />{t('Reopen review')}
      </button>
    {:else}
      <button type="button" class="btn primary" data-tour="review-close" disabled={busy || !info?.started || problems.length > 0} onclick={close}>
        <Icon name="task_alt" />{t('Close sprint')}
      </button>
    {/if}
  {/snippet}
</PageHead>
<StageNav stage="review" />

{#if app.team && app.sprint}<SprintFigures reload={info?.reviewed} />{/if}

{#if error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
{/if}

{#if !app.team || !app.sprint}
  <div class="card"><p class="muted">{t('No sprint selected.')}</p></div>
{:else if info}
  {#if !info.started}
    <div class="banner warn" role="status">
      <Icon name="schedule" />
      <div class="grow">{t('Sprint {id} has not begun; it cannot be reviewed yet.', { id: info.sprint.name })}</div>
    </div>
  {:else if info.reviewed}
    <div class="banner info" role="status">
      <Icon name="lock" />
      <div class="grow">{t('This Review is closed. Reopen it to change the numbers.')}</div>
    </div>
  {/if}

  <div class="grid cols-2 block">
    <section class="card" aria-labelledby="vel-h" data-tour="review-velocity">
      <h2 id="vel-h">{t('Velocity')}</h2>
      <div class="row">
        <span class="big data" data-testid="velocity">{days(velocity)}</span>
        <span class="muted">{unit} {t('done')}</span>
        <Calc label={t('Velocity')} topic="rate">
          {days(commitmentNow)} − {days(notDoneNow)} + {days(additionalNow)} = {days(velocity)} {unit}
        </Calc>
      </div>
      <p class="small muted">{t('Commitment {n} minus not done plus done in addition.', { n: days(commitmentNow) })}</p>
    </section>

    <section class="card" aria-labelledby="scope-h" data-tour="review-scope">
      <h2 id="scope-h">{t('Scope change')}</h2>
      <div class="row fields">
        {#if !info.commitmentSet}
          <div class="field">
            <label for="rv-commit">{t('Commitment')} ({unit})</label>
            <input id="rv-commit" class="input data" inputmode="decimal" bind:value={commitment} disabled={locked} />
          </div>
        {/if}
        {#if !info.tickets}
          <div class="field">
            <label for="rv-notdone">{t('Not done')} ({unit})</label>
            <input id="rv-notdone" class="input data" inputmode="decimal" bind:value={notDone} disabled={locked} />
          </div>
          <div class="field">
            <label for="rv-rest">{t('of which rest in the next sprint')} ({unit})</label>
            <input id="rv-rest" class="input data" inputmode="decimal" bind:value={restNext} disabled={locked} />
          </div>
          <div class="field">
            <label for="rv-extra">{t('Done in addition')} ({unit})</label>
            <input id="rv-extra" class="input data" inputmode="decimal" bind:value={additional} disabled={locked} />
          </div>
        {:else}
          <div class="field">
            <span class="lbl">{t('Not done')} ({unit})</span>
            <span class="data stat" data-testid="not-done">{days(notDoneNow)}</span>
          </div>
          <div class="field">
            <span class="lbl">{t('of which rest in the next sprint')} ({unit})</span>
            <span class="data stat" data-testid="rest-next">{days(restNow)}</span>
          </div>
          <div class="field">
            <span class="lbl">{t('Done in addition')} ({unit})</span>
            <span class="data stat" data-testid="additional">{days(additionalNow)}</span>
          </div>
        {/if}
      </div>
      {#if info.tickets && info.prefill && !info.reviewed}
        <p class="small muted" data-testid="prefill">{t('Prefilled from assumption {label} of the pre-planning; done in the tracker counts as done.', { label: info.prefill })}</p>
      {/if}
      {#if pulledNow.length > 0 && !info.reviewed}
        <p class="small muted" data-testid="pulled">
          {t('Prefilled from {n} done tickets pulled in after the freeze: {keys}.', { n: pulledNow.length, keys: pulledNow.map((r) => r.key).join(', ') })}
          {#if noEstimateNow.length > 0}{t('Without an estimate: {keys}.', { keys: noEstimateNow.join(', ') })}{/if}
        </p>
      {/if}
      <p class="small muted">
        {#if info.tickets}
          {t('The numbers follow the ticket table. Not done is missing in full from the velocity; only its rest continues. Change them there.')}
        {:else}
          {t('Not done is missing in full from the velocity. The rest that continues in the next sprint is the final carry-over and replaces the assumption from the pre-planning.')}
        {/if}
      </p>
    </section>
  </div>

  {#if info.tickets}
    <section class="block" aria-labelledby="tk-h">
      <h2 id="tk-h">{t('Tickets of the commitment')}</h2>
      {#if Math.abs(listSum - commitmentNow) > 0.001 && !info.reviewed}
        <p class="small muted" data-testid="sum-hint">{t('The tickets add up to {sum}, the commitment is {commitment}.', { sum: days(listSum), commitment: days(commitmentNow) })}</p>
      {/if}
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th scope="col">{t('Ticket')}</th>
              <th scope="col">{t('Status')}</th>
              <th scope="col" class="num">{t('Size')}</th>
              <th scope="col">{t('Result')}</th>
              <th scope="col" class="num">{t('Rest')}</th>
              <th scope="col">{t('Continues in')}</th>
            </tr>
          </thead>
          <tbody>
            {#each listed as r (r.key)}{@render trow(r)}{/each}
            {#if addedRows.length > 0}
              <tr class="sum"><td colspan="6"><Icon name="call_received" size={14} /> {t('Pulled in after the planning')} <span class="small muted">{t('(new in the sprint since freezing, not part of the commitment)')}</span></td></tr>
              {#each addedRows as r (r.key)}{@render trow(r)}{/each}
            {/if}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  {#if info.productsOn}
    <section class="block" aria-labelledby="done-h" data-testid="done" data-tour="review-done">
      <h2 id="done-h">{t('Done per product')}</h2>
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th scope="col">{t('Product')}</th>
              <th scope="col" class="num">{t('Planned')}</th>
              <th scope="col" class="num">{t('Done')}</th>
              {#if info.productionOn}<th scope="col" class="num">{t('of which production')}</th>{/if}
              <th scope="col" class="num">{t('Difference')}</th>
            </tr>
          </thead>
          <tbody>
            {#each info.products as p (p.id)}
              <tr>
                <td>{p.name}</td>
                <td class="num">{days(p.planned)}</td>
                <td class="num"><input class="input data narrow" inputmode="decimal" bind:value={done[p.id]} disabled={locked} aria-label={t('Done {name}', { name: p.name })} /></td>
                {#if info.productionOn}
                  <td class="num"><input class="input data narrow" inputmode="decimal" bind:value={prod[p.id]} disabled={locked} aria-label={t('of which production {name}', { name: p.name })} /></td>
                {/if}
                <td class="num">{signed(n(done[p.id] ?? '0') - p.planned)}</td>
              </tr>
            {/each}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{t('Total')}</th>
              <td class="num">{days(plannedSum)}</td>
              <td class="num">{days(doneSum)}</td>
              {#if info.productionOn}<td class="num">{days(prodSum)}</td>{/if}
              <td class="num">{signed(doneSum - plannedSum)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p class="small">
        {#if Math.abs(doneSum - velocity) < 0.001}
          <span class="chip ok"><Icon name="check_circle" size={14} />{t('The total matches the velocity')}</span>
        {:else}
          <span class="chip warn"><Icon name="warning" size={14} />{t('The total differs from the velocity by {n}', { n: signed(doneSum - velocity) })}</span>
        {/if}
        {#if info.productionOn}<span class="muted">{t('The production share is shown, not enforced.')}</span>{/if}
      </p>
    </section>
  {:else if info.productionOn}
    <section class="card block">
      <div class="field">
        <label for="rv-prod">{t('Done with production access')} ({unit})</label>
        <input id="rv-prod" class="input data narrow" inputmode="decimal" bind:value={production} disabled={locked} />
      </div>
    </section>
  {/if}

  <div class="grid cols-2">
    <section class="card" aria-labelledby="fz-h" data-tour="review-capacity">
      <h2 id="fz-h">{t('Freeze person days')}</h2>
      <div class="row fields">
        <div class="field">
          <label for="rv-days">{t('Available person days in the sprint')}</label>
          <input id="rv-days" class="input data narrow" inputmode="decimal" bind:value={frozen} disabled={locked} />
        </div>
        <div>
          <div class="data stat" data-testid="rate">{rate === null ? '–' : days(rate)} {info.unit === 'PT' ? '' : unit} {t('per PD')}</div>
          <span class="small muted">{t('actual rate (estimate)')}</span>
          {#if info.factor != null}
            <span class="small muted" data-testid="rate-factor">{t('Fixed factor {factor} per PD applies to conversions.', { factor: days(info.factor) })}</span>
          {/if}
          {#if rate !== null}
            <Calc label={t('Actual rate')} topic="rate">{days(velocity)} {unit} ÷ {days(frozenDays)} {t('PD')} = {days(rate)}</Calc>
          {/if}
        </div>
      </div>
      <p class="small muted">
        {t('Planned were {n} person days. The frozen days stay with the sprint, even if absences change later.', { n: days(info.plannedDays) })}
      </p>
    </section>

    <section class="card" aria-labelledby="tag-h" data-tour="review-tag">
      <h2 id="tag-h">{t('Tag and share')}</h2>
      <label class="row"><input type="checkbox" bind:checked={tagOn} disabled={locked} />{t('Tag the sprint with the next save')}</label>
      <div class="field top">
        <label for="rv-tag">{t('Name')}</label>
        <input id="rv-tag" class="input data tagname" bind:value={tagName} disabled={locked || !tagOn} />
      </div>
      <p class="small muted">{t('The minutes of this Review are written when you close the sprint.')} <a href={link('/sprint/minutes')}>{t('Open minutes')}</a></p>
    </section>
  </div>

  {#if problems.length > 0}
    <ul class="problems" role="alert">
      {#each problems as p (p)}<li>{p}</li>{/each}
    </ul>
  {/if}
{/if}

{#snippet trow(r: ReviewTicket)}
  <tr>
    <td class="tk"><span class="key">{r.key}</span> {r.title}</td>
    <td><span class="chip">{r.status}</span></td>
    <td class="num">{days(r.estimate)}</td>
    <td><ExpectSeg review ticket={r.key} carry={!r.done} disabled={locked} onchange={(on) => (r.done = !on)} /></td>
    <td class="num">
      {#if r.done}<span class="muted">–</span>{:else}
        <input class="input data narrow" inputmode="decimal" bind:value={rests[r.key]} disabled={locked} aria-label={t('Rest of {key}', { key: r.key })} />
      {/if}
    </td>
    <td>
      {#if r.done}<span class="muted">–</span>{:else}
        <select class="input" bind:value={r.target} disabled={locked} aria-label={t('Where {key} continues', { key: r.key })}>
          {#each info?.targets ?? [] as target (target.id)}
            <option value={target.id}>{target.id === '' ? t('Next sprint') : target.id === 'backlog' ? t('Back to the backlog') : targetName(target.id)}</option>
          {/each}
        </select>
      {/if}
    </td>
  </tr>
{/snippet}

<style>
  .block {
    margin-bottom: 16px;
  }
  .card h2,
  .block > h2 {
    margin: 0 0 8px;
    font: 600 16px/24px var(--font-ui);
  }
  .big {
    font-size: 28px;
    font-weight: 600;
    color: var(--forecast);
  }
  .stat {
    font-size: 18px;
  }
  .fields {
    align-items: flex-end;
    gap: 16px;
  }
  .lbl {
    font-size: 12px;
    color: var(--text-muted);
  }
  .narrow {
    width: 96px;
    text-align: right;
  }
  .tagname {
    max-width: 260px;
  }
  .top {
    margin-top: 8px;
  }
  .tk {
    white-space: normal;
    min-width: 280px;
    max-width: 440px;
  }
  .tk .key {
    white-space: nowrap;
  }
  td select.input {
    max-width: 200px;
  }
  tfoot th,
  tfoot td {
    font-weight: 600;
  }
  tfoot th,
  tfoot td {
    border-bottom: none;
  }
  tfoot th {
    position: static;
  }
  .problems {
    margin: 16px 0 0;
    padding-left: 20px;
    color: var(--bad);
  }
</style>
