<script lang="ts">
  // The side panel for one ticket, open on every page (app.ticket holds the key). A tracker
  // ticket is read from the tracker; here the PO sets product, project, an own estimate, the
  // production share and the earmark. A work package is edited completely in a form. The key NEW
  // opens the form for a new work package (flows.md section 5, "ticket panel"; decision 15).
  import { untrack } from 'svelte';
  import { fmt } from '../../lib/format';
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
    import Icon from '../../lib/Icon.svelte';
  import type { TicketDetail, WorkPackageInput } from '../../lib/types.backlog';
  import { NEW, allTickets, changed, openPresent, store, t } from './store.svelte';
  import { openExternal } from './external';

  let detail = $state<TicketDetail | undefined>();
  let draft = $state<WorkPackageInput | undefined>();
  let error = $state('');
  let confirmDelete = $state(false);
  let newSub = $state('');
  let newComment = $state('');
  let newDep = $state('');
  let loadId = 0;

  const view = $derived(store.view);
  const creating = $derived(app.ticket === NEW);
  const packages = $derived(view?.source === 'packages');
  const others = $derived(allTickets(view).filter((tk) => tk.key !== app.ticket));
  const lanes = $derived(detail?.sprints ?? view?.lanes.map((l) => l.sprint) ?? []);
  const dirty = $derived(draft !== undefined && JSON.stringify(draft) !== JSON.stringify(fromDetail(detail)));

  function blankDraft(): WorkPackageInput {
    return {
      key: '', title: '', status: 'New', type: 'Story', priority: '', assignee: '', product: view?.products[0]?.id ?? '', project: '',
      estimate: null, refined: false, labels: [], description: '', acceptance: '', subtasks: [], dependsOn: [], comments: [], done: false,
    };
  }

  function fromDetail(d: TicketDetail | undefined): WorkPackageInput | undefined {
    if (!d) return undefined;
    return {
      key: d.key, title: d.title, status: d.status, type: d.type, priority: d.priority, assignee: d.assignee, product: d.product,
      project: d.project, estimate: d.estimate, refined: d.refined, labels: [...d.labels], description: d.description,
      acceptance: d.acceptance, subtasks: d.subtasks.map((s) => ({ ...s })), dependsOn: [...d.dependsOn],
      comments: d.comments.map((c) => ({ ...c })), done: false,
    };
  }

  async function load(): Promise<void> {
    const id = ++loadId;
    error = '';
    confirmDelete = false;
    if (app.ticket === NEW) {
      detail = undefined;
      draft = untrack(blankDraft);
      return;
    }
    try {
      const d = await api.Ticket(app.team, app.ticket);
      if (id !== loadId) return;
      detail = d;
      draft = d.editable ? fromDetail(d) : undefined;
    } catch (e) {
      if (id === loadId) {
        detail = undefined;
        draft = undefined;
        error = String(e);
      }
    }
  }

  $effect(() => {
    void app.ticket;
    void app.team;
    void load();
  });

  // The list changes elsewhere (drag, filter reload): the panel shows the new state of its ticket.
  $effect(() => {
    void store.view;
    if (app.ticket && app.ticket !== NEW && !dirty) void load();
  });

  async function run(action: () => Promise<unknown>, done = ''): Promise<boolean> {
    try {
      await action();
      error = '';
      await changed();
      if (done) toast(done, 'ok');
      return true;
    } catch (e) {
      error = String(e);
      return false;
    }
  }

  function close(): void {
    app.ticket = '';
  }

  function number(text: string): number | null {
    const v = parseFloat(text.replace(',', '.'));
    return Number.isFinite(v) ? v : null;
  }

  // --- tracker ticket --------------------------------------------------------------------
  const ruleProduct = $derived(detail && !detail.productSet ? detail.product : '');
  async function assign(product: string, project: string): Promise<void> {
    if (!detail) return;
    const daily = project === '__daily';
    await run(() => api.SetAssignment(app.team, detail!.key, product, daily ? '' : project, daily));
  }
  const productSelect = $derived(detail?.productSet ? detail.product : '');
  const projectSelect = $derived(detail?.projectSet ? (detail.project === '' ? '__daily' : detail.project) : '');
  const productName = (id: string) => view?.products.find((p) => p.id === id)?.name ?? '';
  const projectName = (id: string) => view?.projects.find((p) => p.id === id)?.name ?? '';

  // --- work package ----------------------------------------------------------------------
  async function saveDraft(): Promise<void> {
    if (!draft) return;
    const input = { ...draft, done: draft.status === 'Done' };
    try {
      const key = await api.SaveWorkPackage(app.team, input);
      error = '';
      await changed();
      toast(creating ? t('{key} created and placed first in its priority.', { key }) : t('{key} saved.', { key }), 'ok');
      app.ticket = key;
      await load();
    } catch (e) {
      error = String(e);
    }
  }

  async function remove(): Promise<void> {
    if (!detail) return;
    const key = detail.key;
    if (await run(() => api.DeleteWorkPackage(app.team, key))) {
      toast(t('{key} deleted.', { key }), 'ok');
      close();
    }
  }

  async function duplicate(): Promise<void> {
    if (!draft) return;
    try {
      const key = await api.SaveWorkPackage(app.team, { ...draft, key: '', title: t('{title} (copy)', { title: draft.title }), comments: [] });
      await changed();
      toast(t('Copied as {key}.', { key }), 'ok');
      app.ticket = key;
    } catch (e) {
      error = String(e);
    }
  }

  function addSub(): void {
    if (!draft || !newSub.trim()) return;
    draft.subtasks.push({ title: newSub.trim(), done: false });
    newSub = '';
  }
  function addDep(): void {
    if (!draft || !newDep || draft.dependsOn.includes(newDep)) return;
    draft.dependsOn.push(newDep);
    newDep = '';
  }
  function addComment(): void {
    if (!draft || !newComment.trim()) return;
    draft.comments.push({ author: '', at: new Date().toISOString(), text: newComment.trim() });
    newComment = '';
  }
  const titleOf = (key: string) => allTickets(view).find((tk) => tk.key === key)?.title ?? '';

  const when = (iso: string) => (iso ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso)) : '');
  const unit = $derived(view?.unit === 'PT' ? t('person days') : t('points'));
