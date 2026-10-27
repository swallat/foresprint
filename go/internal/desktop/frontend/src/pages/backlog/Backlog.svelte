<script lang="ts">
  // The backlog: all open tickets (or work packages) in planning order, saved views as filters
  // of the one list, and lanes for the coming sprints to earmark into (flows.md F2, F10).
  import { app, selectSprint, syncTracker, toast } from '../../lib/app.svelte';
  import { tick } from 'svelte';
  import { language } from '../../lib/i18n.svelte';
  import Calc from '../../lib/calc/Calc.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { BacklogTicket } from '../../lib/types.backlog';
  import { fmt, formatPeriod, fmtVal } from '../../lib/format';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import { VIEWS, activeView, activeCustom, applyView, blank, group, matches, neighbour, sortTickets, sum, type Group, type Sort } from './backlog';
  import { NEW, allTickets, applyCustomView, deleteCustomView, earmark, loadBacklog, loadCustomViews, openPresent, reorder, resetOrder, saveCustomView, setLayout, store, t, toProForma, toggleSelected, ui } from './store.svelte';
  import TicketRow from './TicketRow.svelte';

  let { params }: PageProps = $props();
  void params;

  const view = $derived(store.view);
  const packages = $derived(view?.source === 'packages');
  const names = $derived({
    product: (id: string) => view?.products.find((p) => p.id === id)?.name ?? '',
    project: (id: string) => view?.projects.find((p) => p.id === id)?.name ?? t('Daily business'),
  });

  $effect(() => {
    void app.team;
    void loadBacklog();
    loadCustomViews();
  });

  // "Earmarked" lists the earmarked tickets too; every other view lists the backlog.
  const pool = $derived.by(() => {
    if (!view) return [] as BacklogTicket[];
    return ui.filter.flag === 'earmarked' ? allTickets(view).filter((tk) => tk.earmark) : view.tickets;
  });
  const items = $derived(sortTickets(pool.filter((tk) => matches(tk, ui.filter, names, view?.multi ?? false)), ui.sort));
  // Long lists render in steps (a sentinel at the end asks for the next step as it scrolls into
  // view), so that the filter stays instant with thousands of tickets.
  const STEP = 60;
  // Like Jira's "Show all issues": the lists start short and expand on request.
  const PREVIEW = 10;
  const LANE_PREVIEW = 5;
  let shown = $state(STEP);
  let backlogOpen = $state(false);
  let laneOpen = $state<Record<string, boolean>>({});
  let laneClosed = $state<Record<string, boolean>>({});
  const LANES_OPEN = 3;
  const laneIsClosed = (id: string, index: number): boolean => laneClosed[id] ?? index >= LANES_OPEN;
  $effect(() => {
    void ui.filter.q;
    void ui.filter.products;
    void ui.filter.projects;
    void ui.filter.refined;
    void ui.filter.flag;
    void ui.group;
    void ui.sort;
    shown = STEP;
  });
  const visible = $derived(items.slice(0, backlogOpen ? shown : PREVIEW));
  const sections = $derived(view ? group(visible, ui.group, view) : []);
  function more(node: HTMLElement): { destroy(): void } {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) shown += STEP;
    }, { rootMargin: '400px' });
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }
  const lanes = $derived(view?.lanes ?? []);
  // Lanes follow the rank too while that is the sort; any other sort leaves them in planning order.
  const laneTickets = (list: BacklogTicket[]): BacklogTicket[] => sortTickets(list, ui.sort === 'rank' ? 'rank' : 'order');
  const laneIds = $derived(lanes.map((l) => l.sprint));
  const current = $derived(activeView(ui.filter));
  const viewName: Record<string, string> = $derived({
    all: t('All'),
    daily: t('Daily business'),
    refinement: t('Refinement'),
    unassigned: t('Unassigned'),
    earmarked: t('Earmarked'),
    open: t('Open points'),
  });
  const sortNames = $derived<[Sort, string][]>([
    ['rank', t('Rank in the tracker')],
    ['order', t('Planning order')],
    ['size-desc', t('Largest first')],
    ['size-asc', t('Smallest first')],
    ['key', t('Key')],
    ['title', t('Title')],
  ]);
  const currentCustom = $derived(activeCustom(ui.custom, ui.filter, ui.group, ui.sort));
  let naming = $state(false);
  let newName = $state('');
  function saveView(): void {
    saveCustomView(newName);
    naming = false;
    newName = '';
  }

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function ago(iso: string): string {
    const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    const rtf = new Intl.RelativeTimeFormat(language(), { numeric: 'auto' });
    if (minutes < 60) return rtf.format(-minutes, 'minute');
    if (minutes < 60 * 24) return rtf.format(-Math.round(minutes / 60), 'hour');
    return rtf.format(-Math.round(minutes / 1440), 'day');
  }

  // --- drag and drop ---------------------------------------------------------------------
  let dragKeys = $state<string[]>([]);
  let overZone = $state('');

  function dragStart(e: DragEvent, tk: BacklogTicket): void {
    dragKeys = ui.selection.includes(tk.key) ? [...ui.selection] : [tk.key];
    e.dataTransfer?.setData('text/plain', dragKeys.join(','));
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  function dragEnd(): void {
    dragKeys = [];
    overZone = '';
    overRow = '';
  }
  function dragOver(e: DragEvent, zone: string): void {
    if (dragKeys.length === 0) return;
    e.preventDefault();
    overZone = zone;
  }
  async function drop(e: DragEvent, sprint: string): Promise<void> {
    e.preventDefault();
    const keys = dragKeys;
    dragEnd();
    await sendTo(keys, sprint);
  }
  async function dropPro(e: DragEvent, name: string): Promise<void> {
    e.preventDefault();
    const keys = dragKeys;
    dragEnd();
    await toProForma(keys.filter((k) => !fixedKeys.has(k)), name);
  }
  // Tickets out of a pro-forma sprint go back to the backlog or into a sprint lane.
  const fixedKeys = $derived(new Set(allTickets(view).filter((tk) => tk.fixed).map((tk) => tk.key)));
  const proKeys = $derived(new Set((view?.proForma ?? []).flatMap((p) => p.tickets.map((tk) => tk.key))));
  async function sendTo(keys: string[], sprint: string): Promise<void> {
    if (keys.some((k) => fixedKeys.has(k) && zoneOf(k) !== `lane:${sprint}`)) toast(t('This ticket is already in a Jira sprint. Move it in Jira.'), 'info');
    const fromPro = sprint === '' ? keys.filter((k) => proKeys.has(k)) : [];
    if (fromPro.length === 0) return earmark(keys, sprint);
    // One notice for the whole move: the earmark (if any) is taken away with it.
    const earmarked = keys.some((k) => allTickets(view).find((tk) => tk.key === k)?.earmark);
    await toProForma(fromPro, '', earmarked);
    if (earmarked) await earmark(keys, '');
  }
  async function step(tk: BacklogTicket, by: -1 | 1): Promise<void> {
    if (tk.fixed) return;
    const next = neighbour(laneIds, tk.earmark, by);
    if (next === undefined) return;
    if (next) {
      laneClosed[next] = false;
      laneOpen[next] = true;
    } else {
      backlogOpen = true;
    }
    await earmark([tk.key], next);
    document.querySelector<HTMLElement>(`.ticket[data-key="${tk.key}"]`)?.focus();
  }

  // Reordering: in the planning order, ungrouped. A tracker's own rank stays; the order is kept beside it.
  const canReorder = $derived(view?.source !== 'none' && (ui.sort === 'order' || ui.sort === 'rank') && ui.group === 'none');
  let overRow = $state('');
  // The list a ticket sits in ("" = a pro-forma sprint, not reorderable): the backlog or one sprint lane.
  // Reordering works inside one list, also for tickets the tracker has in a sprint (the order is only local).
  function zoneOf(key: string): string {
    if (items.some((x) => x.key === key)) return 'backlog'; // the main list, whatever it shows (also under the Earmarked filter)
    const lane = lanes.find((l) => l.tickets.some((x) => x.key === key));
    return lane ? `lane:${lane.sprint}` : '';
  }
  function listOf(zone: string): BacklogTicket[] {
    if (zone === 'backlog') return items;
    if (zone.startsWith('lane:')) return laneTickets(lanes.find((l) => l.sprint === zone.slice(5))?.tickets ?? []);
    return [];
  }
  function rowOver(e: DragEvent, tk: BacklogTicket): void {
    if (!canReorder || dragKeys.length !== 1 || dragKeys[0] === tk.key) return;
    const zone = zoneOf(tk.key);
    if (!zone || zoneOf(dragKeys[0] ?? '') !== zone) return; // another list: the lane's drop earmarks
    e.preventDefault();
    e.stopPropagation();
    overRow = tk.key;
  }
  async function rowDrop(e: DragEvent, tk: BacklogTicket): Promise<void> {
    if (overRow !== tk.key || dragKeys.length !== 1) return;
    e.preventDefault();
    e.stopPropagation();
    const key = dragKeys[0] ?? '';
    dragEnd();
    overRow = '';
    await reorder(key, tk.key);
  }
  async function rowKey(e: KeyboardEvent, tk: BacklogTicket): Promise<void> {
    if (!canReorder || !e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    const zone = zoneOf(tk.key);
    const list = listOf(zone);
    const i = list.findIndex((x) => x.key === tk.key);
    if (i < 0) return;
    e.preventDefault();
    if (e.key === 'ArrowUp') {
      if (!list[i - 1]) return;
      await reorder(tk.key, list[i - 1]!.key);
    } else {
      if (!list[i + 1]) return;
      if (zone === 'backlog') {
        shown = Math.max(shown, i + 3);
        backlogOpen = true;
      } else {
        laneOpen[zone.slice(5)] = true;
      }
      await reorder(tk.key, list[i + 1]!.key, true);
    }
    await tick();
    document.querySelector<HTMLElement>(`.ticket[data-key="${tk.key}"]`)?.focus();
  }

  // --- right-click menu: "Send to", as in Jira -------------------------------------------
  let ctx = $state<{ key: string; x: number; y: number } | null>(null);
  function openMenu(e: MouseEvent, tk: BacklogTicket): void {
    if ((e.target as HTMLElement).closest('a, input')) return; // keep the native menu on links
    e.preventDefault();
    ctx = { key: tk.key, x: Math.max(0, Math.min(e.clientX, window.innerWidth - 260)), y: Math.max(0, Math.min(e.clientY, window.innerHeight - 360)) };
  }
  const ctxKeys = $derived(ctx ? (ui.selection.includes(ctx.key) ? [...ui.selection] : [ctx.key]) : []);
  const ctxTicket = $derived(ctx ? allTickets(view).find((tk) => tk.key === ctx!.key) : undefined);
  async function ctxSprint(sprint: string): Promise<void> {
    const keys = ctxKeys;
    ctx = null;
    await sendTo(keys, sprint);
  }
  async function ctxPro(name: string): Promise<void> {
    const keys = ctxKeys.filter((k) => !fixedKeys.has(k));
    ctx = null;
    await toProForma(keys, name);
  }
  // Top or bottom of the backlog: out of any sprint first, then to the end of the order. The
  // order only moves among tickets of the same priority and project; the app says so if refused.
  async function ctxEdge(top: boolean): Promise<void> {
    const keys = ctxKeys.filter((k) => !fixedKeys.has(k));
    ctx = null;
    const away = keys.filter((k) => !(view?.tickets ?? []).some((tk) => tk.key === k));
    if (away.length) await sendTo(away, '');
    const anchor = sortTickets(view?.tickets ?? [], ui.sort === 'rank' ? 'rank' : 'order').find((tk) => !keys.includes(tk.key))?.key ?? '';
    ui.selection = ui.selection.filter((k) => !keys.includes(k));
    for (const key of keys) if (!(await reorder(key, top ? anchor : ''))) break;
  }

  // Top or bottom of the sprint the ticket is in: only its place in the order moves, also for
  // tickets the tracker has in that sprint. Several tickets keep their order.
  const ctxZone = $derived(ctx ? zoneOf(ctx.key) : '');
  async function ctxListEdge(top: boolean): Promise<void> {
    const zone = ctxZone;
    const list = listOf(zone);
    const keys = ctxKeys.filter((k) => zoneOf(k) === zone).sort((x, y) => list.findIndex((tk) => tk.key === x) - list.findIndex((tk) => tk.key === y));
    ctx = null;
    ui.selection = ui.selection.filter((k) => !keys.includes(k));
    const others = list.filter((tk) => !keys.includes(tk.key));
    if (others.length === 0) return;
    let prev = top ? others[0]!.key : others[others.length - 1]!.key;
    for (const key of keys) {
      if (!(await reorder(key, prev, !top))) break;
      if (!top) prev = key;
    }
  }

  const unit = $derived(view?.unit === 'PT' ? t('person days') : t('points'));
  const sprintTotal = (tickets: BacklogTicket[]) => sum(tickets);
</script>

{#if view?.source === 'none'}
  <PageHead title={t('Backlog')} lead={t('Without tickets there is no backlog.')} />
  <Banner>
    {t('Your team plans without tickets: amounts per product and project in Pre-plan, the commitment as a number in Plan. To keep work item by item, switch to work packages or a tracker in Settings, Tickets and tracker.')}
    {#snippet action()}
      <a class="btn" href={link('/settings/tickets')}>{t('Open settings')}</a>
    {/snippet}
  </Banner>
{:else}
  <PageHead
    title={t('Backlog')}
    lead={packages
      ? t('All work packages in one order. Views are filters of the same list. On the right you see what is earmarked for the coming sprints and whether it fits the forecast.')
      : t('All tickets in one order. Views are filters of the same list. On the right you see what is earmarked for the coming sprints and whether it fits the forecast.')}
  >
    {#snippet actions()}
      {#if packages}
        <button class="btn primary" type="button" onclick={() => (app.ticket = NEW)}><Icon name="add" />{t('Create work package')}</button>
      {/if}
      <button class="btn" type="button" disabled={!view} title={t('Show the tickets large in the window, for sharing in a meeting')} onclick={() => openPresent([...items.map((i) => i.key)], items[0]?.key ?? '')}>
        <Icon name="fit_screen" />{t('Presentation view')}
      </button>
    {/snippet}
  </PageHead>

  {#if store.error}
    <Banner tone="bad">
      {store.error}
      {#snippet action()}<button class="btn" type="button" onclick={() => loadBacklog()}><Icon name="refresh" />{t('Try again')}</button>{/snippet}
    </Banner>
  {/if}

  {#if view}
    {#if packages}
      <Banner>
        <strong>{t('Work packages in Foresprint, without a tracker.')}</strong>
        {t('There is no fetch. You create work packages by hand and keep estimate, product and project in the panel. Filters and sprint lanes work as with a tracker.')}
      </Banner>
    {:else if app.status.tracker.failed}
      <Banner tone="warn">
        {t('The fetch from {tracker} failed: {problem}. You work with the data of the last fetch.', { tracker: view.tracker, problem: app.status.tracker.failed })}
        {#snippet action()}<button class="btn" type="button" onclick={() => syncTracker()}><Icon name="refresh" />{t('Try again')}</button>{/snippet}
      </Banner>
    {:else}
      <p class="small muted sync" data-tour="backlog-sync">
        {#if view.imported}
          <Icon name="sync" size={14} />
          {t('{tracker}: last fetch {when}, {count} tickets.', { tracker: view.tracker, when: ago(view.imported), count: view.tickets.length + lanes.reduce((n, l) => n + l.tickets.length, 0) })}
        {:else}
          <Icon name="sync_disabled" size={14} />
          {t('{tracker}: no fetch yet.', { tracker: view.tracker })}
        {/if}
      </p>
    {/if}

    {#if view.drift}
      <Banner tone="warn">
        <strong>{t('Sprint {id}: the tracker differs from the frozen plan.', { id: view.drift.sprint })}</strong>
        {#if view.drift.pulledIn.length}
          {t('Pulled in after the freeze: {keys}.', { keys: view.drift.pulledIn.join(', ') })}
        {/if}
        {#if view.drift.dropped.length}
          {t('Left the sprint: {keys}.', { keys: view.drift.dropped.join(', ') })}
        {/if}
        {#if view.drift.unknown.length}
          {t('Not in the last fetch: {keys}.', { keys: view.drift.unknown.join(', ') })}
        {/if}
        {#snippet action()}<a class="btn" href={link('/sprint/plan')} onclick={() => view?.drift && selectSprint(view.drift.sprint)}>{t('Open Plan')}</a>{/snippet}
      </Banner>
    {/if}

    {#if view.adjust.length}
      <Banner tone="info">
        <strong>{t('Adjust in the tracker: the pro-forma sprint differs for {count} tickets.', { count: view.adjust.length })}</strong>
        <ul class="adjust">
          {#each view.adjust as a (a.key)}
            <li>
              {#if a.url}<a href={a.url} target="_blank" rel="noreferrer" class="data">{a.key}</a>{:else}<span class="data">{a.key}</span>{/if}
              {a.title}:
              {a.from || t('Backlog')} → {a.to || t('Backlog')}
            </li>
          {/each}
        </ul>
      </Banner>
    {/if}

    {#if view.cycles.length}
      <Banner tone="warn">{t('Some tickets depend on each other in a circle. They stay in the list but cannot be distributed. Open them and remove one dependency.')}</Banner>
    {/if}

    <div class="tabs" role="tablist" data-tour="backlog-views" aria-label={t('Saved views')}>
      {#each VIEWS as v (v.id)}
        <a
          href="#/backlog"
          role="tab"
          aria-selected={!currentCustom && current === v.id}
          class:active={!currentCustom && current === v.id}
          onclick={(e) => { e.preventDefault(); ui.filter = applyView(v.id, ui.filter.q); ui.sort = 'rank'; ui.group = 'none'; ui.selection = []; }}
        >{viewName[v.id]}</a>
      {/each}
      {#each ui.custom as v (v.id)}
        <a
          href="#/backlog"
          role="tab"
          aria-selected={currentCustom?.id === v.id}
          class:active={currentCustom?.id === v.id}
          onclick={(e) => { e.preventDefault(); applyCustomView(v); }}
        >{v.name}</a>
      {/each}
    </div>

    <div class="filters">
      {#if view.multi && view.products.length}
        <div class="row">
          <span class="small muted">{t('Product')}</span>
          {#each view.products as p (p.id)}
            <button type="button" class="chip filter" class:on={ui.filter.products.includes(p.id)} aria-pressed={ui.filter.products.includes(p.id)} onclick={() => (ui.filter.products = toggle(ui.filter.products, p.id))}>{p.name}</button>
          {/each}
        </div>
      {/if}
      <div class="row">
        <span class="small muted">{t('Project')}</span>
        {#each view.projects.filter((p) => !p.closed) as p (p.id)}
          <button type="button" class="chip filter" class:on={ui.filter.projects.includes(p.id)} aria-pressed={ui.filter.projects.includes(p.id)} onclick={() => (ui.filter.projects = toggle(ui.filter.projects, p.id))}><Icon name="flag" size={14} />{p.name}</button>
        {/each}
        <button type="button" class="chip filter" class:on={ui.filter.projects.includes('')} aria-pressed={ui.filter.projects.includes('')} onclick={() => (ui.filter.projects = toggle(ui.filter.projects, ''))}>{t('Daily business')}</button>
        <span class="small muted gap">{t('Progress')}</span>
        <button type="button" class="chip filter" class:on={ui.filter.refined === 'yes'} aria-pressed={ui.filter.refined === 'yes'} onclick={() => (ui.filter.refined = ui.filter.refined === 'yes' ? 'all' : 'yes')}>{t('Refined')}</button>
        <button type="button" class="chip filter" class:on={ui.filter.refined === 'open'} aria-pressed={ui.filter.refined === 'open'} onclick={() => (ui.filter.refined = ui.filter.refined === 'open' ? 'all' : 'open')}><Icon name="help" size={14} />{t('Still open')}</button>
        <span class="small muted gap">{t('Sort by')}</span>
        <select class="input sort" aria-label={t('Sort by')} bind:value={ui.sort}>
          {#each sortNames as [value, label] (value)}<option {value}>{label}</option>{/each}
        </select>
        <span class="small muted gap">{t('Layout')}</span>
        <button type="button" class="chip filter" class:on={ui.layout === 'side'} aria-pressed={ui.layout === 'side'} onclick={() => setLayout('side')}><Icon name="vertical_split" size={14} />{t('Side by side')}</button>
        <button type="button" class="chip filter" class:on={ui.layout === 'stacked'} aria-pressed={ui.layout === 'stacked'} onclick={() => setLayout('stacked')}><Icon name="splitscreen" size={14} />{t('Stacked')}</button>
        <span class="small muted gap">{t('Group by')}</span>
        {#each [['none', t('Nothing')], ['project', t('Project')], ...(view.multi ? [['product', t('Product')]] : [])] as [value, label] (value)}
          <button type="button" class="chip filter" class:on={ui.group === value} aria-pressed={ui.group === value} onclick={() => (ui.group = value as Group)}>{label}</button>
        {/each}
      </div>
      <div class="row">
        <label class="search-box">
          <Icon name="search" size={16} />
          <input class="input" type="search" bind:value={ui.filter.q} placeholder={t('Search: key, title, product, project')} autocomplete="off" aria-label={t('Search')} />
        </label>
        {#if currentCustom}
          <button class="btn ghost" type="button" onclick={() => deleteCustomView(currentCustom.id)}><Icon name="delete" />{t('Delete view “{name}”', { name: currentCustom.name })}</button>
        {:else if naming}
          <form class="row" onsubmit={(e) => { e.preventDefault(); saveView(); }}>
            <input class="input" bind:value={newName} placeholder={t('Name of the view')} aria-label={t('Name of the view')} autocomplete="off" />
            <button class="btn primary" type="submit" disabled={!newName.trim()}>{t('Save view')}</button>
            <button class="btn ghost" type="button" onclick={() => { naming = false; newName = ''; }}>{t('Cancel')}</button>
          </form>
        {:else}
          <button class="btn ghost" type="button" onclick={() => (naming = true)}><Icon name="bookmark_add" />{t('Save as view…')}</button>
        {/if}
      </div>
    </div>

    {#if ui.selection.length}
      <div class="banner info" role="region" aria-label={t('Selection')}>
        <Icon name="checklist" />
        <div class="grow">
          <strong class="data">{ui.selection.length}</strong> {t('selected')}
          <span class="row selbar">
            <button class="btn primary" type="button" aria-expanded={ui.menu} onclick={() => (ui.menu = !ui.menu)}><Icon name="event" />{t('Earmark for…')}<Icon name="keyboard_arrow_down" /></button>
            <button class="btn ghost" type="button" onclick={() => { ui.selection = []; ui.menu = false; }}>{t('Clear selection')}</button>
          </span>
          {#if ui.menu}
            <span class="row selbar" role="menu">
              {#each lanes as l (l.sprint)}
                <button class="btn" type="button" role="menuitem" onclick={() => earmark([...ui.selection], l.sprint)}><Icon name="event" />{t('Sprint {id}', { id: l.sprint })}</button>
              {/each}
              {#each view.source === 'tracker' ? view.proForma : [] as pf (pf.name)}
                <button class="btn" type="button" role="menuitem" onclick={() => toProForma(ui.selection.filter((k) => !fixedKeys.has(k)), pf.name)}><Icon name="inventory_2" />{pf.name}</button>
              {/each}
              <button class="btn" type="button" role="menuitem" onclick={() => sendTo([...ui.selection], '')}><Icon name="undo" />{t('Back to the backlog')}</button>
            </span>
          {/if}
        </div>
      </div>
    {/if}

    <div class="board" class:stacked={ui.layout === 'stacked'}>
      <div class="stack list" data-tour="backlog-list">
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="lane"
          class:over={overZone === 'backlog'}
          ondragover={(e) => dragOver(e, 'backlog')}
          ondragleave={() => (overZone = '')}
          ondrop={(e) => drop(e, '')}
        >
          <div class="lane-head">
            <div class="row">
              <strong>{t('Backlog')}</strong>
              <span class="chip data">{items.length}</span>
              <span class="muted small data">{fmtVal(sum(items))} {unit}</span>
              <Calc label={t('Backlog')} topic="sums">
                <span class="data">{t('{count} tickets in the list', { count: items.length })}</span><br />
                <span class="data">{t('Sum of the estimates: {sum} {unit}', { sum: fmtVal(sum(items)), unit })}</span><br />
                <span class="data">{t('Without estimate (count 0): {count}', { count: items.filter((tk) => tk.size == null).length })}</span><br />
                <span class="data">{t('Not refined: {count}', { count: items.filter((tk) => !tk.refined).length })}</span>
              </Calc>
            </div>
            {#if view.ownOrder}
              <button class="btn ghost" type="button" onclick={() => resetOrder()}><Icon name="undo" />{t('Back to the order of the tracker')}</button>
              <span class="small muted">{t('The next fetch takes over the order of the tracker again.')}</span>
            {/if}
            <span class="small muted">{ui.sort !== 'order' && ui.sort !== 'rank' ? t('Sorted by your choice. Choose the rank in the tracker or the planning order to see the list as planned.') : ui.sort === 'rank' ? (canReorder ? t('Order: your own order, then the rank in the tracker. Drop a ticket on another to put it before, or press Alt+Up or Alt+Down. Alt+Right earmarks for the next sprint.') : t('Order: your own order, then the rank in the tracker. To reorder, show the list ungrouped. Alt+Right earmarks for the next sprint.')) : canReorder ? t('Order: priority, then project, then your order. Drop a ticket on another to put it before, or press Alt+Up or Alt+Down. Alt+Right earmarks for the next sprint.') : t('Order: priority, then project, then your order. To reorder, show the list ungrouped. Alt+Right earmarks for the next sprint.')}</span>
          </div>
          <div class="lane-body">
            {#if items.length === 0}
              <div class="empty">
                {#if packages && allTickets(view).length === 0}
                  <p class="muted">{t('No open work packages. Create one, or import a table under Settings, Tickets and tracker.')}</p>
                  <button class="btn primary" type="button" onclick={() => (app.ticket = NEW)}><Icon name="add" />{t('Create work package')}</button>
                {:else}
                  <p class="muted">{packages ? t('No work package fits this filter.') : t('No ticket fits this filter.')}</p>
                  <button class="btn" type="button" onclick={() => { ui.filter = blank(); }}><Icon name="filter_alt_off" />{t('Reset filter')}</button>
                {/if}
              </div>
            {:else if ui.group === 'none'}
              {#each visible as tk (tk.key)}
                {@render row(tk, true, true)}
              {/each}
            {:else}
              {#each sections as s (s.id)}
                <div class="gh">
                  {#if s.kind === 'product'}<span class="dot"></span>{:else}<Icon name={s.id ? 'flag' : 'inventory_2'} size={16} />{/if}
                  {s.name || (s.kind === 'project' ? t('Daily business') : t('No product'))}
                  <span class="muted data count">{fmtVal(sum(s.items))} {unit}, {s.items.length}</span>
                </div>
                {#each s.items as tk (tk.key)}
                  {@render row(tk, s.kind !== 'product', s.kind !== 'project')}
                {/each}
              {/each}
            {/if}
            {#if !backlogOpen && items.length > PREVIEW}
              <div class="more">
                <button class="btn ghost" type="button" onclick={() => (backlogOpen = true)}>{t('Show all issues ({total})', { total: items.length })}</button>
              </div>
            {:else if backlogOpen && items.length > shown}
              <div class="more" use:more>
                <button class="btn" type="button" onclick={() => (shown += STEP)}>{t('Show more ({shown} of {total})', { shown, total: items.length })}</button>
              </div>
            {:else if backlogOpen && items.length > PREVIEW}
              <div class="more">
                <button class="btn ghost" type="button" onclick={() => (backlogOpen = false)}>{t('Show fewer issues')}</button>
              </div>
            {/if}
          </div>
        </div>

        {#each view.proForma as pf (pf.name)}
          {@const open = ui.open[pf.name] ?? false}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="lane" class:over={overZone === `pf:${pf.name}`} ondragover={(e) => view?.source === 'tracker' && dragOver(e, `pf:${pf.name}`)} ondragleave={() => (overZone = '')} ondrop={(e) => dropPro(e, pf.name)}>
            <div class="lane-head">
              <div class="row">
                <button class="btn ghost icon" type="button" aria-expanded={open} aria-label={open ? t('Collapse') : t('Expand')} onclick={() => (ui.open[pf.name] = !open)}>
                  <Icon name={open ? 'keyboard_arrow_up' : 'keyboard_arrow_down'} />
                </button>
                <strong>{pf.name}</strong>
                <span class="chip"><Icon name="inventory_2" size={14} />{t('Pro forma')}</span>
                <span class="chip data">{pf.tickets.length}</span>
                <span class="muted small data">{fmtVal(sprintTotal(pf.tickets))} {unit}</span>
              </div>
              <span class="small muted">{t('Not a real sprint: it never counts for capacity or forecast.')}</span>
            </div>
            {#if open}
              <div class="lane-body">
                {#if pf.tickets.length === 0}
                  <p class="muted small pad">{t('Empty.')}</p>
                {:else}
                  {#each pf.tickets as tk (tk.key)}
                    {@render row(tk, true, true)}
                  {/each}
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <div class="stack lanes" aria-label={t('Coming sprints')}>
        {#if lanes.length === 0}
          <div class="card muted">{t('There are no coming sprints yet. Add them under Team, Sprint calendar.')}</div>
        {/if}
        {#each lanes as l, li (l.sprint)}
          {@const used = sprintTotal(l.tickets)}
          {@const closed = laneIsClosed(l.sprint, li)}
          {@const over = l.plan != null && used > l.plan}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="lane" class:over={overZone === l.sprint} data-zone={l.sprint} ondragover={(e) => dragOver(e, l.sprint)} ondragleave={() => (overZone = '')} ondrop={(e) => drop(e, l.sprint)}>
            <div class="lane-head">
              <div class="row">
                <button class="btn ghost icon" type="button" aria-expanded={!closed} aria-label={closed ? t('Expand sprint {id}', { id: l.sprint }) : t('Collapse sprint {id}', { id: l.sprint })} onclick={() => (laneClosed[l.sprint] = !closed)}><Icon name={closed ? 'chevron_right' : 'keyboard_arrow_down'} /></button>
                <strong class="data">{l.sprint}</strong>
                <span class="muted small data">{formatPeriod(l.start, l.end)}</span>
                <span class="chip data" title={t('Earmarked tickets')}>{l.tickets.length}</span>
                <span class="grow"></span>
                {#if l.absences === 'confirmed'}
                  <span class="chip ok"><Icon name="check" size={14} />{t('Absences confirmed')}</span>
                {:else if l.absences === 'announced'}
                  <span class="chip warn"><Icon name="event_busy" size={14} />{t('Absences announced')}</span>
                {:else}
                  <span class="chip"><Icon name="event_busy" size={14} />{t('Absences open')}</span>
                {/if}
                <a class="small" href={link('/sprint/preplan')}>{t('Pre-plan')}</a>
              </div>
              <div class="cap" role="img" aria-label={l.plan != null ? t('{used} of {plan} {unit}', { used: fmtVal(used), plan: fmt(l.plan), unit }) : t('{used} {unit}', { used: fmtVal(used), unit })}>
                <div class="used" class:over style:width={`${l.plan ? Math.min(100, (used / l.plan) * 100) : 0}%`}></div>
              </div>
              <div class="row small">
                {#if l.plan != null}
                  <span class="data"><strong>{fmtVal(used)}</strong> {t('earmarked, Forecast PLAN {plan}', { plan: fmt(l.plan) })}</span>
                {:else}
                  <span class="data"><strong>{fmtVal(used)}</strong> {t('earmarked, no forecast yet')}</span>
                {/if}
                <Calc label={t('Earmarked in {sprint}', { sprint: l.sprint })} topic="sums">
                  <span class="data">{t('Sum of the estimates ({count} tickets): {sum} {unit}', { count: l.tickets.length, sum: fmtVal(used), unit })}</span><br />
                  <span class="data">{t('Without estimate (count 0): {count}', { count: l.tickets.filter((tk) => tk.size == null).length })}</span><br />
                  {#if l.plan != null}
                    <span class="data">{t('Forecast PLAN of the sprint: {plan} {unit}', { plan: fmt(l.plan), unit })}</span><br />
                    <span class="data">{t('Distance to the Forecast PLAN: {gap} {unit}', { gap: fmtVal(l.plan - used), unit })}</span>
                  {:else}
                    <span class="data">{t('No Forecast PLAN yet for this sprint.')}</span>
                  {/if}
                  {#if l.absences !== 'confirmed'}<br /><span>{t('Absences are not confirmed yet, the forecast can still change.')}</span>{/if}
                </Calc>
              </div>
              {#if over}
                <div class="banner bad flat"><Icon name="warning" /><div class="grow">{t('Above the Forecast PLAN: {used} of {plan}.', { used: fmtVal(used), plan: fmt(l.plan ?? 0) })}</div></div>
              {/if}
              {#if l.tickets.some((tk) => !tk.refined || tk.size == null)}
                <div class="row small muted">
                  <Icon name="help" size={14} />{t('{open} not refined, {none} without estimate (they count 0)', { open: l.tickets.filter((tk) => !tk.refined).length, none: l.tickets.filter((tk) => tk.size == null).length })}
                </div>
              {/if}
            </div>
            {#if !closed}
            <div class="lane-body">
              {#if l.tickets.length === 0}
                <p class="muted small pad">{t('Nothing earmarked yet. Drag a ticket here or use Earmark for…')}</p>
              {:else}
                {#each (laneOpen[l.sprint] ? laneTickets(l.tickets) : laneTickets(l.tickets).slice(0, LANE_PREVIEW)) as tk (tk.key)}
                  {@render row(tk, true, false)}
                {/each}
                {#if l.tickets.length > LANE_PREVIEW}
                  <div class="more">
                    <button class="btn ghost" type="button" onclick={() => (laneOpen[l.sprint] = !laneOpen[l.sprint])}>{laneOpen[l.sprint] ? t('Show fewer issues') : t('Show all issues ({total})', { total: l.tickets.length })}</button>
                  </div>
                {/if}
              {/if}
            </div>
            {/if}
          </div>
        {/each}
        {#if view.unmatchedSprints.length}
          <p class="small muted">{t('Jira sprints without a match in the sprint calendar: {names}. Add them under Team, Sprint calendar or map them in the tracker settings.', { names: view.unmatchedSprints.join(', ') })}</p>
        {/if}
        <p class="small muted">{t('The sprints always show everything earmarked, whatever the filter says.')}</p>
      </div>
    </div>
  {:else if store.loading}
    <p class="muted">{t('Loading…')}</p>
  {/if}
{/if}

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') ctx = null; }} onscroll={() => (ctx = null)} onresize={() => (ctx = null)} />

{#if ctx && view}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="ctx-backdrop" onclick={() => (ctx = null)} oncontextmenu={(e) => { e.preventDefault(); ctx = null; }}></div>
  <div class="ctx" role="menu" aria-label={t('Send to')} style:left={`${ctx.x}px`} style:top={`${ctx.y}px`}>
    <div class="ctx-title">{ctxKeys.length > 1 ? t('Send {n} tickets to', { n: ctxKeys.length }) : t('Send to')}</div>
    {#each lanes as l (l.sprint)}
      <button class="ctx-item" type="button" role="menuitem" disabled={ctxTicket?.fixed || (ctxKeys.length === 1 && ctxTicket?.earmark === l.sprint)} onclick={() => ctxSprint(l.sprint)}>
        <span class="data">{t('Sprint {id}', { id: l.sprint })}</span><span class="muted small data">{formatPeriod(l.start, l.end)}</span>
      </button>
    {/each}
    {#each view.source === 'tracker' ? view.proForma : [] as pf (pf.name)}
      <button class="ctx-item" type="button" role="menuitem" disabled={ctxTicket?.fixed} onclick={() => ctxPro(pf.name)}>{pf.name}</button>
    {/each}
    <button class="ctx-item" type="button" role="menuitem" disabled={ctxTicket?.fixed} onclick={() => ctxEdge(true)}>{t('Top of backlog')}</button>
    <button class="ctx-item" type="button" role="menuitem" disabled={ctxTicket?.fixed} onclick={() => ctxEdge(false)}>{t('Bottom of backlog')}</button>
    {#if ctxZone.startsWith('lane:')}
      <button class="ctx-item" type="button" role="menuitem" disabled={!canReorder} onclick={() => ctxListEdge(true)}>{t('Top of sprint')}</button>
      <button class="ctx-item" type="button" role="menuitem" disabled={!canReorder} onclick={() => ctxListEdge(false)}>{t('Bottom of sprint')}</button>
    {/if}
    {#if ctxTicket?.fixed}<div class="ctx-note small muted">{t('This ticket is already in a Jira sprint. Move it in Jira.')}</div>{/if}
  </div>
{/if}

{#snippet row(tk: BacklogTicket, showProduct: boolean, showProject: boolean)}
  {#if view}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="slot" class:over={overRow === tk.key} ondragover={(e) => rowOver(e, tk)} ondragleave={() => { if (overRow === tk.key) overRow = ''; }} ondrop={(e) => rowDrop(e, tk)} onkeydown={(e) => rowKey(e, tk)}>
    <TicketRow
      ticket={tk}
      {view}
      selectable
      draggable
      tour={tk.key === view.tickets[0]?.key ? 'backlog-ticket' : undefined}
      {showProduct}
      {showProject}
      checked={ui.selection.includes(tk.key)}
      onselect={(on) => toggleSelected(tk.key, on)}
      ondragstart={(e) => dragStart(e, tk)}
      ondragend={dragEnd}
      onstep={(by) => step(tk, by)}
      oncontext={(e) => openMenu(e, tk)}
    />
    </div>
  {/if}
{/snippet}

<style>
  .ctx-backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
  }
  .ctx {
    position: fixed;
    z-index: 51;
    width: 250px;
    max-height: 340px;
    overflow-y: auto;
    padding: 4px 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  }
  .ctx-title {
    padding: 6px 12px;
    font-weight: 600;
  }
  .ctx-item {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 6px 12px;
    background: none;
    border: 0;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .ctx-item:hover:not(:disabled),
  .ctx-item:focus-visible {
    background: var(--surface-2);
  }
  .ctx-item:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .ctx-note {
    padding: 6px 12px;
  }
  .slot.over {
    box-shadow: 0 -2px 0 0 var(--primary);
  }
  .board {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .filters {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 12px;
  }
  .gap {
    margin-left: 8px;
  }
  .adjust {
    margin: var(--space-1, 4px) 0 0;
    padding-left: 1.25rem;
  }
  .sync {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .search-box {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 200px;
    max-width: 360px;
    color: var(--text-muted);
  }
  .search-box .input {
    flex: 1;
  }
  .gh {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 6px 8px;
    background: var(--surface-2);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
  }
  .gh .count {
    font-weight: 400;
    font-size: 12px;
  }
  .empty {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
  }
  .empty p,
  .pad {
    margin: 0;
  }
  .pad {
    padding: 12px;
  }
  .lanes .lane-body {
    min-height: 56px;
  }
  .grow {
    flex: 1;
  }
  .more {
    padding: 12px;
    display: flex;
    justify-content: center;
  }
  .selbar {
    margin-top: 6px;
  }
  .flat {
    margin: 0;
  }
  /* Side by side, each column scrolls on its own, so a long sprint list does not push the backlog away. */
  .board:not(.stacked) .stack {
    position: sticky;
    top: 0;
    max-height: calc(100vh - 96px);
    overflow-y: auto;
  }
  /* Stacked, as in Jira: the sprints first, the backlog below. */
  .board.stacked {
    grid-template-columns: minmax(0, 1fr);
  }
  .board.stacked .lanes {
    order: -1;
  }
  @media (max-width: 1100px) {
    .board {
      grid-template-columns: minmax(0, 1fr);
    }
    .board:not(.stacked) .stack {
      position: static;
      max-height: none;
      overflow-y: visible;
    }
  }
</style>
