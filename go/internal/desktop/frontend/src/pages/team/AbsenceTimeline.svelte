<script lang="ts">
  // The planned absences on a time axis: one lane per person, the sprints as columns. A click on a
  // bar opens the dialog for that period; "+" starts a new one. Only dates, never a reason.
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { created, isLocked } from '../../lib/team/absences';
  import { fmtDay, fmtShort } from '../../lib/team/format';
  import type { AbsencePeriod, CalendarRow, Person } from '../../lib/types.team';
  import AbsenceDialog from './AbsenceDialog.svelte';

  interface Props {
    people: Person[];
    sprints: CalendarRow[];
    today: string;
    absences: AbsencePeriod[];
    openFrom: string;
    onchange: (list: AbsencePeriod[]) => void | Promise<void>;
  }
  let { people, sprints, today, absences, openFrom, onchange }: Props = $props();

  const DAY = 86_400_000;
  const ms = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

  const shown = $derived(people.filter((p) => absences.some((a) => a.person === p.id) || p.memberships.some((m) => !m.to || m.to >= today)));
  // The axis starts with the first sprint of the calendar; older periods are in the list only.
  const start = $derived(Math.min(...[ms(today), ...sprints.map((s) => ms(s.start))]));
  const end = $derived(Math.max(...[ms(today) + DAY, ...sprints.map((s) => ms(s.last) + DAY), ...absences.map((a) => ms(a.to) + DAY)]));
  const pos = (iso: string) => ((Math.max(ms(iso), start) - start) / (end - start)) * 100;
  const width = (from: string, to: string) => ((ms(to) + DAY - Math.max(ms(from), start)) / (end - start)) * 100;
  const visible = (a: AbsencePeriod) => ms(a.to) + DAY > start;
  const months = $derived.by(() => {
    const out: { label: string; at: number }[] = [];
    const d = new Date(start);
    d.setUTCDate(1);
    for (; d.getTime() < end; d.setUTCMonth(d.getUTCMonth() + 1)) {
      if (d.getTime() >= start) out.push({ label: new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(d), at: ((d.getTime() - start) / (end - start)) * 100 });
    }
    return out;
  });

  let editing = $state<{ orig: AbsencePeriod | null; draft: AbsencePeriod } | null>(null);
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name ?? '';

  function startNew(person: string) {
    editing = { orig: null, draft: created(absences, person, today, openFrom) };
  }

  async function save(next: AbsencePeriod) {
    const e = editing;
    editing = null;
    if (!e) return;
    await onchange(e.orig ? absences.map((x) => (x === e.orig ? next : x)) : [...absences, next]);
  }

  async function remove() {
    const e = editing;
    editing = null;
    if (e?.orig) await onchange(absences.filter((x) => x !== e.orig));
  }
</script>

<div class="tw">
  <div class="tl" role="group" aria-label={t('Absences on a time axis')}>
    <div class="lab head"></div>
    <div class="axis">
      {#each sprints as s, i (s.id)}
        <div class="sp" class:odd={i % 2 === 1} class:done={s.state === 'finished'} style:left="{pos(s.start)}%" style:width="{width(s.start, s.last)}%" title={`${s.id}: ${fmtDay(s.start)} – ${fmtDay(s.last)}`}>
          <span class="small data">{s.id}</span>
        </div>
      {/each}
      {#each months as m (m.at)}<span class="mo small muted" style:left="{m.at}%">{m.label}</span>{/each}
      <div class="today" style:left="{pos(today)}%" title={t('Today')}></div>
    </div>
    {#each shown as p (p.id)}
      <div class="lab">
        <span class="name">{p.name}</span>
        <button class="btn icon ghost" type="button" title={t('Add period')} aria-label={t('Add period for {name}', { name: p.name })} onclick={() => startNew(p.id)}><Icon name="add" size={16} /></button>
      </div>
      <div class="lane">
        {#each sprints as s, i (s.id)}
          <div class="sp" class:odd={i % 2 === 1} style:left="{pos(s.start)}%" style:width="{width(s.start, s.last)}%"></div>
        {/each}
        <div class="today" style:left="{pos(today)}%"></div>
        {#each absences.filter((a) => a.person === p.id && visible(a)) as a (a)}
          {@const lock = isLocked(a, openFrom)}
          <button
            type="button"
            class="bar data {lock ? 'past' : a.confirmed ? 'ok' : 'warn'}"
            style:left="{pos(a.from)}%"
            style:width="calc({width(a.from, a.to)}% - 2px)"
            title={`${fmtDay(a.from)} – ${fmtDay(a.to)}`}
            aria-label={t('Absence of {name}: {from} to {to}', { name: p.name, from: fmtDay(a.from), to: fmtDay(a.to) })}
            onclick={() => (editing = { orig: a, draft: a })}
          >
            {fmtShort(a.from)}–{fmtShort(a.to)}
          </button>
        {/each}
      </div>
    {/each}
  </div>
</div>
<div class="legend small muted">
  <span><i class="k ok"></i>{t('confirmed')}</span>
  <span><i class="k warn"></i>{t('announced')}</span>
  <span><i class="k past"></i>{t('finished')}</span>
</div>

{#if editing}
  <AbsenceDialog name={nameOf(editing.draft.person)} period={editing.draft} isNew={editing.orig === null} {openFrom} onsave={save} onremove={remove} onclose={() => (editing = null)} />
{/if}

<style>
  .tw {
    overflow-x: auto;
  }
  .tl {
    display: grid;
    grid-template-columns: 150px minmax(640px, 1fr);
    min-width: 790px;
  }
  .lab {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 4px;
    height: 40px;
    padding: 0 4px 0 8px;
    border-bottom: 1px solid var(--border);
  }
  .lab.head {
    height: 52px;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .axis,
  .lane {
    position: relative;
    border-bottom: 1px solid var(--border);
  }
  .axis {
    height: 52px;
  }
  .lane {
    height: 40px;
  }
  .sp {
    position: absolute;
    top: 0;
    bottom: 0;
    border-left: 1px solid var(--border);
  }
  .sp.odd {
    background: var(--surface-2);
  }
  .sp span {
    position: absolute;
    top: 4px;
    left: 4px;
    white-space: nowrap;
    color: var(--text-muted);
  }
  .sp.done span {
    opacity: 0.6;
  }
  .mo {
    position: absolute;
    top: 30px;
    padding-left: 4px;
  }
  .today {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--bad);
    z-index: 2;
  }
  .bar {
    position: absolute;
    top: 8px;
    height: 24px;
    padding: 0 6px;
    border: 1px solid transparent;
    border-radius: var(--r-ctl);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-align: left;
    cursor: pointer;
    z-index: 1;
    min-width: 22px;
  }
  .bar.ok {
    background: var(--ok-weak);
    color: var(--ok);
    border-color: var(--ok);
  }
  .bar.warn {
    background: var(--warn-weak);
    color: var(--warn);
    border-color: var(--warn);
  }
  .bar.past {
    background: var(--surface-3);
    color: var(--text-muted);
    border-color: var(--border-control);
  }
  .bar:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }
  .legend {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  .k {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 3px;
    margin-right: 4px;
    vertical-align: -2px;
    border: 1px solid;
  }
  .k.ok {
    background: var(--ok-weak);
    border-color: var(--ok);
  }
  .k.warn {
    background: var(--warn-weak);
    border-color: var(--warn);
  }
  .k.past {
    background: var(--surface-3);
    border-color: var(--border-control);
  }
</style>