</script>

<aside class="panel" data-tour="ticket-panel" aria-label={packages ? t('Work package') : t('Ticket')}>
  <div class="panel-head">
    <strong class="data">{creating ? t('New work package') : app.ticket}</strong>
    {#if detail?.status}<span class="chip">{detail.status}</span>{/if}
    <span class="grow"></span>
    {#if detail}
      <button class="btn" type="button" title={t('Show the ticket large in the window, step with the arrow keys')} onclick={() => openPresent(others.length ? [detail!.key, ...others.map((o) => o.key)] : [detail!.key], detail!.key)}>
        <Icon name="fit_screen" />{t('Presentation view')}
      </button>
    {/if}
    <button class="btn icon ghost" type="button" aria-label={t('Close')} title={t('Close')} onclick={close}><Icon name="close" /></button>
  </div>

  <div class="panel-body">
    {#if error}
      <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
    {/if}

    {#if draft && (packages || creating)}
      <!-- ============ work package form ============ -->
      <div class="field">
        <label for="wp-title">{t('Title')}</label>
        <input class="input" id="wp-title" bind:value={draft.title} placeholder={t('e.g. write the release notes')} />
      </div>
      <dl class="kv">
        <dt><label for="wp-status">{t('Status')}</label></dt>
        <dd>
          <select class="input" id="wp-status" bind:value={draft.status}>
            {#each (detail?.statuses ?? ['New', 'In progress', 'In review', 'Done']) as s (s)}<option value={s}>{s}</option>{/each}
          </select>
        </dd>
        <dt><label for="wp-type">{t('Type')}</label></dt>
        <dd class="row nowrap">
          <select class="input" id="wp-type" bind:value={draft.type}>
            {#each (detail?.types ?? ['Story', 'Bug', 'Task']) as s (s)}<option value={s}>{s}</option>{/each}
          </select>
          <select class="input" aria-label={t('Priority')} bind:value={draft.priority}>
            <option value="">{t('No priority')}</option>
            {#each (detail?.priorities ?? ['Highest', 'High', 'Medium', 'Low', 'Lowest']) as s (s)}<option value={s}>{s}</option>{/each}
          </select>
        </dd>
        <dt><label for="wp-who">{t('Assignee')}</label></dt>
        <dd>
          <select class="input" id="wp-who" bind:value={draft.assignee}>
            <option value="">{t('Nobody')}</option>
            {#each (detail?.people ?? []) as p (p)}<option value={p}>{p}</option>{/each}
          </select>
        </dd>
        {#if view?.multi}
          <dt><label for="wp-product">{t('Product')}</label></dt>
          <dd>
            <select class="input" id="wp-product" bind:value={draft.product}>
              {#each view.products as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
            </select>
          </dd>
        {/if}
        <dt><label for="wp-project">{t('Project')}</label></dt>
        <dd>
          <select class="input" id="wp-project" bind:value={draft.project}>
            <option value="">{t('Daily business')}</option>
            {#each (view?.projects ?? []).filter((p) => !p.closed) as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </dd>
        <dt><label for="wp-est">{t('Estimate')}</label></dt>
        <dd class="row nowrap">
          <input class="input data short" id="wp-est" inputmode="decimal" value={draft.estimate ?? ''} placeholder="–" onchange={(e) => { if (draft) draft.estimate = number(e.currentTarget.value); }} />
          <span class="small muted">{unit}</span>
        </dd>
        <dt>{t('Refined')}</dt>
        <dd><label class="row nowrap"><input type="checkbox" bind:checked={draft.refined} /><span class="small">{t('clarified in refinement')}</span></label></dd>
        <dt><label for="wp-labels">{t('Labels')}</label></dt>
        <dd><input class="input" id="wp-labels" value={draft.labels.join(', ')} placeholder={t('comma separated')} onchange={(e) => { if (draft) draft.labels = e.currentTarget.value.split(',').map((x) => x.trim()).filter(Boolean); }} /></dd>
      </dl>
      <div class="field">
        <label for="wp-desc">{t('Description')}</label>
        <textarea class="input" id="wp-desc" rows="4" bind:value={draft.description} placeholder={t('What should be achieved?')}></textarea>
      </div>
      <div class="field">
        <label for="wp-ac">{t('Acceptance criteria')} <span class="muted small">{t('one per line')}</span></label>
        <textarea class="input" id="wp-ac" rows="3" bind:value={draft.acceptance}></textarea>
      </div>

      <section class="td-sec">
        <h3>{t('Subtasks')} <span class="muted small">{draft.subtasks.length}</span></h3>
        {#each draft.subtasks as s, i (i)}
          <div class="row nowrap">
            <label class="row nowrap grow"><input type="checkbox" bind:checked={s.done} /><span class:done={s.done}>{s.title}</span></label>
            <button class="btn icon ghost" type="button" aria-label={t('Remove')} title={t('Remove')} onclick={() => draft?.subtasks.splice(i, 1)}><Icon name="close" size={16} /></button>
          </div>
        {/each}
        <div class="row nowrap">
          <input class="input grow" placeholder={t('New subtask')} aria-label={t('New subtask')} bind:value={newSub} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addSub(); } }} />
          <button class="btn" type="button" onclick={addSub}><Icon name="add" />{t('Add')}</button>
        </div>
      </section>

      <section class="td-sec">
        <h3>{t('Dependencies')}</h3>
        {#if draft.dependsOn.length === 0}
          <p class="muted small flush">{t('None. Pre-planning warns when a package is earmarked before the one it needs.')}</p>
        {:else}
          <ul class="td-list">
            {#each draft.dependsOn as k, i (k)}
              <li class="row nowrap"><span class="muted">{t('needs')}</span> <span class="key data">{k}</span> <span class="grow">{titleOf(k)}</span>
                <button class="btn icon ghost" type="button" aria-label={t('Remove')} title={t('Remove')} onclick={() => draft?.dependsOn.splice(i, 1)}><Icon name="close" size={16} /></button></li>
            {/each}
          </ul>
        {/if}
        <div class="row nowrap">
          <select class="input grow" aria-label={t('Work package')} bind:value={newDep}>
            <option value="">{t('Choose a work package')}</option>
            {#each others.filter((o) => !draft?.dependsOn.includes(o.key)) as o (o.key)}<option value={o.key}>{o.key} {o.title}</option>{/each}
          </select>
          <button class="btn" type="button" onclick={addDep}><Icon name="add_link" />{t('Link')}</button>
        </div>
      </section>

      <section class="td-sec">
        <h3>{t('Comments')} <span class="muted small">{draft.comments.length}</span></h3>
        {#each draft.comments as c, i (i)}
          <div class="td-comment">
            <div class="small"><strong>{c.author || t('Note')}</strong> <span class="muted data">{when(c.at)}</span></div>
            <div>{c.text}</div>
          </div>
        {/each}
        <div class="row nowrap">
          <input class="input grow" placeholder={t('Comment')} aria-label={t('Comment')} bind:value={newComment} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addComment(); } }} />
          <button class="btn" type="button" onclick={addComment}><Icon name="send" />{t('Add')}</button>
        </div>
      </section>

      {#if detail}
        <section class="td-sec">
          <h3>{t('Earmarked for')}</h3>
          {@render earmarkRow()}
        </section>
      {/if}

      <p class="small muted flush">{t('Changes go to the team data (arbeitspakete.yaml) and to the others with Save in the top bar. Attachments are not kept; write links into the description.')}</p>
      <div class="row">
        <button class="btn primary" type="button" disabled={!dirty && !creating} onclick={saveDraft}><Icon name="check" />{creating ? t('Create') : t('Save changes')}</button>
        {#if dirty && !creating}<button class="btn" type="button" onclick={load}>{t('Discard')}</button>{/if}
        {#if !creating}
          <button class="btn" type="button" onclick={duplicate}><Icon name="content_copy" />{t('Duplicate')}</button>
          {#if confirmDelete}
            <button class="btn danger" type="button" onclick={remove}><Icon name="delete" />{t('Yes, delete')}</button>
            <button class="btn ghost" type="button" onclick={() => (confirmDelete = false)}>{t('Keep')}</button>
          {:else}
            <button class="btn danger" type="button" onclick={() => (confirmDelete = true)}><Icon name="delete" />{t('Delete')}</button>
          {/if}
        {/if}
      </div>
    {:else if detail}
      <!-- ============ tracker ticket ============ -->
      <h2 class="flush">{detail.title}</h2>
      {#if detail.url}
        <p class="flush"><a class="key" href={detail.url} onclick={(e) => { e.preventDefault(); openExternal(detail!.url); }}>{t('Open in {tracker}', { tracker: view?.tracker ?? '' })}<Icon name="open_in_new" size={14} /></a></p>
      {/if}
      {#if detail.blocked}
        <div class="banner warn"><Icon name="block" /><div class="grow">{t('A ticket it depends on is not planned early enough. Earmark that one first or in the same sprint.')}</div></div>
      {/if}
      <dl class="kv">
        {#if view?.multi}
          <dt><label for="tp-product">{t('Product')}</label></dt>
          <dd>
            <select class="input" id="tp-product" value={productSelect} onchange={(e) => assign(e.currentTarget.value, projectSelect)}>
              <option value="">{ruleProduct ? t('By rule: {name}', { name: productName(ruleProduct) }) : t('By rule: none')}</option>
              {#each view.products as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
            </select>
          </dd>
        {/if}
        <dt><label for="tp-project">{t('Project')}</label></dt>
        <dd>
          <select class="input" id="tp-project" value={projectSelect} onchange={(e) => assign(productSelect, e.currentTarget.value)}>
            <option value="">{!detail.projectSet && detail.project ? t('By rule: {name}', { name: projectName(detail.project) }) : t('By rule: daily business')}</option>
            <option value="__daily">{t('Daily business')}</option>
            {#each (view?.projects ?? []).filter((p) => !p.closed) as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </dd>
        <dt><label for="tp-est">{t('Estimate')}</label></dt>
        <dd>
          {#if detail.estimate != null || detail.remaining != null}
            <span class="data">{fmt(detail.size)} {unit}</span> <span class="muted small">{t('from {tracker}', { tracker: view?.tracker ?? '' })}</span>
          {:else}
            <span class="row nowrap">
              <input class="input data short" id="tp-est" inputmode="decimal" value={detail.size ?? ''} placeholder="–" aria-describedby="tp-est-hint" onchange={(e) => run(() => api.SetEstimate(app.team, detail!.key, number(e.currentTarget.value)))} />
              <span class="small muted">{unit}</span>
            </span>
            <span class="small muted" id="tp-est-hint">{t('Your own estimate, until the tracker has one.')}</span>
          {/if}
        </dd>
        {#if view?.production}
          <dt><label for="tp-prod">{t('Production share')}</label></dt>
          <dd class="row nowrap">
            <input class="input data short" id="tp-prod" inputmode="numeric" value={detail.production ?? ''} placeholder="–" onchange={(e) => run(() => api.SetProduction(app.team, detail!.key, number(e.currentTarget.value)))} />
            <span class="small muted">{t('% need production access, 100 = only people with access')}</span>
          </dd>
        {/if}
        <dt>{t('Refined')}</dt>
        <dd>{#if detail.refined}<span class="chip ok"><Icon name="check" size={14} />{t('yes')}</span>{:else}<span class="chip warn">{detail.refinedUnclear ? t('unclear') : t('no')}</span>{/if}</dd>
        <dt>{t('Earmarked for')}</dt>
        <dd>{@render earmarkRow()}</dd>
        {#if detail.trackerSprint}
          <dt>{t('Sprint in {tracker}', { tracker: view?.tracker ?? '' })}</dt>
          <dd class="data">{detail.trackerSprint}</dd>
        {/if}
      </dl>
      {#if detail.ruleHint}
        <div class="banner warn">
          <Icon name="rule" />
          <div class="grow">
            {#if detail.ruleHint === 'none'}{t('No product rule matches this ticket. Set the product here or edit the rules under Team, Products.')}
            {:else if detail.ruleHint === 'several'}{t('Several product rules match: {names}. Set the product here or make the rules exclusive.', { names: (detail.ruleProducts ?? []).map(productName).join(', ') })}
            {:else}{t('A product rule would give {name}, but the project decides.', { name: productName(detail.ruleProducts?.[0] ?? '') })}{/if}
          </div>
        </div>
      {/if}

      <h2 class="flush">{t('From {tracker}', { tracker: view?.tracker ?? '' })} <span class="chip">{t('read only')}</span></h2>
      <dl class="kv">
        {#if detail.type}<dt>{t('Type')}</dt><dd>{detail.type}</dd>{/if}
        {#if detail.priority}<dt>{t('Priority')}</dt><dd>{detail.priority}</dd>{/if}
        {#if detail.assignee}<dt>{t('Assignee')}</dt><dd>{detail.assignee}</dd>{/if}
        {#if detail.epic}<dt>{t('Epic')}</dt><dd>{detail.epic}</dd>{/if}
        {#if detail.components.length}<dt>{t('Components')}</dt><dd>{detail.components.join(', ')}</dd>{/if}
        {#if detail.labels.length}<dt>{t('Labels')}</dt><dd>{detail.labels.join(', ')}</dd>{/if}
      </dl>
      {@render readOnlyDetails()}
    {:else if !error}
      <p class="muted">{t('Loading…')}</p>
    {/if}
  </div>
</aside>

{#snippet earmarkRow()}
  {#if detail}
    <div class="stack tight">
      <select class="input" aria-label={t('Earmarked for')} value={detail.earmark} disabled={detail.fixed} onchange={(e) => run(() => api.EarmarkTicket(app.team, detail!.key, e.currentTarget.value, detail!.note))}>
        <option value="">{t('Not earmarked')}</option>
        {#each lanes as s (s)}<option value={s}>{t('Sprint {id}', { id: s })}</option>{/each}
        {#if detail.earmark && !lanes.includes(detail.earmark)}<option value={detail.earmark}>{t('Sprint {id}', { id: detail.earmark })}</option>{/if}
      </select>
      {#if detail.earmark}
        <label class="small muted" for="tp-note">{t('Note on the earmark')}</label>
        <textarea class="input" id="tp-note" rows="2" placeholder={t('e.g. agreed with the product owner')} value={detail.note} onchange={(e) => run(() => api.SetEarmarkNote(app.team, detail!.key, e.currentTarget.value))}></textarea>
      {/if}
    </div>
  {/if}
{/snippet}

{#snippet readOnlyDetails()}
  {#if detail}
    {#if detail.description}
      <section class="td-sec"><h3>{t('Description')}</h3><p class="prose">{detail.description}</p></section>
    {/if}
    {#if detail.acceptance}
      <section class="td-sec"><h3>{t('Acceptance criteria')}</h3><p class="prose">{detail.acceptance}</p></section>
    {/if}
    {#if detail.dependencies.length}
      <section class="td-sec">
        <h3>{t('Dependencies')}</h3>
        <ul class="td-list">
          {#each detail.dependencies as d (d.key)}
            <li><span class="muted">{t('needs')}</span> <button class="link data" type="button" onclick={() => (app.ticket = d.key)}>{d.key}</button> {d.title}
              {#if d.earmark}<span class="chip"><Icon name="event" size={14} />{d.earmark}</span>{/if}</li>
          {/each}
        </ul>
      </section>
    {/if}
    {#if !detail.description && !detail.acceptance}
      <p class="muted small flush">{t('No description fetched yet.')}</p>
    {/if}
  {/if}
{/snippet}

<style>
  .grow {
    flex: 1;
    min-width: 0;
  }
  .flush {
    margin: 0;
  }
  .nowrap {
    flex-wrap: nowrap;
  }
  .short {
    width: 80px;
    text-align: right;
  }
  .tight {
    gap: 4px;
  }
  .done {
    text-decoration: line-through;
    color: var(--text-muted);
  }
  .prose {
    white-space: pre-wrap;
    margin: 0;
  }
  dd {
    min-width: 0;
  }
  dd :global(.input) {
    max-width: 100%;
  }
</style>
