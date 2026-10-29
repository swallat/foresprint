<script lang="ts">
  import type { PageProps } from '../../lib/routes';
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { takeNew } from '../../lib/router.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import RuleEditor from '../../lib/rules/RuleEditor.svelte';
  import { fmtDay, fmtNum, parseNum } from '../../lib/team/format';
  import { percent, shareSum } from '../../lib/team/products';
  import { inverse } from '../../lib/team/undo';
  import type { Product, ProductsDefault, ProductsView } from '../../lib/types.team';
  import Calc from '../../lib/calc/Calc.svelte';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import EndProductPanel from './EndProductPanel.svelte';

  let { params }: PageProps = $props();
  void params;

  let view = $state<ProductsView>();
  let failed = $state('');
  let ending = $state('');
  let ruleFor = $state('');
  let ruleText = $state('');
  let ruleValid = $state(true);
  let focusId = $state('');

  const active = $derived((view?.products ?? []).filter((p) => !p.ended));
  const ended = $derived((view?.products ?? []).filter((p) => p.ended));
  const sum = $derived(shareSum(active));
  const rules = $derived(view?.source === 'tracker');
  const counts = $derived(view?.source !== 'none');
  const ticketsLabel = $derived(view?.source === 'packages' ? t('Work packages') : t('Tickets'));
  const unit = $derived(view?.source === 'packages' ? t('work packages') : t('tickets'));

  // The default share is shown for the sprint to plan next: the first one that is not running.
  const defaults = $derived(view?.defaults ?? []);
  const focus = $derived(defaults.find((d) => !d.running) ?? defaults[0]);
  const focusSum = $derived(active.reduce((n, p) => n + (focus?.values[p.id] ?? 0), 0));

  let loadedTeam = '';
  async function load() {
    const team = app.team;
    try {
      view = await api.Products(team);
      loadedTeam = team;
      failed = '';
      if (!active.some((p) => p.id === ruleFor)) selectRule(active[0]?.id ?? '');
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

  function selectRule(id: string) {
    ruleFor = id;
    ruleText = (view?.products ?? []).find((p) => p.id === id)?.rule ?? '';
  }

  async function save(next: Product[], message = ''): Promise<boolean> {
    try {
      view = await api.SaveProducts(app.team, next);
      if (message) toast(message, 'ok');
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
      return false;
    }
  }

  const replace = (p: Product) => (view?.products ?? []).map((x) => (x.id === p.id ? p : x));

  function rename(p: Product, name: string) {
    if (!name.trim() || name === p.name) return load();
    return save(replace({ ...p, name: name.trim() }));
  }

  function setShare(p: Product, text: string) {
    if (text.trim() === '') return save(replace({ ...p, share: null }));
    const value = parseNum(text);
    if (!(value >= 0 && value <= 100)) {
      toast(t('Enter a share between 0 and 100 percent.'), 'bad');
      return load();
    }
    return save(replace({ ...p, share: value / 100 }));
  }

  // "+" menu in the top bar: open with a new row
  $effect(() => {
    if (view && loadedTeam === app.team && takeNew()) add();
  });

  function add() {
    const product: Product = {
      id: '',
      name: t('New product'),
      po: view?.owners[0]?.id ?? '',
      share: null,
      rule: '',
      from: '',
      to: '',
      tickets: 0,
      points: 0,
      ended: false,
      used: false,
    };
    void save([...(view?.products ?? []), product], t('Product added.')).then(() => {
      const added = view?.products.find((p) => p.name === product.name && !p.used);
      if (added) focusId = added.id;
    });
  }

  async function applyRule() {
    const product = active.find((p) => p.id === ruleFor);
    if (!product) return;
    await save(replace({ ...product, rule: ruleText.trim() }), t('Rule of {name} saved. It applies from the next fetch.', { name: product.name }));
    selectRule(ruleFor);
  }

  const productFields: (keyof Product)[] = ['name', 'po', 'share', 'rule', 'from', 'to'];

  async function remove(p: Product) {
    const rest = (view?.products ?? []).filter((x) => x.id !== p.id);
    const before = view?.products ?? [];
    if (!(await save(rest))) return;
    const undo = inverse(before, view?.products ?? [], productFields);
    toast(t('{name} deleted.', { name: p.name }), 'ok', {
      label: t('Undo'),
      run: () => {
        const { list, ok } = undo(view?.products ?? []);
        if (!ok) toast(t('This change can no longer be undone.'), 'bad');
        else void save(list, t('Change undone.'));
      },
    });
  }

  async function resume(p: Product) {
    try {
      const step = await api.ResumeProduct(app.team, p.id);
      view = step.view;
      toast(t('{name} is active again with a share of 0 %. Adjust the shares above.', { name: p.name }), 'ok', {
        label: t('Undo'),
        run: () => void undo(step.undo),
      });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
    }
  }

  async function undo(token: number) {
    try {
      await api.Undo(app.team, token);
      toast(t('Change undone.'), 'ok');
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
    }
    await load();
  }

  const ownerName = (ref: string) => view?.owners.find((o) => o.id === ref)?.name ?? ref;
  const endingProduct = $derived(active.find((p) => p.id === ending));
  const lead = $derived(
    view?.source === 'tracker'
      ? t('Products with product owner, share of the sprint and a rule that assigns tickets.')
      : view?.source === 'packages'
        ? t('Products with product owner and share of the sprint. You choose the product on the work package itself.')
        : t('Products with product owner and share of the sprint. Planning uses an amount per product, without tickets.'),
  );
</script>

{#snippet calc(d: ProductsDefault, p: Product)}
  {#if d.roadmap}{t('Forecast PLAN')} {fmtNum(d.plan ?? 0)} × {percent(d.roadmapShare)} % = {fmtNum(d.available ?? 0)};
  {/if}{#if p.share === null}({fmtNum(d.available ?? 0)} − {fmtNum(d.fixed)}) ÷ {d.rest} = {fmtNum(d.values[p.id] ?? 0, 0)}{:else}{fmtNum(d.available ?? 0)} × {percent(p.share)} % = {fmtNum(d.values[p.id] ?? 0, 0)}{/if}
{/snippet}

<PageHead title={t('Products')} {lead}>
  {#snippet actions()}
    <button class="btn" type="button" onclick={add}><Icon name="add" />{t('Add product')}</button>
  {/snippet}
</PageHead>

{#if failed}
  <Banner tone="bad">{failed}</Banner>
{:else if !view}
  <p class="muted">{t('Loading…')}</p>
{:else}
  {#if active.length < 2}
    <Banner>
      <strong>{t('One product')}:</strong>
      {t('All tickets belong to the team; assignment rules, budgets and balance per product are hidden. With a second product they appear everywhere by themselves.')}
    </Banner>
  {/if}
  {#if sum !== 100 && active.length > 1}
    <Banner tone="warn">{t('The shares add up to {sum} %, not 100 %. The rest is not distributed in the default share.', { sum })}</Banner>
  {/if}

  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th>{t('Product')}</th>
          <th class="only-multipo">{t('Product owner')}</th>
          <th class="num">{t('Share %')}</th>
          {#if focus}<th class="num" title={t('Forecast PLAN of the sprint times the share')}>{t('Default {sprint}', { sprint: focus.sprint })}</th>{/if}
          {#if rules}<th>{t('Assignment rule')}</th>{/if}
          {#if counts}<th class="num">{ticketsLabel}</th>{/if}
          <th><span class="sr-only">{t('Actions')}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each active as p (p.id)}
          <tr>
            <td><input class="input name" data-name={p.id} value={p.name} aria-label={t('Name')} onchange={(e) => rename(p, e.currentTarget.value)} /></td>
            <td class="only-multipo">
              <select class="input" aria-label={t('Product owner of {name}', { name: p.name })} value={p.po} onchange={(e) => save(replace({ ...p, po: e.currentTarget.value }))}>
                {#if !view.owners.some((o) => o.id === p.po)}<option value={p.po}>{p.po || '–'}</option>{/if}
                {#each view.owners as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
              </select>
            </td>
            <td class="num">
              <input
                class="input data share"
                inputmode="numeric"
                value={percent(p.share) ?? ''}
                placeholder={t('auto')}
                aria-label={t('Share of {name} in percent', { name: p.name })}
                onchange={(e) => setShare(p, e.currentTarget.value)}
              />
            </td>
            {#if focus}
              <td class="num data">
                {#if focus.values[p.id] !== undefined}
                  <span class="row nowrap end">
                    {fmtNum(focus.values[p.id]!, 0)}
                    <Calc label={t('Default {sprint}', { sprint: focus.sprint })} topic="plannable">
                      {@render calc(focus, p)}
                    </Calc>
                  </span>
                {:else}
                  <span class="muted">–</span>
                {/if}
              </td>
            {/if}
            {#if rules}
              <td>
                <span class="row nowrap">
                  <span class="data small rule-txt">{p.rule || t('no rule')}</span>
                  <button
                    class="btn ghost icon"
                    type="button"
                    aria-label={t('Edit rule of {name}', { name: p.name })}
                    title={t('Edit rule')}
                    onclick={() => {
                      selectRule(p.id);
                      document.getElementById('rule-card')?.scrollIntoView({ block: 'nearest' });
                    }}
                  >
                    <Icon name="edit" />
                  </button>
                </span>
              </td>
            {/if}
            {#if counts}<td class="num data">{p.tickets}</td>{/if}
            <td class="actions">
              {#if p.used}
                <button
                  class="btn icon ghost"
                  type="button"
                  disabled={active.length < 2}
                  aria-label={t('End {name}', { name: p.name })}
                  title={active.length < 2 ? t('The only product cannot be ended') : t('End (the history stays)')}
                  onclick={() => (ending = p.id)}
                >
                  <Icon name="archive" />
                </button>
              {:else}
                <button class="btn icon ghost" type="button" disabled={active.length < 2} aria-label={t('Delete {name}', { name: p.name })} title={t('Delete')} onclick={() => remove(p)}>
                  <Icon name="delete" />
                </button>
              {/if}
            </td>
          </tr>
        {/each}
        <tr class="sum">
          <td>{t('Total')}</td>
          <td></td>
          <td class="num">{sum}</td>
          {#if focus}<td class="num data">{focus.plan === null ? '–' : fmtNum(focusSum, 0)}</td>{/if}
          {#if rules}<td></td>{/if}
          {#if counts}<td class="num">{active.reduce((n, p) => n + p.tickets, 0)}</td>{/if}
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>
  <p class="small muted note">
    {#if app.features?.po !== false}{#each view.owners as o, i (o.id)}{i ? ', ' : ''}{o.name} <span class="data">{shareSum(active.filter((p) => p.po === o.id))} %</span>{/each}.{/if}
    {t('The share is the target; what is really planned and done is in the sprint table. Create and rename POs under People and absences. To remove a product use the symbol at the end of the row; a product with history is ended, not deleted.')}
  </p>

  {#if defaults.length}
    <div class="card below" id="defaults-card">
      <h2>{t('Default share per sprint')}</h2>
      <p class="small muted">{t('Forecast PLAN times the share of each product, rounded to whole points. This is what Plan proposes for the product.')}</p>
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th>{t('Product')}</th>
              {#each defaults as d (d.sprint)}<th class="num">{d.sprint}</th>{/each}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{t('Forecast PLAN')}</td>
              {#each defaults as d (d.sprint)}
                <td class="num data">
                  {#if d.plan === null}
                    <span class="muted">–</span>
                  {:else}
                    <span class="row nowrap end">
                      {fmtNum(d.plan)}
                      <Calc label={t('Forecast PLAN {sprint}', { sprint: d.sprint })} topic="forecast">
                        {t('Forecast PLAN of {sprint}', { sprint: d.sprint })}: {fmtNum(d.plan)}{d.roadmap
                          ? ` × ${percent(d.roadmapShare)} % = ${fmtNum(d.available ?? 0)}`
                          : ''}
                      </Calc>
                    </span>
                  {/if}
                </td>
              {/each}
            </tr>
            {#each active as p (p.id)}
              <tr>
                <td>{p.name}</td>
                {#each defaults as d (d.sprint)}
                  <td class="num data">{d.values[p.id] === undefined ? '–' : fmtNum(d.values[p.id]!, 0)}</td>
                {/each}
              </tr>
            {/each}
            <tr class="sum">
              <td>{t('Total')}</td>
              {#each defaults as d (d.sprint)}
                <td class="num data">{d.plan === null ? '–' : fmtNum(active.reduce((n, p) => n + (d.values[p.id] ?? 0), 0), 0)}</td>
              {/each}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  {#if ended.length}
    <details class="card ended">
      <summary><strong>{t('Ended products')}</strong> <span class="muted small">{ended.length}</span></summary>
      <div class="tw">
        <table class="t">
          <thead><tr><th>{t('Product')}</th><th class="only-multipo">{t('Product owner')}</th><th>{t('Last day')}</th><th></th></tr></thead>
          <tbody>
            {#each ended as p (p.id)}
              <tr>
                <td>{p.name}</td>
                <td class="only-multipo">{ownerName(p.po)}</td>
                <td class="data">{fmtDay(p.to)}</td>
                <td><button class="btn" type="button" onclick={() => resume(p)}><Icon name="unarchive" />{t('Take up again')}</button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="small muted">{t('Past sprints, minutes and the forecast history keep ended products. A product taken up again starts with a share of 0 %.')}</p>
    </details>
  {/if}

  <div class="grid cols-2 below">
    {#if rules && active.length}
      <div class="card" id="rule-card">
        <h2>{t('Edit assignment rule')}</h2>
        <div class="field pick">
          <label for="rule-product">{t('Product')}</label>
          <select id="rule-product" class="input" value={ruleFor} onchange={(e) => selectRule(e.currentTarget.value)}>
            {#each active as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </div>
        {#key ruleFor}
          <RuleEditor team={app.team} owner={{ kind: 'product', id: ruleFor }} name={active.find((p) => p.id === ruleFor)?.name ?? ""} bind:value={ruleText} bind:valid={ruleValid} allowEmpty />
        {/key}
        <p class="small muted">
          {t('The same rule language as for projects. Example')}: <span class="data rule-txt">component = "Portal" OR (epic ~ "Customer" AND label != "internal")</span>
        </p>
        <div class="row">
          <button class="btn primary" type="button" disabled={!ruleValid} onclick={applyRule}>{t('Apply rule')}</button>
          <span class="small muted">{t('A product set by hand on a ticket wins over the rule.')}</span>
        </div>
      </div>
    {:else if !rules}
      <div class="card">
        <h2>{view.source === 'none' ? t('No assignment rules') : t('Product on the work package')}</h2>
        <p class="small muted">
          {view.source === 'none'
            ? t('Without tickets there is nothing to assign. The share is the target for the amount per product in Pre-plan and Plan.')
            : t('Without a tracker there are no fields such as component or label. You choose the product when you create a work package and change it in the backlog.')}
        </p>
      </div>
    {/if}
  </div>
{/if}

{#if view && endingProduct}
  <EndProductPanel
    product={endingProduct}
    remaining={active.filter((p) => p.id !== endingProduct.id)}
    source={view.source}
    {unit}
    onclose={() => (ending = '')}
    ondone={async (result) => {
      const name = endingProduct?.name ?? '';
      ending = '';
      view = result.view;
      toast(
        result.moved > 0
          ? t('{name} ended. {count} open {unit} moved to another product. Undo until you save.', { name, count: result.moved, unit })
          : t('{name} ended. Undo until you save.', { name }),
        'ok',
        { label: t('Undo'), run: () => void undo(result.undo) },
      );
    }}
  />
{/if}

<style>
  .name {
    width: 170px;
  }
  .share {
    width: 64px;
    text-align: right;
  }
  .nowrap {
    flex-wrap: nowrap;
  }
  .end {
    justify-content: flex-end;
  }
  .rule-txt {
    font-variant-ligatures: none;
    font-feature-settings: 'calt' 0, 'liga' 0;
  }
  .actions {
    white-space: nowrap;
  }
  .note {
    margin: 8px 0 0;
  }
  .ended {
    margin-top: 16px;
  }
  .ended summary {
    cursor: pointer;
  }
  .below {
    margin-top: 16px;
  }
  .pick {
    max-width: 240px;
    margin-bottom: 8px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
