<script lang="ts">
  // Times of one person: the periods in the team with their share, the leaving day, and removal
  // for someone who was added by mistake. All dates can be corrected, also afterwards;
  // capacity and forecast use the period that applies to each sprint.
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import SidePanel from '../../lib/ui/SidePanel.svelte';
  import { fmtNum, parseNum } from '../../lib/team/format';
  import { leaving, periodProblem, withLeaving, withNewShare } from '../../lib/team/people';
  import type { Person } from '../../lib/types.team';

  interface Props {
    person: Person;
    today: string;
    onclose: () => void;
    onsave: (next: Person, message: string) => void | Promise<void>;
    onremove: () => void | Promise<void>;
  }
  let { person, today, onclose, onsave, onremove }: Props = $props();

  // svelte-ignore state_referenced_locally
  let draft = $state<Person>(structuredClone($state.snapshot(person)));
  const problem = $derived(periodProblem(draft));
  const message = $derived(
    {
      from: t('Enter the first day of every period.'),
      order: t('The end of a period lies before its start.'),
      fte: t('The share must be between 0.1 and 1.0.'),
      overlap: t('The periods overlap.'),
      '': '',
    }[problem],
  );
  const last = $derived(draft.memberships.length - 1);
  const past = $derived(draft.memberships.some((m) => m.from < today));

  function newShare() {
    const lastFrom = draft.memberships[last]?.from ?? today;
    const from = lastFrom < today ? today : lastFrom.slice(0, 8) + '28';
    draft = withNewShare(draft, from, draft.memberships[last]?.fte ?? 1);
  }
</script>

<SidePanel title={t('Times: {name}', { name: person.name })} {onclose}>
  <p class="small muted">
    {t('One period per section with its own share. The first "from" is the entry. All dates can be corrected, also afterwards; capacity and forecast calculate each sprint with the period that applies.')}
  </p>
  <div class="tw">
    <table class="t">
      <thead>
        <tr><th>{t('From')}</th><th>{t('To')}</th><th class="num">{t('FTE')}</th></tr>
      </thead>
      <tbody>
        {#each draft.memberships as m, i (i)}
          <tr>
            <td><input class="input data date" type="date" bind:value={m.from} aria-label={i ? t('Period {n} from', { n: i + 1 }) : t('Entry')} /></td>
            <td>
              {#if i < last}
                <span class="small muted">{t('until the next')}</span>
              {:else}
                <input class="input data date" type="date" bind:value={m.to} aria-label={t('Period to, empty = open')} />
              {/if}
            </td>
            <td class="num">
              <input
                class="input data fte"
                inputmode="decimal"
                value={fmtNum(m.fte)}
                aria-label={t('FTE of period {n}', { n: i + 1 })}
                onchange={(e) => (m.fte = parseNum(e.currentTarget.value))}
              />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  {#if message}<p class="small bad" role="alert">{message}</p>{/if}
  {#if past}
    <p class="small muted">{t('If a change lies before today, Foresprint recalculates capacity and normalized velocity of the closed sprints it touches. The measured velocity stays as it was entered in the review.')}</p>
  {/if}
  <div class="row">
    <button class="btn" type="button" onclick={newShare}><Icon name="add" />{t('New share from a date')}</button>
  </div>

  <h3>{t('Leaving')}</h3>
  <p class="small muted">
    {t('Last working day in the team. Until then the person counts for capacity; afterwards they are listed under Former and stay in the history, in minutes and in the velocity of past sprints.')}
  </p>
  <div class="row bottom">
    <div class="field">
      <label for="tp-until">{t('Last day')}</label>
      <input class="input data date" type="date" id="tp-until" value={leaving(draft)} onchange={(e) => (draft = withLeaving(draft, e.currentTarget.value))} />
    </div>
  </div>

  <div class="row">
    <button class="btn primary" type="button" disabled={problem !== ''} onclick={() => onsave(draft, t('Times of {name} saved.', { name: person.name }))}>
      <Icon name="check" />{t('Apply')}
    </button>
    <button class="btn ghost" type="button" onclick={onclose}>{t('Cancel')}</button>
  </div>

  <h3>{t('Remove')}</h3>
  <p class="small muted">
    {person.used
      ? t('Not possible: the person already stands in sprints. Enter a leaving day instead.')
      : t('Only for people added by mistake who have no history.')}
  </p>
  <div class="row">
    <button class="btn danger" type="button" disabled={person.used} onclick={onremove}><Icon name="person_remove" />{t('Remove person')}</button>
  </div>
</SidePanel>

<style>
  h3 {
    margin: 16px 0 0;
    font: 600 14px/20px var(--font-ui);
  }
  .date {
    width: 138px;
  }
  .fte {
    width: 64px;
    text-align: right;
  }
  .bad {
    color: var(--bad);
    margin: 0;
  }
  .bottom {
    align-items: flex-end;
  }
</style>
