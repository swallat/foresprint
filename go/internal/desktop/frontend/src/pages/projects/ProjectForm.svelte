<script lang="ts">
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { HandLight, MilestoneInput, ProjectInput, ProjectsView, ProjectView } from '../../lib/types.projects';
  import { month } from './format';
  import RuleEditor from '../../lib/rules/RuleEditor.svelte';
  import SidePanel from './SidePanel.svelte';
  import { addMonths } from './timeline';

  interface Props {
    view: ProjectsView;
    /** The project to change; none creates a new one. */
    project?: ProjectView;
    onclose: () => void;
    onsaved: (id: string) => void;
  }
  let { view, project, onclose, onsaved }: Props = $props();

  // The form starts from the project once; later changes of the page data do not overwrite input.
  /* svelte-ignore state_referenced_locally */
  const p = project;
  let name = $state(p?.name ?? '');
  let products = $state<string[]>(p?.products ?? (view.products.length === 1 ? [view.products[0]!.id] : []));
  let start = $state(p?.start ?? '');
  let end = $state(p?.end ?? addMonths(view.today, 3));
  let booked = $state(p?.booked === null || p?.booked === undefined ? '' : String(p.booked));
  let used = $state(p?.usedHand === null || p?.usedHand === undefined ? '' : String(p.usedHand));
  let contact = $state(p?.contact ?? '');
  let usedMonths = $state<Record<string, string>>(Object.fromEntries((p?.months ?? []).filter((m) => m.used !== null).map((m) => [m.month, String(m.used)])));
  const LIGHTS: { value: HandLight; label: string }[] = [
    { value: '', label: t('Derive from tickets') },
    { value: 'green', label: t('on track') },
    { value: 'yellow', label: t('tight') },
    { value: 'red', label: t('at risk') },
  ];
  let openScope = $state(p?.openScope === null || p?.openScope === undefined ? '' : String(p.openScope));
  let rule = $state(p?.rule ?? '');
  let ruleValid = $state(true);
  let note = $state(p?.note ?? '');
  let milestones = $state<MilestoneInput[]>(
    p ? p.milestones.map((m) => ({ id: m.id, name: m.name, date: m.date, tickets: m.tickets, light: m.hand })) : [{ id: '', name: '', date: addMonths(view.today, 2), tickets: [], light: '' }],
  );
  let months = $state<Record<string, string>>(Object.fromEntries((p?.months ?? []).filter((m) => m.booked > 0).map((m) => [m.month, String(m.booked)])));
  let error = $state('');
  let busy = $state(false);
  const filled = (m: Record<string, string>) => Object.fromEntries(Object.entries(m).filter(([, v]) => v !== ''));
  const snapshot = () => JSON.stringify([name, products, start, end, booked, used, contact, openScope, rule, note, milestones, filled(months), filled(usedMonths)]);
  const initial = snapshot();
  const dirty = $derived(snapshot() !== initial);

  // Months of the contingent: from the start (or today) to the end, at most three years.
  const monthKeys = $derived.by(() => {
    const keys = new Set(Object.keys(months));
    const first = (start || view.today).slice(0, 7);
    const last = (end || addMonths(view.today, 3)).slice(0, 7);
    for (let m = `${first}-01`, i = 0; m.slice(0, 7) <= last && i < 36; m = addMonths(m, 1), i++) keys.add(m.slice(0, 7));
    return [...keys].sort();
  });
  const hasTickets = $derived(view.source !== 'none');

  function toggle(id: string): void {
    products = products.includes(id) ? products.filter((x) => x !== id) : [...products, id];
  }

  const number = (text: string): number | null => {
    const clean = text.trim().replace(',', '.');
    if (clean === '') return null;
    const n = Number(clean);
    return Number.isFinite(n) ? n : NaN;
  };

  async function submit(e: SubmitEvent): Promise<void> {
    e.preventDefault();
    error = '';
    const total = number(booked);
    const scope = number(openScope);
    const spent = number(used);
    if (Number.isNaN(total) || Number.isNaN(scope) || Number.isNaN(spent) || (spent !== null && spent < 0) || (total !== null && total < 0)) {
      error = t('Please enter the amounts as numbers from 0.');
      return;
    }
    const perMonth: Record<string, number> = {};
    for (const [ym, text] of Object.entries(months)) {
      const v = number(text);
      if (v === null) continue;
      if (Number.isNaN(v) || v < 0) {
        error = t('Please enter the amounts as numbers from 0.');
        return;
      }
      perMonth[ym] = v;
    }
    const spentMonths: Record<string, number> = {};
    for (const [ym, text] of Object.entries(usedMonths)) {
      const v = number(text);
      if (v === null) continue;
      if (Number.isNaN(v) || v < 0) {
        error = t('Please enter the amounts as numbers from 0.');
        return;
      }
      spentMonths[ym] = v;
    }
    const input: ProjectInput = {
      id: p?.id ?? '',
      name,
      products,
      start,
      end,
      note,
      rule,
      booked: total,
      used: spent,
      contact,
      months: perMonth,
      usedMonths: spentMonths,
      openScope: scope,
      milestones: milestones.map((m) => ({ ...m, name: m.name.trim() || t('Milestone') })),
    };
    busy = true;
    try {
      const id = await api.SaveProject(app.team, input);
      toast(p ? t('{name} saved.', { name }) : t('Project {name} created.', { name }), 'ok', {
        label: t('Undo'),
        run: () => void api.UndoProjects(app.team).then(() => onsaved('')),
      });
      onsaved(id);
    } catch (err) {
      error = String(err).replace(/^Error: /, '');
    } finally {
      busy = false;
    }
  }
