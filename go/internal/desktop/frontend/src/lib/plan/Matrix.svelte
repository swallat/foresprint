<script lang="ts">
  // The table product x project of the pre-planning: how much of each product goes into which
  // project. What is left of a product is daily business. The sums are a hint, never a block;
  // "Take the sums" sets the pre-planned amounts of products (raised, never lowered) and
  // projects from the table.
  import { api } from '../api';
  import { app } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { PlanSprint } from '../types.plan';
  import { parseAmount, unitName, type PlanModel, fmtVal } from './model.svelte';

  interface Props {
    d: PlanSprint;
    model: PlanModel;
    readonly?: boolean;
  }
  let { d, model, readonly = false }: Props = $props();

  const matrix = $derived(d.matrix);
  const products = $derived(d.products.filter((p) => p.active));
  const cell = (product: string, project: string) => matrix?.cells.find((c) => c.product === product && c.project === project)?.value ?? 0;
  const rowSum = (product: string) => matrix?.cells.filter((c) => c.product === product).reduce((a, c) => a + c.value, 0) ?? 0;
  const colSum = (project: string) => matrix?.cells.filter((c) => c.project === project).reduce((a, c) => a + c.value, 0) ?? 0;
  const total = $derived(matrix?.cells.reduce((a, c) => a + c.value, 0) ?? 0);
  /** A product whose row takes more than its pre-planned amount. */
  const over = (product: string, pre: number | null) => pre != null && rowSum(product) > pre + 1e-9;
  const raise = $derived(products.some((p) => rowSum(p.id) > (p.pre ?? p.default ?? 0) + 1e-9));

  async function set(product: string, project: string, text: string): Promise<void> {
    const v = parseAmount(text);
    if (v === undefined) return void model.reload();
    await model.change(() => api.SetMatrixCell(app.team, d.sprint, product, project, v));
  }
  const take = () => model.change(() => api.UseMatrix(app.team, d.sprint), t('Sums taken as the pre-planned amounts.'));
</script>

{#if matrix && matrix.cells.length + products.length > 0}
  <section id="matrix" class="gap" data-tour="preplan-matrix">
    <div class="row head">
      <h2 id="matrix-h">{t('Products in projects')}</h2>
      <button class="btn" type="button" id="use-matrix" disabled={readonly || matrix.cells.length === 0} onclick={take}>
        <Icon name="calculate" />{t('Take the sums')}
      </button>
    </div>
    <div class="tw">
      <table class="t" aria-labelledby="matrix-h">
        <thead>
          <tr>
            <th scope="col">{t('Product')}</th>
            {#each matrix.projects as pr (pr.id)}<th scope="col" class="num">{pr.name}</th>{/each}
            <th scope="col" class="num">{t('Daily business')}</th>
          </tr>
        </thead>
        <tbody>
          {#each products as p (p.id)}
            {@const rest = (p.pre ?? p.default ?? 0) - rowSum(p.id)}
            <tr>
              <th scope="row">{p.name}</th>
              {#each matrix.projects as pr (pr.id)}
                <td class="num edit">
                  <input
                    inputmode="decimal"
                    value={cell(p.id, pr.id) || ''}
                    placeholder="–"
                    disabled={readonly}
                    aria-label={t('{product} in {project} ({unit})', { product: p.name, project: pr.name, unit: unitName(d) })}
                    onchange={(e) => set(p.id, pr.id, e.currentTarget.value)}
                  />
                </td>
              {/each}
              <td class="num">
                {#if over(p.id, p.pre ?? p.default)}<span class="chip warn">{t('{n} over the amount', { n: fmtVal(-rest) })}</span>{:else}{fmtVal(rest)}{/if}
              </td>
            </tr>
          {/each}
          <tr class="sum">
            <th scope="row">{t('Total')}</th>
            {#each matrix.projects as pr (pr.id)}<td class="num">{fmtVal(colSum(pr.id))}</td>{/each}
            <td class="num">{fmtVal(total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="small muted gap">
      {raise
        ? t('Some rows take more than the amount of the product; “Take the sums” raises it.')
        : t('What a product has left after its projects is daily business. The amounts are in {unit}.', { unit: unitName(d) })}
    </p>
  </section>
{/if}

<style>
  .gap {
    margin-top: 8px;
  }
</style>
