<script lang="ts">
  import { onMount } from 'svelte';
  import { app, loadFeatures, toast } from '../../lib/app.svelte';
  import { api } from '../../lib/api';
  import { t } from '../../lib/i18n.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { TeamSettings } from '../../lib/types.settings';
  import type { Region } from '../../lib/types.setup';
  import ChangesCard from '../../lib/settings/ChangesCard.svelte';
  import NumInput from '../../lib/settings/NumInput.svelte';
  import Switch from '../../lib/settings/Switch.svelte';
  import { changes, parseNumber, type Field } from '../../lib/settings/diff';
  import ArchiveCard from './ArchiveCard.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import Icon from '../../lib/Icon.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  let applied = $state<TeamSettings>();
  let draft = $state<TeamSettings>();
  let busy = $state(false);
  let query = $state('');
  let newName = $state('');
  let factorText = $state('');
  let regions = $state<Region[]>([]);

  async function load(team: string): Promise<void> {
    applied = draft = undefined;
    if (!team) return;
    try {
      const s = await api.TeamSettings(team);
      if (team !== app.team) return; // the team changed while the answer was on its way
      applied = s;
      draft = structuredClone(s);
      factorText = s.factor === null ? '' : String(s.factor).replace('.', ',');
    } catch (e) {
      toast(String(e), 'bad');
    }
  }
  $effect(() => {
    void load(app.team);
  });
  onMount(async () => {
    try {
      regions = await api.SetupRegions();
    } catch (e) {
      toast(String(e), 'bad');
    }
  });
  const country = $derived(regions.find((r) => r.country === draft?.country));
  const countryName = (code: unknown) => regions.find((r) => r.country === code)?.name ?? String(code);

  const trends = $derived([
    ['flat', t('Flat (default)')],
    ['linear', t('Linear')],
    ['classic', t('Classic')],
  ]);
  const unitLabel = (u: unknown) => (u === 'SP' ? t('Story points') : t('Person days'));
  const basisLabel = (b: unknown) => (b === 'share' ? t('Plannable share only') : t('Whole Forecast PLAN'));
  const trendLabel = (v: unknown) => trends.find(([k]) => k === v)?.[1] ?? String(v);

  const fields: Field<TeamSettings>[] = $derived([
    { label: t('Sprints in the average'), get: (s) => s.forecast.window },
    { label: t('Trend'), get: (s) => s.forecast.trend, show: trendLabel },
    { label: t('Reference capacity (PD)'), get: (s) => s.forecast.referenceCapacity },
    { label: t('Plannable share (%)'), get: (s) => s.forecast.plannableShare },
    { label: t('Rounding (decimals)'), get: (s) => s.forecast.rounding },
    { label: t('Horizon of the forecast (sprints)'), get: (s) => s.forecast.horizon },
    { label: t('Default sprint length (working days)'), get: (s) => s.lengthDays },
    { label: t('Basis of the budget'), get: (s) => s.forecast.basis, show: basisLabel },
    { label: t('Estimation unit'), get: (s) => s.unit, show: unitLabel },
    { label: t('Conversion points to person days'), get: (s) => s.factor, show: (v) => (v === null ? t('From the team rate') : t('Fixed factor {factor}', { factor: String(v) })) },
    { label: t('Unit applies from sprint'), get: (s) => s.unitFrom },
    { label: t('Products'), get: (s) => s.products },
    { label: t('Product owners'), get: (s) => s.po },
    { label: t('Access to production'), get: (s) => s.production },
    { label: t('Cap of the production time (%)'), get: (s) => s.productionCap },
    { label: t('Projects and contingents'), get: (s) => s.projects },
    { label: t('Pro-forma sprints'), get: (s) => s.proForma },
    { label: t('Country'), get: (s) => s.country, show: countryName },
    { label: t('Region'), get: (s) => s.region, show: (v) => String(v) || t('Whole country') },
  ]);

  const rows = $derived(
    applied && draft ? changes(fields, applied, draft, { on: t('on'), off: t('off'), none: '–' }) : [],
  );

  const futureSprints = $derived(app.sprints.filter((s) => s.state === 'future'));
  const unitChanged = $derived(!!applied && !!draft && applied.unit !== draft.unit);
  // With sprints recorded the new unit always applies from a sprint: finished ones keep theirs.
  const needsSprint = $derived(unitChanged && app.sprints.length > 0);

  function setFactor(text: string): void {
    factorText = text;
    if (!draft) return;
    if (text.trim() === '') {
      draft.factor = null;
      return;
    }
    const n = parseNumber(text);
    if (n !== undefined && n > 0) draft.factor = n;
  }

  function addName(): void {
    const name = newName.trim();
    if (!name || !draft) return;
    if (draft.proForma.some((n) => n.toLowerCase() === name.toLowerCase())) {
      toast(t('{name} is listed twice.', { name }), 'bad');
      return;
    }
    draft.proForma.push(name);
    newName = '';
  }

  async function apply(): Promise<void> {
    if (!draft || !app.team) return;
    if (unitChanged && !draft.unitFrom && needsSprint) {
      toast(t('Choose the sprint the new unit applies from.'), 'bad');
      return;
    }
    busy = true;
    try {
      await api.SaveTeamSettings(app.team, draft);
      toast(t('Applied, not saved yet.'), 'ok');
      await load(app.team);
      await loadFeatures();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }

  function reset(): void {
    if (applied) {
      draft = structuredClone(applied);
      factorText = applied.factor === null ? '' : String(applied.factor).replace('.', ',');
    }
  }

  const keywords: Record<string, string> = $derived({
    forecast: t('Forecast velocity range horizon sprint length window trend classic linear reference capacity plannable small items rounding'),
    features: t('Features products product owners production access cap projects contingents'),
    budget: t('Budget basis share'),
    unit: t('Estimation unit conversion story points person days factor'),
    holidays: t('Holidays country region state federal state public holidays calendar'),
    proforma: t('Pro-forma sprints refinement'),
  });
  const q = $derived(query.trim().toLowerCase());
  const shows = (key: string, text: string) => !q || (keywords[key] + ' ' + text).toLowerCase().includes(q);
</script>

<PageHead title={t('Team settings')} lead={t('Forecast, features and budget basis of the team.')} />

{#if !app.team}
  <p class="muted">{t('Choose a team first.')}</p>
{:else if draft}
  <div class="field find">
    <label for="s-q">{t('Find a setting')}</label>
    <input id="s-q" class="input" type="search" bind:value={query} placeholder={t('e.g. production, range')} />
  </div>

  <div class="grid cols-2">
    {#if shows('forecast', t('Forecast'))}
      <div class="card wide">
        <h2>{t('Forecast')}</h2>
        <div class="fields">
          <div class="field">
            <label for="t-window">{t('Sprints in the average')}</label>
            <select id="t-window" class="input" bind:value={draft.forecast.window}>
              {#each [3, 4, 5, 6, 8] as n (n)}<option value={n}>{n === 5 ? t('{n} (default)', { n }) : n}</option>{/each}
              {#if ![3, 4, 5, 6, 8].includes(draft.forecast.window)}<option value={draft.forecast.window}>{draft.forecast.window}</option>{/if}
            </select>
          </div>
          <div class="field">
            <label for="t-trend">{t('Trend')}</label>
            <select id="t-trend" class="input" bind:value={draft.forecast.trend}>
              {#each trends as [value, label] (value)}<option {value}>{label}</option>{/each}
            </select>
          </div>
          <NumInput id="t-refcap" label={t('Reference capacity (PD)')} bind:value={draft.forecast.referenceCapacity} min={0.1} max={10000} />
          <NumInput id="t-share" label={t('Plannable share (%)')} bind:value={draft.forecast.plannableShare} min={0} max={100} />
          <div class="field">
            <label for="t-rounding">{t('Rounding')}</label>
            <select id="t-rounding" class="input" bind:value={draft.forecast.rounding}>
              <option value={0}>{t('whole points')}</option>
              <option value={1}>{t('one decimal')}</option>
              <option value={2}>{t('two decimals')}</option>
            </select>
          </div>
          <div class="field">
            <label for="t-horizon">{t('Horizon')}</label>
            <select id="t-horizon" class="input" bind:value={draft.forecast.horizon}>
              {#each [2, 3, 4, 6, 8, 12] as n (n)}<option value={n}>{t('{n} sprints', { n })}</option>{/each}
              {#if ![2, 3, 4, 6, 8, 12].includes(draft.forecast.horizon)}<option value={draft.forecast.horizon}>{t('{n} sprints', { n: draft.forecast.horizon })}</option>{/if}
            </select>
          </div>
          <NumInput id="t-len" label={t('Default sprint length')} unit={t('working days')} bind:value={draft.lengthDays} min={1} max={60} integer />
        </div>
        <details>
          <summary>{t('What the settings do')}</summary>
          <ul class="small">
            <li><strong>{t('Window')}:</strong> {t('over how many sprints with a value the normalized velocity is averaged (rolling mean). A new team gets a first forecast from 3 sprints.')}</li>
            <li><strong>{t('Trend')}:</strong> {t('how the average is carried into the future. Flat keeps the last average (robust). Linear continues the slope of the last two averages. Classic works like the Excel template: first sprint linear, second multiplicative, then linear; it carries outliers on.')}</li>
            <li><strong>{t('Forecast PLAN')}</strong> = {t('trend of the normalized velocity ÷ reference capacity × capacity of the sprint, rounded down. With a flat trend this equals capacity × rate.')}</li>
            <li><strong>{t('Range')}:</strong> {t('lowest to highest normalized velocity in the window, converted to the capacity. No setting.')}</li>
            <li><strong>{t('Plannable share')}:</strong> {t('the part of the Forecast PLAN that is distributed to products and projects; the rest is small items.')}</li>
          </ul>
        </details>
      </div>
    {/if}

    {#if shows('features', t('Features'))}
      <div class="card">
        <h2>{t('Features')}</h2>
        <div class="stack gap">
          <Switch bind:checked={draft.products} title={t('Products')}>
            {t('The sprint is distributed to several products. Without it the pages show no product columns.')}
          </Switch>
          <Switch bind:checked={draft.po} title={t('Product owners')}>
            {t('Each product has a responsible product owner; sums are shown per owner.')}
          </Switch>
          <Switch bind:checked={draft.production} title={t('Access to production')}>
            {t('Each person can have production access, each ticket a production share (without tickets one PD value per sprint). Pre-planning and planning compare that with the time of the people with access. It warns and never blocks.')}
          </Switch>
          {#if draft.production}
            <div class="sub">
              <NumInput id="t-prodmax" label={t('Cap of the production time (%)')} bind:value={draft.productionCap} min={0} max={100} width="170px" />
              <span class="small muted">
                {t('At most this part of the time of the people with production access counts for production work. 100 = no cap; 60 means at most 60 percent.')}
              </span>
            </div>
          {/if}
          <Switch bind:checked={draft.projects} title={t('Projects and contingents')}>
            {t('Projects with milestones and a contingent in person days. They also work without a tracker.')}
          </Switch>
        </div>
      </div>
    {/if}

    {#if shows('holidays', t('Holidays'))}
      <div class="card">
        <h2>{t('Holidays')}</h2>
        <div class="fields">
          <div class="field">
            <label for="t-country">{t('Country')}</label>
            <select id="t-country" class="input" bind:value={draft.country} onchange={() => (draft!.region = '')}>
              {#each regions as r (r.country)}<option value={r.country}>{r.name}</option>{/each}
            </select>
          </div>
          <div class="field">
            <label for="t-region">{t('Region')}</label>
            <select id="t-region" class="input" bind:value={draft.region}>
              <option value="">{t('Whole country')}</option>
              {#each country?.regions ?? [] as r (r)}<option value={r}>{r}</option>{/each}
            </select>
          </div>
        </div>
        <p class="small muted">{t('The public holidays of this country and region reduce the working days of every sprint.')}</p>
      </div>
    {/if}

    {#if shows('budget', t('Basis of the budget'))}
      <div class="card">
        <h2>{t('Basis of the budget')}</h2>
        <div class="stack" role="radiogroup" aria-label={t('Basis of the budget')}>
          <label class="opt">
            <input type="radio" name="basis" value="plan" bind:group={draft.forecast.basis} />
            <span><strong>{t('Whole Forecast PLAN')}</strong> <span class="small muted">({t('default')})</span></span>
          </label>
          <label class="opt">
            <input type="radio" name="basis" value="share" bind:group={draft.forecast.basis} />
            <span><strong>{t('Plannable share only')}</strong> <span class="small muted">({t('small items are not distributed to products')})</span></span>
          </label>
          <p class="small muted">
            {t('Example: a product with 35 percent gets {whole} points of the whole Forecast PLAN of 60, or {share} of its plannable share of {percent} percent.', {
              whole: 21,
              share: Math.floor((60 * draft.forecast.plannableShare) / 100 * 0.35),
              percent: draft.forecast.plannableShare,
            })}
          </p>
        </div>
      </div>
    {/if}

    {#if shows('unit', t('Estimation unit and conversion'))}
      <div class="card">
        <h2>{t('Estimation unit and conversion')}</h2>
        <div class="stack gap">
          <div class="stack" role="radiogroup" aria-label={t('Estimation unit')}>
            <div class="small muted">{t('What does the team estimate in?')}</div>
            <label class="opt">
              <input type="radio" name="unit" value="SP" bind:group={draft.unit} />
              <span><strong>{t('Story points')}</strong></span>
            </label>
            <label class="opt">
              <input type="radio" name="unit" value="PT" bind:group={draft.unit} />
              <span><strong>{t('Person days')}</strong> <span class="small muted">{t('estimate, velocity and forecast in PD')}</span></span>
            </label>
          </div>
          {#if draft.unit === 'SP'}
            <div class="stack" role="radiogroup" aria-label={t('Conversion')}>
              <div class="small muted">{t('How are points converted to person days? Needed for the contingents of projects, which always run in PD.')}</div>
              <label class="opt">
                <input type="radio" name="conv" checked={draft.factor === null} onchange={() => setFactor('')} />
                <span><strong>{t('From the team rate')}</strong> <span class="small muted">({t('default')})</span><br /><span class="small muted">{t('Follows the measured rate and changes with every review. Help > Calculations explains how it is measured.')}</span></span>
              </label>
              <label class="opt">
                <input type="radio" name="conv" checked={draft.factor !== null} onchange={() => setFactor(factorText || '1')} />
                <span><strong>{t('Fixed factor')}</strong><br /><span class="small muted">{t('For example from an agreement with the project lead.')}</span></span>
              </label>
              {#if draft.factor !== null}
                <div class="row indent">
                  <input class="input data num" style="width:72px" aria-label={t('Points per person day')} inputmode="decimal" value={factorText} oninput={(e) => setFactor(e.currentTarget.value)} />
                  <span class="small">{t('points per PD')}</span>
                </div>
                <div class="small muted indent">
                  {t('Example: 21 points are about {pd} PD.', { pd: (21 / draft.factor).toFixed(1).replace('.', ',') })}
                  <Calc label={t('Points in person days')} topic="units">{t('21 points ÷ {factor} points per PD = {pd} PD', { factor: String(draft.factor).replace('.', ','), pd: (21 / draft.factor).toFixed(1).replace('.', ',') })}</Calc>
                </div>
              {/if}
            </div>
          {:else}
            <p class="small muted">{t('Estimating in PD needs no conversion: contingents, planning and forecast count in person days directly.')}</p>
          {/if}
          {#if unitChanged}
            <div class="field" style="max-width:280px">
              <label for="t-unitfrom">{t('Applies from sprint')}</label>
              <select id="t-unitfrom" class="input" bind:value={draft.unitFrom}>
                {#if !needsSprint}<option value="">{t('From the first sprint')}</option>{:else if !draft.unitFrom}<option value="" disabled>{t('Choose a sprint')}</option>{/if}
                {#each futureSprints as s (s.id)}<option value={s.id}>{s.id}</option>{/each}
              </select>
            </div>
          {/if}
          {#if applied && applied.unitChanges.length}
            <p class="small muted">{t('Earlier switches')}: {applied.unitChanges.map((c) => `${c.from}: ${unitLabel(c.unit)}`).join(', ')}</p>
          {/if}
          <p class="small muted">
            {t('Finished sprints keep their unit. When the unit changes, the forecast converts their velocity with the factor and says so in the calculation. Open estimates stay and are marked as “old unit” in the backlog until someone estimates them again.')}
          </p>
        </div>
      </div>
    {/if}

    {#if shows('proforma', t('Pro-forma sprints'))}
      <div class="card">
        <h2>{t('Pro-forma sprints')}</h2>
        <p class="small muted lead">
          {t('Pro-forma sprints are only places to park tickets, for example “Refinement”. They sit under the backlog and never count for capacity or forecast. None, one or several are possible; names are matched to the sprints of the tracker.')}
        </p>
        <ul class="names">
          {#each draft.proForma as name, i (name)}
            <li class="chip">
              {name}
              <button class="btn icon ghost mini" type="button" aria-label={t('Remove {name}', { name })} onclick={() => draft?.proForma.splice(i, 1)}>
                <Icon name="close" size={14} />
              </button>
            </li>
          {:else}
            <li class="small muted">{t('None.')}</li>
          {/each}
        </ul>
        <form class="row" onsubmit={(e) => { e.preventDefault(); addName(); }}>
          <input class="input" aria-label={t('Name of the pro-forma sprint')} placeholder={t('Name, e.g. Refinement')} bind:value={newName} />
          <button class="btn" type="submit"><Icon name="add" />{t('Add')}</button>
        </form>
      </div>
    {/if}

    {#if !q}<ArchiveCard />{/if}

    <div class="full">
      <ChangesCard {rows} {busy} onapply={apply} onreset={reset} />
    </div>
  </div>
  {#if q && !['forecast', 'features', 'budget', 'unit', 'proforma'].some((k) => shows(k, ''))}
    <p class="muted">{t('No setting found.')}</p>
  {/if}
{:else}
  <p class="muted">{t('Loading …')}</p>
{/if}

<style>
  .find {
    max-width: 360px;
    margin-bottom: 12px;
  }
  .wide,
  .full {
    grid-column: 1 / -1;
  }
  .fields {
    display: grid;
    gap: 8px 12px;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  }
  .gap {
    gap: 12px;
  }
  .opt {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .opt input {
    margin-top: 3px;
  }
  .sub {
    margin-left: 24px;
    display: flex;
    gap: 12px;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .sub .small {
    flex: 1;
    min-width: 200px;
  }
  .indent {
    margin-left: 24px;
  }
  details {
    margin-top: 12px;
  }
  summary {
    cursor: pointer;
  }
  ul.small {
    margin: 6px 0 0;
    padding-left: 18px;
  }
  .names {
    list-style: none;
    padding: 0;
    margin: 0 0 8px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .mini {
    width: 20px;
    height: 20px;
    margin-right: -4px;
  }
  .lead {
    margin: 0 0 8px;
  }
  p {
    margin: 0;
  }
</style>
