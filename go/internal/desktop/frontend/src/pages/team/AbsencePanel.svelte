<script lang="ts">
  // Planned absences of one person as periods: first and last day, announced or confirmed.
  // Only dates are stored, never a reason or kind of absence (data protection).
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import SidePanel from '../../lib/ui/SidePanel.svelte';
  import { fmtDay } from '../../lib/team/format';
  import type { AbsencePeriod, Person } from '../../lib/types.team';

  interface Props {
    person: Person;
    today: string;
    /** All periods of the team; the panel shows and edits the ones of this person. */
    absences: AbsencePeriod[];
    onclose: () => void;
    /** Saves the whole list of the team. */
    onchange: (list: AbsencePeriod[]) => void | Promise<void>;
  }
  let { person, today, absences, onclose, onchange }: Props = $props();

  const mine = $derived(absences.filter((a) => a.person === person.id).sort((a, b) => a.from.localeCompare(b.from)));
  const others = $derived(absences.filter((a) => a.person !== person.id));

  function replaceMine(list: AbsencePeriod[]) {
    return onchange([...others, ...list]);
  }

  function edit(a: AbsencePeriod, patch: Partial<AbsencePeriod>, input?: HTMLInputElement) {
    const next = { ...a, ...patch };
    if (patch.from && patch.from > next.to) next.to = patch.from; // the period moves with its first day
    if (next.from === '' || next.to === '' || next.to < next.from) {
      if (input) input.value = patch.from !== undefined ? a.from : a.to; // keep the field as saved
      return;
    }
    return replaceMine(mine.map((x) => (x === a ? next : x)));
  }

  function add() {
    const from = mine.length ? mine[mine.length - 1]!.to : today;
    const day = new Date(`${from}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() + (mine.length ? 7 : 0));
    const iso = day.toISOString().slice(0, 10);
    return replaceMine([...mine, { person: person.id, from: iso, to: iso, confirmed: false }]);
  }
</script>

<SidePanel title={t('Absences: {name}', { name: person.name })} {onclose}>
  <p class="small muted">
    {t('Planned absences as periods, first to last day. Foresprint turns them into days per sprint. Only the dates are stored, never a reason.')}
  </p>
  {#if mine.length}
    <div class="tw">
      <table class="t">
        <thead>
          <tr><th>{t('From')}</th><th>{t('To')}</th><th>{t('Status')}</th><th><span class="sr-only">{t('Actions')}</span></th></tr>
        </thead>
        <tbody>
          {#each mine as a, i (i)}
            <tr class:past={a.to < today}>
              <td><input class="input data date" type="date" value={a.from} aria-label={t('First day')} onchange={(e) => edit(a, { from: e.currentTarget.value }, e.currentTarget)} /></td>
              <td><input class="input data date" type="date" value={a.to} aria-label={t('Last day')} onchange={(e) => edit(a, { to: e.currentTarget.value }, e.currentTarget)} /></td>
              <td>
                <button
                  type="button"
                  class="chip {a.confirmed ? 'ok' : 'warn'}"
                  aria-pressed={a.confirmed}
                  title={a.confirmed ? t('Confirmed. Click to mark as announced.') : t('Announced. Click to confirm.')}
                  onclick={() => edit(a, { confirmed: !a.confirmed })}
                >
                  <Icon name={a.confirmed ? 'lock' : 'lock_open'} size={14} />{a.confirmed ? t('confirmed') : t('announced')}
                </button>
              </td>
              <td>
                <button
                  class="btn icon ghost"
                  type="button"
                  aria-label={t('Delete absence {from} to {to}', { from: fmtDay(a.from), to: fmtDay(a.to) })}
                  title={t('Delete')}
                  onclick={() => replaceMine(mine.filter((x) => x !== a))}
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
  <div class="row">
    <button class="btn" type="button" onclick={add}><Icon name="add" />{t('Add period')}</button>
  </div>
</SidePanel>

<style>
  .date {
    width: 138px;
  }
  .past {
    opacity: 0.6;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
