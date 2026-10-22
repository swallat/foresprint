<script lang="ts">
  // Ending a product (flows.md decision 22). A product with history is not deleted: it gets a
  // last sprint, its share goes to the remaining products (proposal in proportion, editable,
  // must reach 100 %), its open tickets or work packages go to another product, its rule is
  // dropped. Past sprints, minutes and the forecast history keep it.
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import SidePanel from '../../lib/ui/SidePanel.svelte';
  import { fmtDay, parseNum } from '../../lib/team/format';
  import { percent, proposeShares } from '../../lib/team/products';
  import type { EndResult, Product, TicketSource } from '../../lib/types.team';

  interface Props {
    product: Product;
    remaining: Product[];
    source: TicketSource;
    /** "tickets" or "work packages", in the language of the window. */
    unit: string;
    onclose: () => void;
    ondone: (result: EndResult) => void | Promise<void>;
  }
  let { product, remaining, source, unit, onclose, ondone }: Props = $props();

  // The last sprint: the running one and later ones; the day it ends is the last day of the product.
  const choices = $derived(app.sprints.filter((s) => s.state !== 'past'));
  // svelte-ignore state_referenced_locally
  let lastDay = $state(app.sprints.find((s) => s.state === 'current')?.end ?? app.sprints.find((s) => s.state === 'future')?.end ?? '');
  // svelte-ignore state_referenced_locally
  let percents = $state<Record<string, string>>(
    Object.fromEntries(Object.entries(proposeShares(remaining)).map(([id, v]) => [id, String(Math.round(v * 100))])),
  );
  // svelte-ignore state_referenced_locally
  let target = $state(remaining[0]?.id ?? '');
  let busy = $state(false);

  const total = $derived(remaining.reduce((n, p) => n + (Number.isFinite(parseNum(percents[p.id] ?? '')) ? parseNum(percents[p.id] ?? '') : 0), 0));
  const reaches = $derived(Math.abs(total - 100) < 0.5);

  async function confirm() {
    busy = true;
    try {
      const shares = Object.fromEntries(remaining.map((p) => [p.id, (parseNum(percents[p.id] ?? '') || 0) / 100]));
      const result = await api.EndProduct(app.team, product.id, lastDay, shares, target);
      await ondone(result);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
    } finally {
      busy = false;
    }
  }
</script>

<SidePanel title={t('End {name}', { name: product.name })} {onclose}>
  <p class="small muted">
    {t('{name} has history, so it is ended and not deleted. Past sprints, minutes and the forecast history keep it.', { name: product.name })}
  </p>

  <div class="field">
    <label for="end-day">{t('Last sprint of the product')}</label>
    {#if choices.length}
      <select id="end-day" class="input" bind:value={lastDay}>
        {#each choices as s (s.id)}<option value={s.end}>{s.id} ({t('ends {date}', { date: fmtDay(s.end) })})</option>{/each}
      </select>
    {:else}
      <input id="end-day" class="input data" type="date" bind:value={lastDay} />
    {/if}
  </div>

  <h3>{t('Shares of the remaining products')}</h3>
  <p class="small muted">{t('The share of {name} ({share} %) goes to the others in proportion. You can change it; it has to add up to 100 %.', { name: product.name, share: percent(product.share) ?? 0 })}</p>
  <div class="tw">
    <table class="t">
      <thead><tr><th>{t('Product')}</th><th class="num">{t('Now')}</th><th class="num">{t('New share %')}</th></tr></thead>
      <tbody>
        {#each remaining as p (p.id)}
          <tr>
            <td>{p.name}</td>
            <td class="num data">{percent(p.share) ?? '–'}</td>
            <td class="num">
              <input class="input data share" inputmode="numeric" bind:value={percents[p.id]} aria-label={t('New share of {name} in percent', { name: p.name })} />
            </td>
          </tr>
        {/each}
        <tr class="sum"><td>{t('Total')}</td><td></td><td class="num" class:bad={!reaches}>{Math.round(total)}</td></tr>
      </tbody>
    </table>
  </div>
  {#if !reaches}<p class="small bad" role="alert">{t('The shares add up to {sum} %, not 100 %.', { sum: Math.round(total) })}</p>{/if}

  {#if source !== 'none'}
    <div class="field">
      <label for="end-target">{t('Open {unit} go to', { unit })}</label>
      <select id="end-target" class="input" bind:value={target}>
        {#each remaining as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
        <option value="">{t('not assigned')}</option>
      </select>
    </div>
    {#if source === 'tracker'}
      <p class="small muted">{t('With a tracker the rule of {name} is added to the rule of the chosen product, so its tickets keep their place. The rule of {name} itself is dropped.', { name: product.name })}</p>
    {/if}
  {/if}
  <p class="small muted">{t('Projects continue without this product.')}</p>

  <div class="row">
    <button class="btn danger" type="button" disabled={!reaches || busy || !lastDay} onclick={confirm}><Icon name="archive" />{t('End product')}</button>
    <button class="btn ghost" type="button" onclick={onclose}>{t('Cancel')}</button>
  </div>
</SidePanel>

<style>
  h3 {
    margin: 12px 0 0;
    font: 600 14px/20px var(--font-ui);
  }
  .share {
    width: 64px;
    text-align: right;
  }
  .bad {
    color: var(--bad);
    margin: 0;
  }
</style>
