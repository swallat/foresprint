<script lang="ts">
  import { fmt, fmtVal } from '../../lib/format';
  // One ticket in a list or a lane: handle, selection, key, title, chips, estimate. Click on the
  // title (or Enter) opens the ticket panel; Alt+Right/Left earmarks for the next sprint or back
  // (the keyboard way of dragging).
  import { openTicket } from '../../lib/app.svelte';
    import Icon from '../../lib/Icon.svelte';
  import type { BacklogTicket, BacklogView } from '../../lib/types.backlog';
  import { productColor } from './backlog';
  import { t } from './store.svelte';
  import { openExternal } from './external';

  interface Props {
    ticket: BacklogTicket;
    view: BacklogView;
    selectable?: boolean;
    checked?: boolean;
    draggable?: boolean;
    /** Name for the guided flows (data-tour). */
    tour?: string;
    showProduct?: boolean;
    showProject?: boolean;
    onselect?: (on: boolean) => void;
    ondragstart?: (e: DragEvent) => void;
    ondragend?: () => void;
    /** Moves one lane: 1 = next sprint, -1 = back. */
    onstep?: (step: -1 | 1) => void;
    /** Right click: the "Send to" menu. */
    oncontext?: (e: MouseEvent) => void;
  }
  let {
    ticket: tk,
    view,
    selectable = false,
    checked = false,
    draggable = false,
    tour = undefined,
    showProduct = true,
    showProject = true,
    onselect,
    ondragstart,
    ondragend,
    onstep,
    oncontext,
  }: Props = $props();

  const packages = $derived(view.source === 'packages');
  const product = $derived(view.products.find((p) => p.id === tk.product));
  const project = $derived(view.projects.find((p) => p.id === tk.project));
  const hint = $derived(
    tk.ruleHint === 'none'
      ? t('Product rule without a match')
      : tk.ruleHint === 'several'
        ? t('Several product rules match')
        : tk.ruleHint === 'project'
          ? t('Product rule disagrees with the project')
          : '',
  );

  function key(e: KeyboardEvent): void {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      openTicket(tk.key);
    } else if (e.altKey && e.key === 'ArrowRight') {
      e.preventDefault();
      onstep?.(1);
    } else if (e.altKey && e.key === 'ArrowLeft') {
      e.preventDefault();
      onstep?.(-1);
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="ticket"
  data-tour={tour}
  class:selected={checked}
  class:withbox={selectable}
  data-key={tk.key}
  role="group"
  tabindex="0"
  draggable={draggable}
  aria-label={`${tk.key} ${tk.title}`}
  onkeydown={key}
  ondragstart={ondragstart}
  ondragend={ondragend}
  oncontextmenu={oncontext}
>
  {#if selectable}
    <input type="checkbox" class="sel" {checked} aria-label={t('Select {key}', { key: tk.key })} onchange={(e) => onselect?.(e.currentTarget.checked)} />
  {/if}
  <span class="handle" title={draggable ? t('Drag into a sprint') : ''}>{#if draggable}<Icon name="drag_indicator" />{/if}</span>
  <span class="key">
    {#if tk.url && !packages}
      <a href={tk.url} onclick={(e) => { e.preventDefault(); openExternal(tk.url); }} title={t('Open in the tracker')}>{tk.key}<Icon name="open_in_new" size={14} /></a>
    {:else}
      <span class="data">{tk.key}</span>
    {/if}
  </span>
  <button type="button" class="title linkish" onclick={() => openTicket(tk.key)}>{tk.title}</button>
  <span class="meta">
    {#if tk.size == null}<span class="chip warn"><Icon name="help" size={14} />{t('No estimate')}</span>{/if}
    {#if hint}<button type="button" class="chip warn" data-tour="backlog-ruleflag" title={hint} onclick={() => openTicket(tk.key)}><Icon name="rule" size={14} />{t('Rule without a match')}</button>{/if}
    {#if tk.subtaskCount}<span class="chip" title={t('Sub-tasks left out of the import')}><Icon name="visibility_off" size={14} />{tk.subtaskCount === 1 ? t('1 sub-task') : t('{n} sub-tasks', { n: tk.subtaskCount })}</span>{/if}
    {#if tk.blocked}<span class="chip bad" title={t('A ticket it depends on is not planned early enough')}><Icon name="block" size={14} />{t('Blocked')}</span>{/if}
    {#if tk.refined}<span class="chip ok"><Icon name="check" size={14} />{t('Refined')}</span>{:else}<span class="chip">{t('Not refined')}</span>{/if}
    {#if showProduct && view.multi && product}<span class="chip" title={product.name}><span class="dot" style:background={productColor(view, product.id)}></span>{product.name}</span>{/if}
    {#if showProject && project}<span class="chip" title={project.name}><Icon name="flag" size={14} />{project.name}</span>{/if}
    {#if view.production && tk.production}<span class="chip" title={t('Share that needs production access')}><span class="data">{fmt(tk.production, 1)} %</span> {t('Prod')}</span>{/if}
    <span class="est" class:muted={tk.size == null} title={tk.size == null ? t('No estimate') : ''}>{tk.size == null ? '?' : fmtVal(tk.size)}</span>
  </span>
</div>

<style>
  .ticket {
    grid-template-columns: 20px 92px minmax(0, 1fr);
    row-gap: 2px;
  }
  .ticket.withbox {
    grid-template-columns: 22px 20px 92px minmax(0, 1fr);
  }
  .ticket .title {
    white-space: normal;
    text-align: left;
  }
  .ticket .meta {
    grid-column: 3 / -1;
    flex-wrap: wrap;
  }
  .ticket.withbox .meta {
    grid-column: 3 / -1;
  }
  .est {
    margin-left: auto;
  }
  .sel {
    margin: 0;
    width: 16px;
    height: 16px;
    accent-color: var(--primary);
  }
  .linkish {
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    color: var(--text);
    min-width: 0;
  }
  .linkish:hover {
    text-decoration: underline;
  }
  button.chip {
    cursor: pointer;
    border: 0;
  }
  @media (max-width: 700px) {
    .ticket,
    .ticket.withbox {
      grid-template-columns: 22px 20px minmax(0, 1fr);
    }
  }
</style>