</script>

<SidePanel title={p ? t('Edit project') : t('New project')} {onclose} {dirty}>
  {#snippet children(askClose)}
  <form class="stack" onsubmit={submit} novalidate>
    <div class="banner info">
      <Icon name="cloud_off" />
      <div class="grow">{t('Works without a tracker and offline. The project is stored in the team data and shared with Save.')}</div>
    </div>

    <div class="field">
      <label for="pf-name">{t('Name')}</label>
      <input class="input" id="pf-name" bind:value={name} placeholder={t('e.g. New partner portal')} />
    </div>

    {#if view.products.length > 0}
      <fieldset>
        <legend class="small muted">{t('Products (several possible)')}</legend>
        <div class="row">
          {#each view.products as pr (pr.id)}
            <button type="button" class="chip filter" class:on={products.includes(pr.id)} aria-pressed={products.includes(pr.id)} onclick={() => toggle(pr.id)}>
              {pr.name}
            </button>
          {/each}
        </div>
      </fieldset>
    {/if}

    <div class="row">
      <div class="field">
        <label for="pf-start">{t('Start date (optional)')}</label>
        <input class="input data" id="pf-start" type="date" bind:value={start} />
      </div>
      <div class="field">
        <label for="pf-end">{t('End date')}</label>
        <input class="input data" id="pf-end" type="date" bind:value={end} />
      </div>
    </div>

    <fieldset>
      <legend class="small muted">{t('Milestones (date, tickets optional)')}</legend>
      <div class="stack">
        {#each milestones as m, i (i)}
          <div class="ms">
            <input class="input" aria-label={t('Milestone name')} placeholder={t('Name')} bind:value={m.name} />
            <input class="input data" type="date" aria-label={t('Milestone date')} bind:value={m.date} />
            <select class="input" aria-label={t('Traffic light of the milestone')} bind:value={m.light}>
              {#each LIGHTS as l (l.value)}<option value={l.value}>{l.label}</option>{/each}
            </select>
            <button type="button" class="btn icon ghost" aria-label={t('Remove milestone')} onclick={() => (milestones = milestones.filter((_, k) => k !== i))}>
              <Icon name="close" />
            </button>
            {#if hasTickets}
              <input
                class="input data tickets"
                aria-label={t('Tickets of the milestone')}
                placeholder={t('Tickets, separated by commas (optional)')}
                value={m.tickets.join(', ')}
                onchange={(e) => (m.tickets = e.currentTarget.value.split(/[\s,;]+/).filter(Boolean))}
              />
            {/if}
          </div>
        {/each}
        <div>
          <button type="button" class="btn" onclick={() => (milestones = [...milestones, { id: '', name: '', date: end || view.today, tickets: [], light: '' }])}>
            <Icon name="add" />{t('Milestone')}
          </button>
        </div>
      </div>
    </fieldset>

    <div class="field">
      <label for="pf-booked">{t('Contingent in total (person days)')}</label>
      <input class="input data narrow" id="pf-booked" inputmode="decimal" bind:value={booked} />
    </div>
    <div class="field">
      <label for="pf-used">{t('Used so far (person days, entered by hand)')}</label>
      <input class="input data narrow" id="pf-used" inputmode="decimal" bind:value={used} />
    </div>
    <details>
      <summary>{t('Split per month (optional)')}</summary>
      <div class="stack months">
        {#each monthKeys as ym (ym)}
          <div class="row">
            <label class="muted" for="pf-m-{ym}">{month(ym)}</label>
            <input class="input data narrow" id="pf-m-{ym}" inputmode="decimal" placeholder={t('PD')} bind:value={months[ym]} />
            <input class="input data narrow" aria-label={t('Used in {month}', { month: month(ym) })} inputmode="decimal" placeholder={t('used')} bind:value={usedMonths[ym]} />
          </div>
        {/each}
        <span class="small muted">{t('Leave empty when only the total is booked.')}</span>
      </div>
    </details>

    {#if view.source === 'none'}
      <div class="field">
        <label for="pf-scope">{t('Open scope (points)')}</label>
        <input class="input data narrow" id="pf-scope" inputmode="decimal" bind:value={openScope} />
        <span class="small muted">{t('Without tickets you keep the open scope by hand, for example after each review.')}</span>
      </div>
    {:else if view.source === 'tracker'}
      <RuleEditor team={app.team} owner={{ kind: 'project', id: p?.id ?? '' }} name={name || t('New project')} bind:value={rule} bind:valid={ruleValid} allowEmpty />
    {/if}

    <div class="field">
      <label for="pf-contact">{t('Contact person (optional)')}</label>
      <input class="input" id="pf-contact" bind:value={contact} />
    </div>

    <div class="field">
      <label for="pf-note">{t('Note')}</label>
      <textarea class="input" id="pf-note" rows="2" bind:value={note} placeholder={t('e.g. contact person, agreements')}></textarea>
    </div>

    {#if error}<div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>{/if}
    <div class="row">
      <button class="btn primary" type="submit" disabled={busy || !ruleValid}><Icon name="check" />{p ? t('Save project') : t('Create project')}</button>
      <button class="btn ghost" type="button" onclick={askClose}>{t('Cancel')}</button>
    </div>
  </form>
  {/snippet}
</SidePanel>

<style>
  fieldset {
    border: 0;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ms {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto 32px;
    gap: 6px;
    align-items: center;
  }
  .ms .tickets {
    grid-column: 1 / -1;
  }
  .narrow {
    width: 120px;
  }
  .months label {
    width: 88px;
  }
  summary {
    cursor: pointer;
  }
</style>
