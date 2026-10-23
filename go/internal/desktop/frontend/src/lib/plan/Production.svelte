<script lang="ts">
  // The production card of Pre-plan and Plan: the time of the people with production access
  // against the production part of the planned work. It warns, it never blocks. With tickets
  // each one has a share of 0 to 100 percent (set in Foresprint, by label or by rule); without
  // tickets one value per sprint is entered.
  import { api } from '../api';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import type { PlanSprint } from '../types.plan';
  import Calc from '../calc/Calc.svelte';
  import { fmt, itemWord, parseAmount, type PlanModel } from './model.svelte';

  interface Props {
    d: PlanSprint;
    model: PlanModel;
    readonly?: boolean;
  }
  let { d, model, readonly = false }: Props = $props();
  const prod = $derived(d.prod);
  const withProd = $derived(d.tickets.filter((x) => x.prodPct > 0));
  const without = $derived(d.tickets.filter((x) => x.prodPct === 0));
  const source = (s: string) =>
    ({ manual: t('by hand'), label: t('label'), rule: t('rule'), none: '–' })[s] ?? s;

  async function setPct(key: string, text: string): Promise<void> {
    const v = parseAmount(text);
    if (v === undefined) return void model.reload();
    await model.change(() => api.SetProductionPercent(app.team, key, v == null ? null : Math.min(v, 100)));
  }
  async function setPT(text: string): Promise<void> {
    const v = parseAmount(text);
    if (v === undefined) return void model.reload();
    await model.change(() => api.SetProductionPT(app.team, d.sprint, v));
  }
  async function add(key: string): Promise<void> {
    if (key) await model.change(() => api.SetProductionPercent(app.team, key, 100));
  }
</script>

{#if prod}
  <div class="card prod" id="prod-card">
    <div class="row head">
      <h2>{t('Production')}</h2>
      {#if prod.demandSet}
        <span class="chip {prod.status === 'over' ? 'bad' : prod.status === 'tight' ? 'warn' : 'ok'}">
          {prod.status === 'over'
            ? t('{n} PD more than available', { n: fmt(prod.demand - prod.available, 1) })
            : prod.status === 'tight'
              ? t('tight')
              : t('fits')}
        </span>
      {/if}
      <Calc label={t('Production')} topic="units">
        {#each prod.people as p (p.name)}
          <div>{p.name}: <span class="data">{fmt(p.capacity, 1)} {t('PD')}</span></div>
        {/each}
        <div class="data">{fmt(prod.time, 1)} {t('PD')} × {fmt(prod.capPercent)} % = {fmt(prod.available, 1)} {t('PD')}</div>
      </Calc>
    </div>
    <p class="small muted lead">
      {t('Available: {n} PD', { n: fmt(prod.available, 1) })}{prod.capPercent < 100
        ? `, ${t('that is {pct} % (cap) of {time} PD', { pct: fmt(prod.capPercent), time: fmt(prod.time, 1) })}`
        : ''}
      {t('with {count} people with production access ({names}), after absences.', {
        count: prod.people.length,
        names: prod.people.map((p) => p.name.split(' ')[0]).join(', '),
      })}
    </p>

    {#if d.source === 'none'}
      <div class="row">
        <div class="field">
          <label for="prod-pt">{t('Production work in {sprint} (PD)', { sprint: d.sprint })}</label>
          <input
            id="prod-pt"
            class="input data num"
            inputmode="decimal"
            value={prod.manual ?? ''}
            placeholder="–"
            disabled={readonly}
            onchange={(e) => setPT(e.currentTarget.value)}
          />
        </div>
        <p class="small muted note">{t('Without tickets one value is enough: how many person days need access to production?')}</p>
      </div>
    {:else}
      {#if withProd.length}
        <div class="tw">
          <table class="t">
            <thead>
              <tr>
                <th>{itemWord(d, false)}</th>
                <th class="num">{t('Size')}</th>
                <th class="num">{t('Prod %')}</th>
                {#if d.source === 'tracker'}<th>{t('Source')}</th>{/if}
                <th class="num">{t('Prod part')}</th>
              </tr>
            </thead>
            <tbody>
              {#each withProd as x (x.key)}
                <tr>
                  <td><span class="data">{x.key}</span> {x.title}</td>
                  <td class="num">{fmt(x.size, 1)}</td>
                  <td class="num edit">
                    <input
                      inputmode="numeric"
                      value={x.prodPct}
                      aria-label={t('Production share of {key} in percent', { key: x.key })}
                      disabled={readonly}
                      onchange={(e) => setPct(x.key, e.currentTarget.value)}
                    />
                  </td>
                  {#if d.source === 'tracker'}<td class="small">{source(x.prodSource)}</td>{/if}
                  <td class="num">{fmt(((x.size ?? 0) * x.prodPct) / 100, 1)}</td>
                </tr>
              {/each}
              <tr class="sum">
                <td>{t('Sum')}</td><td></td><td></td>{#if d.source === 'tracker'}<td></td>{/if}
                <td class="num">{fmt(prod.demandAmount, 1)}</td>
              </tr>
              <tr class="sum">
                <td>{t('in person days')}</td><td></td><td></td>{#if d.source === 'tracker'}<td></td>{/if}
                <td class="num">{fmt(prod.demand, 1)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      {:else}
        <p class="muted small">{t('No {items} in {sprint} needs production access.', { items: itemWord(d, false), sprint: d.sprint })}</p>
      {/if}
      {#if !readonly && without.length}
        <div class="row add">
          <select class="input" aria-label={t('Another item needs production access')} onchange={(e) => { add(e.currentTarget.value); e.currentTarget.value = ''; }}>
            <option value="">{t('Another {item} needs production …', { item: itemWord(d, false) })}</option>
            {#each without as x (x.key)}<option value={x.key}>{x.key} {x.title}</option>{/each}
          </select>
          <span class="small muted">{t('starts at 100 %, then adjust')}</span>
        </div>
      {/if}
      <p class="small muted note">
        {t('Each item has a share from 0 to 100 %: 100 % means only people with access can do it.')}
        {#if d.source === 'tracker'}{t('Taken from a label or a rule where you set one; a value set here always wins.')}{/if}
      </p>
    {/if}
  </div>
{/if}

<style>
  .prod {
    margin-bottom: 16px;
  }
  .head {
    margin-bottom: 4px;
  }
  .head h2 {
    margin: 0;
    flex: 1;
  }
  .lead {
    margin: 0 0 8px;
  }
  .note {
    flex: 1;
    min-width: 220px;
    margin: 8px 0 0;
  }
  .add {
    margin-top: 8px;
  }
  .add select {
    max-width: 420px;
  }
  #prod-pt {
    width: 120px;
    text-align: right;
  }
</style>
