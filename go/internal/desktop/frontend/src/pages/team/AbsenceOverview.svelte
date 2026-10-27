<script lang="ts">
  // The planned absences as periods, one row each, past ones included. With `only` it lists one person
  // (inside the times panel), otherwise the whole team with a filter by person.
  // Only dates are stored, never a reason or kind of absence (data protection).
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { changed, created, isLocked as locked, touchesFinished } from '../../lib/team/absences';
  import { fmtDay } from '../../lib/team/format';
  import type { AbsencePeriod, Person } from '../../lib/types.team';

  interface Props {
    people: Person[];
    today: string;
    /** All periods of the team. */
    absences: AbsencePeriod[];
    /** First day of the first sprint that has not ended; earlier days belong to finished sprints. */
    openFrom: string;
    /** Id of the one person to show, null for the whole team. */
    only?: string | null;
    /** Saves the whole list of the team. */
    onchange: (list: AbsencePeriod[]) => void | Promise<void>;
  }
  let { people, today, absences, openFrom, only = null, onchange }: Props = $props();

  const names = $derived(new Map(people.map((p) => [p.id, p.name])));
  let who = $state('');
  const shown = $derived(only ?? who);
  const rows = $derived(
    absences
      .filter((a) => names.has(a.person) && (shown === '' || a.person === shown))
      .sort((a, b) => (names.get(a.person) ?? '').localeCompare(names.get(b.person) ?? '') || a.from.localeCompare(b.from)),
  );
  let adding = $state('');

  function edit(a: AbsencePeriod, patch: Partial<AbsencePeriod>, input: HTMLInputElement | null = null) {
    const next = changed(a, patch, openFrom);
    if (!next) {
      if (input) input.value = patch.from !== undefined ? a.from : a.to; // keep the field as saved
      return;
    }
    return onchange(absences.map((x) => (x === a ? next : x)));
  }

  function add(person: string) {
    adding = '';
    if (!person) return;
    return onchange([...absences, created(absences, person, today, openFrom)]);
  }
</script>

{#if !only}
  <div class="row filter">
    <select class="input" aria-label={t('Show person')} bind:value={who}>
      <option value="">{t('All people')}</option>
      {#each people as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
    </select>
  </div>
{/if}
{#if rows.length}
  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          {#if !only}<th>{t('Name')}</th>{/if}
          <th>{t('From')}</th>
          <th>{t('To')}</th>
          <th>{t('Status')}</th>
          <th><span class="sr-only">{t('Actions')}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each rows as a (a)}
          {@const lock = locked(a, openFrom)}
          <tr class:past={a.to < today}>
            {#if !only}<td>{names.get(a.person)}</td>{/if}
            <td><input class="input data date" type="date" value={a.from} min={openFrom || undefined} disabled={lock} aria-label={t('First day {name}', { name: names.get(a.person) ?? '' })} onchange={(e) => edit(a, { from: e.currentTarget.value }, e.currentTarget)} /></td>
            <td><input class="input data date" type="date" value={a.to} disabled={lock} aria-label={t('Last day {name}', { name: names.get(a.person) ?? '' })} onchange={(e) => edit(a, { to: e.currentTarget.value }, e.currentTarget)} /></td>
            <td>
              <button
                type="button"
                class="chip {a.confirmed ? 'ok' : 'warn'}"
                aria-pressed={a.confirmed}
                disabled={lock}
                title={a.confirmed ? t('Confirmed. Click to mark as announced.') : t('Announced. Click to confirm.')}
                onclick={() => edit(a, { confirmed: !a.confirmed })}
              >
                <Icon name={a.confirmed ? 'lock' : 'lock_open'} size={14} />{a.confirmed ? t('confirmed') : t('announced')}
              </button>
              {#if lock}
                <span class="chip filter small" title={t('Lies in finished sprints. They stay as they are.')}><Icon name="history" size={14} />{t('finished')}</span>
              {:else if touchesFinished(a, openFrom)}
                <span class="chip filter small" title={t('Days in finished sprints stay as they are; a change only reaches the open sprints.')}><Icon name="info" size={14} />{t('partly finished')}</span>
              {/if}
            </td>
            <td class="actions">
              <button
                class="btn icon ghost"
                type="button"
                disabled={lock}
                aria-label={t('Delete absence {from} to {to}', { from: fmtDay(a.from), to: fmtDay(a.to) })}
                title={t('Delete')}
                onclick={() => onchange(absences.filter((x) => x !== a))}
              >
                <Icon name="delete" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else}
  <p class="muted">{t('No absences planned.')}</p>
{/if}
<div class="row add">
  {#if only}
    <button class="btn" type="button" onclick={() => add(only)}><Icon name="add" />{t('Add period')}</button>
  {:else}
    <select class="input" aria-label={t('Person')} bind:value={adding} onchange={() => add(adding)}>
      <option value="">{t('Add period for…')}</option>
      {#each people as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
    </select>
  {/if}
</div>

<style>
  .date {
    width: 138px;
  }
  .past {
    opacity: 0.6;
  }
  .filter {
    margin-bottom: 8px;
  }
  .add {
    margin-top: 8px;
  }
  .actions {
    white-space: nowrap;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
