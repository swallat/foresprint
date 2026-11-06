<script lang="ts">
  // The filter chips of ticket lists (product, project, progress, sort, group). The state is the
  // backlog's own (`ui`), so the choice follows you from Backlog to Pre-plan, Plan and Review.
  import Icon from '../../lib/Icon.svelte';
  import type { Named } from '../../lib/types.backlog';
  import { blank, chipsOn, type Group, type Sort } from './backlog';
  import { setLayout, t, ui } from './store.svelte';

  const ALL_SORTS: Sort[] = ['rank', 'order', 'size-desc', 'size-asc', 'key', 'title'];

  let {
    products,
    projects,
    multi = true,
    sorts = ALL_SORTS,
    groups = true,
    layout = false,
    groupNone = true,
  }: {
    products: Named[];
    projects: Named[];
    /** False for a team with one product: no product chips, no grouping by product. */
    multi?: boolean;
    sorts?: Sort[];
    groups?: boolean;
    layout?: boolean;
    /** False where the list is always grouped (Pre-plan: by project unless by product). */
    groupNone?: boolean;
  } = $props();

  const sortNames: Record<Sort, string> = $derived({
    rank: t('Rank in the tracker'),
    order: t('Planning order'),
    'size-desc': t('Largest first'),
    'size-asc': t('Smallest first'),
    key: t('Key'),
    title: t('Title'),
  });
  const toggle = (list: string[], value: string): string[] => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const active = $derived(chipsOn(ui.filter));
</script>

{#if multi && products.length}
  <div class="row" role="group" aria-label={t('Product')}>
    <span class="small muted">{t('Product')}</span>
    {#each products as p (p.id)}
      <button type="button" class="chip filter" class:on={ui.filter.products.includes(p.id)} aria-pressed={ui.filter.products.includes(p.id)} onclick={() => (ui.filter.products = toggle(ui.filter.products, p.id))}>{p.name}</button>
    {/each}
  </div>
{/if}
<div class="row" role="group" aria-label={t('Project')}>
  <span class="small muted">{t('Project')}</span>
  {#each projects.filter((p) => !p.closed) as p (p.id)}
    <button type="button" class="chip filter" class:on={ui.filter.projects.includes(p.id)} aria-pressed={ui.filter.projects.includes(p.id)} onclick={() => (ui.filter.projects = toggle(ui.filter.projects, p.id))}><Icon name="flag" size={14} />{p.name}</button>
  {/each}
  <button type="button" class="chip filter" class:on={ui.filter.projects.includes('')} aria-pressed={ui.filter.projects.includes('')} onclick={() => (ui.filter.projects = toggle(ui.filter.projects, ''))}>{t('Daily business')}</button>
  <span class="small muted gap">{t('Progress')}</span>
  <button type="button" class="chip filter" class:on={ui.filter.refined === 'yes'} aria-pressed={ui.filter.refined === 'yes'} onclick={() => (ui.filter.refined = ui.filter.refined === 'yes' ? 'all' : 'yes')}>{t('Refined')}</button>
  <button type="button" class="chip filter" class:on={ui.filter.refined === 'open'} aria-pressed={ui.filter.refined === 'open'} onclick={() => (ui.filter.refined = ui.filter.refined === 'open' ? 'all' : 'open')}><Icon name="help" size={14} />{t('Still open')}</button>
  {#if sorts.length}
    <span class="small muted gap">{t('Sort by')}</span>
    <select class="input sort" aria-label={t('Sort by')} bind:value={ui.sort}>
      {#each sorts as value (value)}<option {value}>{sortNames[value]}</option>{/each}
    </select>
  {/if}
  {#if layout}
    <span class="small muted gap">{t('Layout')}</span>
    <button type="button" class="chip filter" class:on={ui.layout === 'side'} aria-pressed={ui.layout === 'side'} onclick={() => setLayout('side')}><Icon name="vertical_split" size={14} />{t('Side by side')}</button>
    <button type="button" class="chip filter" class:on={ui.layout === 'stacked'} aria-pressed={ui.layout === 'stacked'} onclick={() => setLayout('stacked')}><Icon name="splitscreen" size={14} />{t('Stacked')}</button>
  {/if}
  {#if groups}
    <span class="small muted gap">{t('Group by')}</span>
    {#each [...(groupNone ? [['none', t('Nothing')]] : []), ['project', t('Project')], ...(multi ? [['product', t('Product')]] : [])] as [value, label] (value)}
      <button type="button" class="chip filter" class:on={ui.group === value || (!groupNone && ui.group === 'none' && value === 'project')} aria-pressed={ui.group === value || (!groupNone && ui.group === 'none' && value === 'project')} onclick={() => (ui.group = value as Group)}>{label}</button>
    {/each}
  {/if}
  {#if active}
    <button type="button" class="btn ghost" onclick={() => { const q = ui.filter.q; ui.filter = { ...blank(), q }; }}><Icon name="filter_alt_off" />{t('Reset filter')}</button>
  {/if}
</div>

<style>
  .gap {
    margin-left: 8px;
  }
</style>
