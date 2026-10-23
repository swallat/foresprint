<script lang="ts">
  // Absences of several sprints in one grid (flows.md decisions 1 and 23). Used on Prepare and
  // on Team > People. Days are typed in (half days, comma or point); an entry is announced (open
  // lock) until the sprint is frozen ("Freeze": closed lock, every empty cell counts as 0 days).
  // A cleared value stays visible, struck through, with an undo button until the next save.
  // Edits are written at once through the API; the grid only shows what the API answered.
  import { untrack } from 'svelte';
  import { api } from '../api';
  import { app, toast } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { AbsenceCell, AbsenceColumn, AbsenceGrid, AbsenceRow } from '../types.sprints';
  import { formatDate } from '../format';
  import { days, parseDays } from './format';

  interface Props {
    team: string;
    /** First sprint of the grid, "" = the running or next sprint. */
    from?: string;
    count?: number;
    /** Sprint marked as the one in focus. */
    focus?: string;
    /** Show capacity and Forecast PLAN under the entries. */
    totals?: boolean;
    /** Called with the changed column after every edit, so that a page can refresh its figures. */
    onchange?: (column: AbsenceColumn) => void;
  }
  let { team, from = '', count = 4, focus = '', totals = true, onchange }: Props = $props();

  let grid = $state<AbsenceGrid | undefined>();
  let error = $state('');
  /** Cleared values by "sprint|person", restorable until the next save. */
  let ghosts = $state<Record<string, number>>({});
  
  let seq = 0;
  async function load() {
    const mine = ++seq;
    try {
      const next = await api.AbsenceGrid(team, from, count);
      if (mine !== seq) return; // a newer request is on its way
      grid = next;
      error = '';
    } catch (e) {
      if (mine === seq) error = String(e);
    }
  }

  // Reload when team, start or width change; not when the grid itself changes.
  $effect(() => {
    void [team, from, count];
    untrack(load);
  });

  // A save ends the undo for cleared values.
  $effect(() => {
    if (app.status.storage === 'saved') untrack(() => (ghosts = {}));
  });

  const col = (i: number) => grid!.columns[i] as AbsenceColumn;
  const rowAt = (i: number) => grid!.rows[i] as AbsenceRow;
  const cellAt = (ri: number, ci: number) => rowAt(ri).cells[ci] as AbsenceCell;
  const nameOf = (id: string) => grid?.columns.find((c) => c.id === id)?.name ?? id;

  // Every write goes through one queue: edits are applied in the order they were made, so a
  // freeze right after typing cannot overtake the typed days.
  let queue: Promise<unknown> = Promise.resolve();
  function enqueue<T>(job: () => Promise<T>): Promise<T> {
    const run = queue.then(job, job);
    queue = run.catch(() => undefined);
    return run;
  }

  function replaceColumn(next: AbsenceColumn) {
    if (!grid) return;
    grid.columns = grid.columns.map((c) => (c.id === next.id ? next : c));
    onchange?.(next);
  }

  async function commit(ci: number, ri: number, input: HTMLInputElement) {
    if (!grid) return;
    const cell = cellAt(ri, ci);
    const sprint = col(ci).id;
    const person = rowAt(ri).person;
    const key = `${sprint}|${person}`;
    const value = parseDays(input.value);
    if (Number.isNaN(value) || value < 0) {
      toast(t('Enter a number of days from 0 to {max}.', { max: days(cell.max) }), 'bad');
      input.value = cell.days ? days(cell.days) : '';
      return;
    }
    const shown = Math.min(cell.max, Math.round(value * 2) / 2);
    if (shown === cell.days) {
      input.value = cell.days ? days(cell.days) : '';
      return;
    }
    if (shown === 0) ghosts[key] = cell.days;
    else delete ghosts[key];
    cell.days = shown;
    if (shown === 0 && cell.state !== 'confirmed') cell.state = 'empty';
    else if (cell.state === 'empty') cell.state = 'announced';
    input.value = shown ? days(shown) : '';
    if (shown !== value) toast(t('Set to {days} days (half days, at most {max}).', { days: days(shown), max: days(cell.max) }));
    try {
      await enqueue(async () => replaceColumn(await api.SetAbsence(team, sprint, person, shown)));
    } catch (e) {
      delete ghosts[key];
      toast(String(e), 'bad');
      await load();
    }
  }

  async function restore(ci: number, ri: number) {
    if (!grid) return;
    const sprint = col(ci).id;
    const person = rowAt(ri).person;
    const key = `${sprint}|${person}`;
    const value = ghosts[key] ?? 0;
    delete ghosts[key];
    cellAt(ri, ci).days = value;
    try {
      await enqueue(async () => replaceColumn(await api.SetAbsence(team, sprint, person, value)));
    } catch (e) {
      toast(String(e), 'bad');
      await load();
    }
  }

  async function lockCell(ci: number, ri: number, confirmed: boolean) {
    if (!grid) return;
    const sprint = col(ci).id;
    const person = rowAt(ri).person;
    cellAt(ri, ci).state = confirmed ? 'confirmed' : 'announced';
    try {
      await enqueue(async () => replaceColumn(await api.SetAbsenceConfirmed(team, sprint, person, confirmed)));
    } catch (e) {
      toast(String(e), 'bad');
      await load();
    }
  }

  async function freeze(sprint: string) {
    try {
      await enqueue(async () => replaceColumn(await api.FreezeAbsences(team, sprint)));
      await load(); // every cell of the sprint is confirmed now
      toast(t('Allocation of {sprint} frozen. Empty cells count as 0 days.', { sprint: nameOf(sprint) }), 'ok', {
        label: t('Undo'),
        run: () => void unfreeze(sprint, false),
      });
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  async function unfreeze(sprint: string, say = true) {
    try {
      await enqueue(async () => replaceColumn(await api.UnfreezeAbsences(team, sprint)));
      await load();
      if (say) toast(t('Allocation of {sprint} is open again. Entries count as announced.', { sprint: nameOf(sprint) }));
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  /** Enter saves the cell and moves to the same sprint, next person. */
  function onkey(e: KeyboardEvent, ci: number, ri: number) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const input = e.currentTarget as HTMLInputElement;
    const list = [...document.querySelectorAll<HTMLInputElement>(`[data-abs-col="${col(ci).id}"]`)];
    const next = list[list.indexOf(input) + 1];
    if (next) next.focus();
    else void commit(ci, ri, input); // last person: no blur follows, so save here
  }

  const stateText = (s: AbsenceColumn['state']) =>
    s === 'confirmed' ? t('Confirmed') : s === 'announced' ? t('Announced') : t('Not entered');
</script>

{#if error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
{:else if grid}
  <div class="tw">
    <table class="t abs" aria-label={t('Absences in person days')}>
      <thead>
        <tr>
          <th scope="col">{t('Person')}</th>
          <th scope="col" class="num">{t('FTE')}</th>
          {#each grid.columns as c (c.id)}
            <th scope="col" class="sc" class:focus={c.id === focus}>
              <span class="data">{c.name}</span><br />
              <span class="muted small">{formatDate(c.start)}</span>
              <span class="chip small {c.state === 'confirmed' ? 'ok' : c.state === 'announced' ? 'warn' : ''}">
                {#if c.state !== 'unknown'}<Icon name={c.state === 'confirmed' ? 'lock' : 'lock_open'} size={14} />{/if}
                {stateText(c.state)}
              </span>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each grid.rows as row, ri (row.person)}
          <tr>
            <td>{row.name}</td>
            <td class="num">{days(row.fte)}</td>
            {#each row.cells as cell, ci (col(ci).id)}
              {@const c = col(ci)}
              {@const key = `${c.id}|${row.person}`}
              {@const ghost = ghosts[key]}
              <td class="sc" class:focus={c.id === focus}>
                {#if !cell.active}
                  <span class="muted" title={t('Not in the team during this sprint.')}>–</span>
                {:else}
                  <div class="cell {cell.state === 'confirmed' && cell.days > 0 ? 'c' : cell.state === 'announced' ? 'a' : ''}" class:g={ghost !== undefined}>
                    <input
                      class="input data"
                      inputmode="decimal"
                      data-abs-col={c.id}
                      value={cell.days ? days(cell.days) : ''}
                      placeholder={ghost !== undefined ? days(ghost) : ''}
                      aria-label={t('{person}, {sprint}: absence in days', { person: row.name, sprint: c.name })}
                      disabled={c.past}
                      onchange={(e) => commit(ci, ri, e.currentTarget)}
                      onkeydown={(e) => onkey(e, ci, ri)}
                    />
                    {#if ghost !== undefined}
                      <button class="btn icon ghost" type="button" disabled={c.past} title={t('Restore {days} days', { days: days(ghost) })} aria-label={t('Restore {days} days', { days: days(ghost) })} onclick={() => restore(ci, ri)}>
                        <Icon name="undo" size={16} />
                      </button>
                    {:else if cell.days > 0}
                      {@const text = c.state === 'confirmed'
                        ? t('Frozen with the sprint. Open the sprint to change the lock.')
                        : cell.state === 'confirmed'
                          ? t('Confirmed. A click makes it announced again.')
                          : t('Announced. A click confirms it.')}
                      <button
                        class="btn icon ghost lock"
                        type="button"
                        disabled={c.past || c.state === 'confirmed'}
                        title={text}
                        aria-label={text}
                        onclick={() => lockCell(ci, ri, cell.state !== 'confirmed')}
                      >
                        <Icon name={cell.state === 'confirmed' ? 'lock' : 'lock_open'} size={16} />
                      </button>
                    {/if}
                  </div>
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
        {#if totals}
          <tr class="sum">
            <td>{t('Absent in total')}</td>
            <td></td>
            {#each grid.columns as c (c.id)}<td class="sc data" class:focus={c.id === focus}>{days(c.absent)} {t('PD')}</td>{/each}
          </tr>
          <tr class="sum">
            <td>{t('Capacity')}</td>
            <td></td>
            {#each grid.columns as c (c.id)}<td class="sc data" class:focus={c.id === focus}>{days(c.capacity)} {t('PD')}</td>{/each}
          </tr>
          <tr class="sum">
            <td>{t('Forecast PLAN')}</td>
            <td></td>
            {#each grid.columns as c (c.id)}
              <td class="sc data fc" class:focus={c.id === focus}>{c.plan === null ? '–' : days(c.plan)}</td>
            {/each}
          </tr>
        {/if}
        <tr>
          <td>{t('Allocation')}</td>
          <td></td>
          {#each grid.columns as c, ci (c.id)}
            <td class="sc" class:focus={c.id === focus}>
              {#if c.past}
                <span class="muted small">{t('Closed')}</span>
              {:else if c.state === 'confirmed'}
                <button class="btn ghost frozen" type="button" onclick={() => unfreeze(c.id)} title={c.entries ? t('{n} entries confirmed, all others 0 days. A click opens the sprint again.', { n: c.entries }) : t('Nobody is absent. A click opens the sprint again.')}>
                  <Icon name="lock" size={16} />{t('Frozen')}
                </button>
              {:else}
                <button class="btn" type="button" data-tour="prepare-freeze" onclick={() => freeze(c.id)} title={c.entries ? t('Confirm all entries; empty cells count as 0 days.') : t('Nobody is absent: empty cells count as 0 days.')}>
                  <Icon name="lock_open" size={16} />{c.entries ? t('Freeze') : t('Nobody absent')}
                </button>
              {/if}
            </td>
          {/each}
        </tr>
      </tbody>
    </table>
  </div>
{:else}
  <p class="muted">{t('Loading …')}</p>
{/if}

<style>
  th.sc,
  td.sc {
    text-align: center;
  }
  th.focus {
    box-shadow: inset 0 2px 0 var(--primary);
  }
  td.focus {
    background: color-mix(in srgb, var(--primary) 7%, transparent);
  }
  /* The input is always centred under the column head; the lock or undo button hangs to its
     right, so a cell with and without a lock line up. */
  .cell {
    position: relative;
    display: block;
    width: 56px;
    height: 28px;
    margin: 0 auto;
  }
  .cell :global(.btn.icon) {
    position: absolute;
    left: 100%;
    top: 0;
    height: 28px;
    margin: 0 0 0 2px; /* the table rule .t td .btn.icon would shift it by -4px */
    display: grid;
    place-items: center;
    padding: 0;
    line-height: 1;
  }
  .cell .input {
    display: block;
    width: 56px;
    height: 28px;
    text-align: right;
    padding: 0 8px;
  }
  .cell.a .input {
    background: var(--warn-weak);
    border-color: var(--warn);
  }
  .cell.c .input {
    background: var(--ok-weak);
    border-color: var(--ok);
  }
  .cell.a .lock {
    color: var(--warn);
  }
  .cell.c .lock {
    color: var(--ok);
  }
  .cell.g .input {
    border-style: dashed;
  }
  .cell.g .input::placeholder {
    color: var(--text-muted);
    text-decoration: line-through;
    opacity: 1;
  }
  .fc {
    color: var(--forecast);
  }
  .frozen {
    color: var(--ok);
  }
  td .btn:not(.icon) {
    width: 100%;
    max-width: 170px;
    justify-content: center;
  }
</style>
