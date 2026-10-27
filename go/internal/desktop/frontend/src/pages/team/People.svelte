<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { takeNew } from '../../lib/router.svelte';
  import { t } from '../../lib/i18n.svelte';
  import AbsenceGrid from '../../lib/absences/AbsenceGrid.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import Icon from '../../lib/Icon.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import Banner from '../../lib/ui/Banner.svelte';
  import { fmtDay, fmtNum, fmtShort, parseNum } from '../../lib/team/format';
  import { currentPeriod, entry, isCurrent, leaving, needsEnd, rejoined, withShare } from '../../lib/team/people';
  import { inverse, type Inverse } from '../../lib/team/undo';
  import type { AbsencePeriod, PeopleView, Person, PersonKind } from '../../lib/types.team';
  import AbsenceOverview from './AbsenceOverview.svelte';
  import AbsencePanel from './AbsencePanel.svelte';
  import OwnersCard from './OwnersCard.svelte';
  import TimesPanel from './TimesPanel.svelte';

  let { params }: PageProps = $props();
  void params;

  let view = $state<PeopleView>();
  let absences = $state<AbsencePeriod[]>([]);
  let filter = $state<'now' | 'former' | 'all'>('now');
  let panel = $state<{ kind: 'times' | 'absences'; id: string } | null>(null);
  let focusId = $state('');
  let failed = $state('');
  let openFrom = $state('');
  // The absence grid reads the people and the periods itself; it starts over when they changed.
  let gridKey = $state(0);

  const today = $derived(view?.today ?? '');
  const current = $derived((view?.people ?? []).filter((p) => isCurrent(p, today)));
  const former = $derived((view?.people ?? []).filter((p) => !isCurrent(p, today)));
  const total = $derived(current.reduce((n, p) => n + (currentPeriod(p, today)?.fte ?? 0), 0));
  const kinds: PersonKind[] = ['member', 'guest', 'external'];
  const kindLabel = (k: PersonKind) => (k === 'guest' ? t('Guest') : k === 'external' ? t('External') : t('Member'));

  let loadedTeam = '';
  async function load() {
    const team = app.team;
    try {
      const [v, a, cal] = await Promise.all([api.People(team), api.AbsencePeriods(team), api.Calendar(team, 1)]);
      view = v;
      openFrom = cal.rows.find((r) => r.state !== 'finished')?.start ?? '';
      loadedTeam = team;
      absences = a;
      gridKey++;
      failed = '';
    } catch (e) {
      failed = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    void app.team;
    load();
  });

  $effect(() => {
    if (!focusId) return;
    const input = document.querySelector<HTMLInputElement>(`[data-name="${focusId}"]`);
    if (input) {
      input.focus();
      input.select();
      focusId = '';
    }
  });

  const personFields: (keyof Person)[] = ['name', 'kind', 'production', 'memberships', 'region', 'country', 'workweek'];

  async function undoChange(undo: Inverse<Person>) {
    const { list, ok } = undo(view?.people ?? []);
    if (!ok) {
      toast(t('This change can no longer be undone.'), 'bad');
      return;
    }
    await save(list, t('Change undone.'), false);
    absences = await api.AbsencePeriods(app.team); // a removed person comes back without absences
  }

  /** Called by the PO card after one of its steps. */
  async function poStep() {
    await load();
  }

  /** Saves a new list of people. Undo takes back this one change only (see lib/team/undo.ts). */
  async function save(next: Person[], message: string, undoable = true) {
    const before = view?.people ?? [];
    try {
      view = await api.SavePeople(app.team, next);
      gridKey++;
      if (message) {
        const undo = inverse(before, view.people, personFields);
        toast(message, 'ok', undoable ? { label: t('Undo'), run: () => void undoChange(undo) } : undefined);
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
    }
  }

  const replace = (p: Person) => (view?.people ?? []).map((x) => (x.id === p.id ? p : x));

  function rename(p: Person, name: string) {
    if (!name.trim() || name === p.name) return load();
    return save(replace({ ...p, name: name.trim() }), '', false);
  }

  function setShare(p: Person, text: string) {
    const fte = parseNum(text);
    if (!(fte > 0 && fte <= 1)) {
      toast(t('Enter a share between 0.1 and 1.0.'), 'bad');
      return load();
    }
    return save(replace(withShare(p, today, fte)), '', false);
  }

  async function setKind(p: Person, kind: PersonKind) {
    const next = { ...p, kind };
    await save(replace(next), '', false);
    if (needsEnd(next)) {
      panel = { kind: 'times', id: p.id };
      toast(t('{name} is external. Please enter the end of the contract as the leaving day.', { name: p.name }));
    }
  }

  // "+" menu in the top bar: open with a new row
  $effect(() => {
    if (view && loadedTeam === app.team && takeNew()) add();
  });

  function add() {
    const person: Person = {
      id: '',
      name: t('New person'),
      kind: 'member',
      production: false,
      used: false,
      memberships: [{ from: view?.newFrom || today, to: '', fte: 1 }],
    };
    void save([...(view?.people ?? []), person], t('Person added.')).then(() => {
      const added = view?.people.find((p) => p.name === person.name && !p.used);
      if (added) focusId = added.id;
    });
  }

  function takeBack(p: Person) {
    void save(replace(rejoined(p, today)), t('{name} is back in the team from today. The earlier period stays in the history.', { name: p.name }));
  }

  /** The next absences of a person that have not ended. */
  function nextAbsences(p: Person): AbsencePeriod[] {
    return absences.filter((a) => a.person === p.id && a.to >= today).sort((a, b) => a.from.localeCompare(b.from));
  }

  async function saveAbsences(list: AbsencePeriod[]) {
    try {
      absences = await api.SaveAbsencePeriods(app.team, list);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      absences = await api.AbsencePeriods(app.team);
    }
    gridKey++;
  }

  const shown = $derived(filter === 'former' ? [] : current);
  const shownFormer = $derived(filter === 'now' ? [] : former);
  const production = $derived(view?.production ?? false);
</script>

<PageHead title={t('People and absences')} lead={t('Who is in the team, with which share, and when someone is away. Capacity and forecast read from here.')}>
  {#snippet actions()}
    <button class="btn" type="button" onclick={add}><Icon name="person_add" />{t('Add person')}</button>
  {/snippet}
</PageHead>

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{:else if !view}
  <p class="muted">{t('Loading…')}</p>
{:else}
  <div class="row filter" role="group" aria-label={t('Show')}>
    {#each [['now', t('Current ({n})', { n: current.length })], ['former', t('Former ({n})', { n: former.length })], ['all', t('All')]] as [code, label] (code)}
      <button type="button" class="chip filter" class:on={filter === code} aria-pressed={filter === code} onclick={() => (filter = code as typeof filter)}>{label}</button>
    {/each}
  </div>

  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th>{t('Name')}</th>
          <th class="num">{t('FTE')}</th>
          {#if production}<th title={t('Has access to production')}>{t('Production access')}</th>{/if}
          <th>{t('Belongs as')}</th>
          <th>{t('In the team')}</th>
          <th>{t('Absent (planned)')}</th>
          <th class="num">{t('Days per sprint')}</th>
          <th><span class="sr-only">{t('Actions')}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each shown as p (p.id)}
          {@const cur = currentPeriod(p, today)}
          {@const next = nextAbsences(p)}
          {@const end = leaving(p)}
          <tr>
            <td><input class="input name" data-name={p.id} value={p.name} aria-label={t('Name')} onchange={(e) => rename(p, e.currentTarget.value)} /></td>
            <td class="num">
              <input class="input data fte" value={fmtNum(cur?.fte ?? 1)} inputmode="decimal" aria-label={t('FTE {name}', { name: p.name })} onchange={(e) => setShare(p, e.currentTarget.value)} />
              {#if p.memberships.length > 1}
                <div class="small muted since" title={t('The share changed, see times')}>{t('since {date}', { date: fmtShort(cur?.from ?? '') })}</div>
              {/if}
            </td>
            {#if production}
              <td>
                <input type="checkbox" checked={p.production} aria-label={t('Production access {name}', { name: p.name })} onchange={(e) => save(replace({ ...p, production: e.currentTarget.checked }), '', false)} />
              </td>
            {/if}
            <td>
              <select class="input" aria-label={t('Belongs as {name}', { name: p.name })} value={p.kind} onchange={(e) => setKind(p, e.currentTarget.value as PersonKind)}>
                {#each kinds as k (k)}<option value={k}>{kindLabel(k)}</option>{/each}
              </select>
            </td>
            <td>
              <span class="small">{t('since')} <span class="data">{fmtDay(entry(p))}</span></span>
              {#if end}
                <span class="chip warn small" title={t('Counts for capacity until this day, not after')}><Icon name="logout" size={14} />{t('until {date}', { date: fmtDay(end) })}</span>
              {:else if needsEnd(p)}
                <button type="button" class="chip warn small" title={t('Externals are temporary. Without an end date the forecast counts them without limit.')} onclick={() => (panel = { kind: 'times', id: p.id })}>
                  <Icon name="event_busy" size={14} />{t('End date missing')}
                </button>
              {/if}
            </td>
            <td>
              <button
                type="button"
                class="chip {next.length ? (next.every((a) => a.confirmed) ? 'ok' : 'warn') : 'filter'}"
                aria-label={t('Planned absences of {name}: {count}', { name: p.name, count: next.length })}
                onclick={() => (panel = { kind: 'absences', id: p.id })}
              >
                {#if next.length}
                  <Icon name={next.every((a) => a.confirmed) ? 'lock' : 'lock_open'} size={14} />
                  {fmtShort(next[0]!.from)}–{fmtShort(next[0]!.to)}{next.length > 1 ? ` +${next.length - 1}` : ''}
                {:else}
                  <Icon name="add" size={14} />{t('Period')}
                {/if}
              </button>
            </td>
            <td class="num data">
              {fmtNum((cur?.fte ?? 0) * (view.sprintDays || 10))}
              <Calc label={t('Days per sprint of {name}', { name: p.name })} topic="capacity">
                {fmtNum(cur?.fte ?? 0)} {t('FTE')} × {view.sprintDays || 10} {t('working days')} = {fmtNum((cur?.fte ?? 0) * (view.sprintDays || 10))}
              </Calc>
            </td>
            <td class="actions">
              <button class="btn icon ghost" type="button" title={t('Times and leaving')} aria-label={t('Times and leaving {name}', { name: p.name })} onclick={() => (panel = { kind: 'times', id: p.id })}>
                <Icon name="date_range" />
              </button>
            </td>
          </tr>
        {/each}
        {#each shownFormer as p (p.id)}
          <tr class="former">
            <td>{p.name}</td>
            <td class="num data">{fmtNum(p.memberships[p.memberships.length - 1]?.fte ?? 0)}</td>
            {#if production}<td>{#if p.production}<Icon name="check" size={16} />{/if}</td>{/if}
            <td class="muted">{t('Former')}</td>
            <td class="small muted"><span class="data">{fmtDay(entry(p))}</span> {t('to')} <span class="data">{fmtDay(leaving(p))}</span></td>
            <td></td>
            <td class="num muted data">0</td>
            <td class="actions">
              <button class="btn icon ghost" type="button" title={t('Correct times')} aria-label={t('Correct times {name}', { name: p.name })} onclick={() => (panel = { kind: 'times', id: p.id })}>
                <Icon name="date_range" />
              </button>
              <button class="btn ghost" type="button" onclick={() => takeBack(p)}><Icon name="person_add" />{t('Take back')}</button>
            </td>
          </tr>
        {/each}
        {#if filter !== 'former'}
          <tr class="sum">
            <td>{t('Team')}</td>
            <td class="num">{fmtNum(total)}</td>
            {#if production}<td class="data">{t('{n} of {total}', { n: current.filter((p) => p.production).length, total: current.length })}</td>{/if}
            <td></td><td></td><td></td>
            <td class="num">{fmtNum(total * (view.sprintDays || 10))}</td>
            <td></td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
  <p class="small muted note">
    <strong>{t('Belongs as')}:</strong>
    {t('A member belongs to the team for good. A guest helps out from another team. An external is a temporary resource from outside and needs an end date (end of contract). All three count for capacity; minutes and calculations show guests and externals separately.')}
  </p>
  {#if !production}
    <p class="small muted">{t('The production access column appears when the feature is switched on in Settings, Team.')}</p>
  {/if}
{/if}

<OwnersCard people={view} onchange={poStep} />

{#if view}
  <section class="grid-sec" aria-labelledby="all-h">
    <div class="row head">
      <h2 id="all-h">{t('All absences')}</h2>
    </div>
    <p class="small muted">{t('Every planned period of every person. Change, confirm or delete them here; only the dates are stored, never a reason.')}</p>
    <AbsenceOverview people={view.people} today={view.today} {absences} {openFrom} onchange={saveAbsences} />
  </section>

  <section class="grid-sec" aria-labelledby="abs-h">
    <div class="row head">
      <h2 id="abs-h">{t('Absences over several sprints')}</h2>
    </div>
    <p class="small muted">{t('The number is person days, never a reason. Typing an entry is enough; the lock confirms it, as on Prepare.')}</p>
    <AbsenceGrid team={app.team} count={4} version={gridKey} />
  </section>
{/if}

{#if view && panel}
  {@const shown = panel}
  {@const person = view.people.find((p) => p.id === shown?.id)}
  {#if person && shown?.kind === 'times'}
    {#key shown.id}
    <TimesPanel
      {person}
      today={view.today}
      teamCountry={view.country}
      onclose={() => (panel = null)}
      onsave={(next, message) => {
        // Read before the panel closes: `person` is derived from the open panel and is gone afterwards.
        const was = person;
        panel = null;
        // Only the times and the holiday calendar come from the panel; the rest of the row may have changed meanwhile.
        return save(replace({ ...was, memberships: next.memberships, country: next.country, region: next.region }), message);
      }}
      onremove={() => {
        const gone = person;
        panel = null;
        return save(
          (view?.people ?? []).filter((x) => x.id !== gone.id),
          t('{name} removed.', { name: gone.name }),
        );
      }}
    />
    {/key}
  {:else if person && shown?.kind === 'absences'}
    <AbsencePanel
      {person}
      today={view.today}
      {absences}
      onclose={() => (panel = null)}
      onchange={saveAbsences}
    />
  {/if}
{/if}

<style>
  .filter {
    margin-bottom: 8px;
    gap: 6px;
  }
  .name {
    width: 150px;
  }
  .fte {
    width: 64px;
    text-align: right;
  }
  .since {
    margin-top: 6px;
    line-height: 1.2;
  }
  .former td {
    color: var(--text-muted);
  }
  .actions {
    white-space: nowrap;
  }
  .note {
    margin: 8px 0 0;
  }
  .grid-sec {
    margin-top: 24px;
  }
  .head {
    gap: 8px;
    margin-bottom: 4px;
  }
  .head h2 {
    flex: 1;
    margin: 0;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
