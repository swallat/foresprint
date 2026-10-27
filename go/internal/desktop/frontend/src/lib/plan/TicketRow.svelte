<script lang="ts">
  // One ticket (or work package) in a lane: key with link to the tracker, title, product,
  // project, refinement state, production share and estimate. Drag with the handle, or use the
  // button; Alt+arrow moves between lanes (handled by the lane).
  import { openTicket } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { PlanSprint, PlanTicket } from '../types.plan';
  import { fmt, fmtVal } from './model.svelte';

  interface Props {
    ticket: PlanTicket;
    d: PlanSprint;
    drag?: boolean;
    showProduct?: boolean;
    showProject?: boolean;
    /** Label of the move button; it is only shown when onmove is given. */
    moveLabel?: string;
    moveIcon?: 'arrow_forward' | 'arrow_back';
    onmove?: () => void;
    ondragstart?: (e: DragEvent) => void;
    ondragend?: () => void;
  }
  let { ticket, d, drag = false, showProduct = true, showProject = true, moveLabel = '', moveIcon = 'arrow_forward', onmove, ondragstart, ondragend }: Props = $props();
  const product = $derived(d.products.find((p) => p.id === ticket.product));
  const project = $derived(d.projects.find((p) => p.id === ticket.project));
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
  class="ticket"
  data-key={ticket.key}
  draggable={drag}
  role="listitem"
  tabindex="0"
  {ondragstart}
  {ondragend}
>
  <span class="handle" aria-hidden="true">{#if drag}<Icon name="drag_indicator" />{/if}</span>
  <span class="key">
    <button class="linkbtn data" type="button" onclick={() => openTicket(ticket.key)}>{ticket.key}</button>
    {#if ticket.url}
      <a href={ticket.url} target="_blank" rel="noreferrer" aria-label={t('Open {key} in the tracker', { key: ticket.key })}>
        <Icon name="open_in_new" size={14} />
      </a>
    {/if}
  </span>
  <span class="title" title={ticket.title}>{ticket.title}</span>
  <span class="chips">
    {#if !ticket.refined}<span class="chip warn">{t('not refined')}</span>{/if}
    {#if ticket.size == null}<span class="chip warn">{t('no estimate')}</span>{/if}
    {#if showProduct && d.multiProduct && product}<span class="chip">{product.name}</span>{/if}
    {#if showProject && project}<span class="chip"><Icon name="flag" size={14} />{project.name}</span>{/if}
    {#if d.production && ticket.prodPct > 0}
      <span class="chip" title={t('Production share')}>{t('Prod {pct} %', { pct: fmt(ticket.prodPct, 1) })}</span>
    {/if}
  </span>
  <span class="end">
    <span class="est">{ticket.size == null ? '–' : fmtVal(ticket.size)}</span>
    {#if onmove}
      <button class="btn icon ghost" type="button" aria-label={moveLabel} onclick={onmove}>
        <Icon name={moveIcon} />
      </button>
    {/if}
  </span>
</div>

<style>
  /* Narrow lanes: chips go below the title, estimate and button stay at the right. */
  .ticket { grid-template-columns: 20px 92px minmax(0, 1fr) auto; grid-template-areas: 'h k ti e' '. . m m'; row-gap: 4px; }
  .handle { grid-area: h; }
  .key { grid-area: k; display: flex; gap: 4px; align-items: center; }
  .title { grid-area: ti; }
  .chips { grid-area: m; display: flex; flex-wrap: wrap; gap: 6px; }
  .chips:empty { display: none; }
  .end { grid-area: e; display: flex; gap: 4px; align-items: center; justify-content: flex-end; }
  .est { min-width: 2ch; text-align: right; }
</style>
