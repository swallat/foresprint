<script lang="ts">
  // The presentation view: one ticket fills the window, the arrow keys step through the list.
  // Made for sharing a single window in planning and refinement meetings (flows.md F10), so the
  // ticket details sit here and nothing else has to be opened.
  import { onMount } from 'svelte';
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
    import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import type { TicketDetail } from '../../lib/types.backlog';
  import { productColor } from './backlog';
  import { loadBacklog, present, store, allTickets, t } from './backlog.svelte';
  import { openExternal } from './external';

  let { params }: PageProps = $props();
  void params;

  let detail = $state<TicketDetail | undefined>();
  let error = $state('');
  let busy = $state(false);
  let closeButton: HTMLButtonElement | undefined = $state();

  const view = $derived(store.view);
  const index = $derived(present.keys.indexOf(present.key));
  const packages = $derived(view?.source === 'packages');
  const product = $derived(view?.products.find((p) => p.id === detail?.product));
  const project = $derived(view?.projects.find((p) => p.id === detail?.project));
  const unit = $derived(view?.unit === 'PT' ? t('person days') : t('points'));

  onMount(async () => {
    app.ticket = '';
    if (!store.view) await loadBacklog();
    if (present.keys.length === 0) {
      // opened by address: show what is earmarked, then the backlog
      const v = store.view;
      const keys = v ? [...v.lanes.flatMap((l) => l.tickets), ...v.tickets].map((tk) => tk.key) : [];
      present.keys = keys;
      present.key = keys[0] ?? '';
    }
    closeButton?.focus();
  });

  $effect(() => {
    void store.view;
    const key = present.key;
    if (!key) {
      detail = undefined;
      return;
    }
    api
      .Ticket(app.team, key)
      .then((d) => {
        if (key === present.key) {
          detail = d;
          error = '';
        }
      })
      .catch((e) => {
        if (key === present.key) error = String(e);
      });
  });

  function step(by: number): void {
    const next = present.keys[index + by];
    if (next) present.key = next;
  }
  function close(): void {
    location.hash = present.from || '#/backlog';
  }
  async function act(): Promise<void> {
    if (!present.action || !present.key || busy) return;
    busy = true;
    try {
      await present.action.run(present.key);
    } finally {
      busy = false;
    }
  }

  function keys(e: KeyboardEvent): void {
    if ((e.target as HTMLElement).closest('input, textarea, select')) return;
    if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'Escape') close();
    else if (e.key === ' ' && present.action) {
      e.preventDefault();
      void act();
    } else return;
  }

  const when = (iso: string) => (iso ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso)) : '');
  const titleOf = (key: string) => allTickets(view).find((tk) => tk.key === key)?.title ?? '';
</script>

<svelte:window onkeydown={keys} />

<div class="present" role="dialog" aria-modal="true" aria-label={detail ? `${detail.key} ${detail.title}` : t('Presentation view')}>
  <div class="present-head">
    {#if detail}
      {#if detail.url && !packages}
        <a class="key" href={detail.url} onclick={(e) => { e.preventDefault(); openExternal(detail!.url); }}>{detail.key}<Icon name="open_in_new" size={14} /></a>
      {:else}
        <span class="key data">{detail.key}</span>
      {/if}
      {#if detail.status}<span class="chip">{detail.status}</span>{/if}
      {#if detail.refined}<span class="chip ok"><Icon name="check" size={14} />{t('Refined')}</span>{:else}<span class="chip">{t('Not refined')}</span>{/if}
      {#if view?.multi && product}<span class="chip"><span class="dot" style:background={productColor(view, product.id)}></span>{product.name}</span>{/if}
      {#if project}<span class="chip"><Icon name="flag" size={14} />{project.name}</span>{/if}
    {/if}
    <span class="grow"></span>
    {#if present.keys.length > 0}<span class="small muted data">{t('{n} of {total}', { n: index + 1, total: present.keys.length })}</span>{/if}
    <button class="btn icon" type="button" aria-label={t('Previous ticket')} title={t('Previous ticket')} disabled={index <= 0} onclick={() => step(-1)}><Icon name="chevron_left" /></button>
    <button class="btn icon" type="button" aria-label={t('Next ticket')} title={t('Next ticket')} disabled={index < 0 || index >= present.keys.length - 1} onclick={() => step(1)}><Icon name="chevron_right" /></button>
    <button class="btn icon ghost" type="button" bind:this={closeButton} aria-label={t('Close presentation view')} title={t('Close presentation view')} onclick={close}><Icon name="close" /></button>
  </div>

  {#if detail}
    <div class="present-body">
      <div class="present-main">
        <h1>{detail.title}</h1>
        {#if detail.description}<section class="td-sec"><h3>{t('Description')}</h3><p class="prose">{detail.description}</p></section>{/if}
        {#if detail.acceptance}
          <section class="td-sec">
            <h3>{t('Acceptance criteria')}</h3>
            <ul class="td-list">{#each detail.acceptance.split('\n').filter((l) => l.trim()) as line, i (i)}<li>{line}</li>{/each}</ul>
          </section>
        {/if}
        {#if detail.subtasks.length}
          <section class="td-sec">
            <h3>{t('Subtasks')}</h3>
            <ul class="td-list">{#each detail.subtasks as s, i (i)}<li class:done={s.done}>{s.title}</li>{/each}</ul>
          </section>
        {/if}
        {#if detail.dependencies.length}
          <section class="td-sec">
            <h3>{t('Dependencies')}</h3>
            <ul class="td-list">
              {#each detail.dependencies as d (d.key)}
                <li><span class="muted">{t('needs')}</span> <span class="key data">{d.key}</span> {d.title || titleOf(d.key)}
                  {#if d.earmark}<span class="chip"><Icon name="event" size={14} />{d.earmark}</span>{:else}<span class="chip warn">{t('not earmarked')}</span>{/if}</li>
              {/each}
            </ul>
          </section>
        {/if}
        {#if detail.comments.length}
          <section class="td-sec">
            <h3>{t('Comments')}</h3>
            {#each detail.comments as c, i (i)}
              <div class="td-comment"><div class="small"><strong>{c.author || t('Note')}</strong> <span class="muted data">{when(c.at)}</span></div><div>{c.text}</div></div>
            {/each}
          </section>
        {/if}
        {#if !detail.description && !detail.acceptance && !detail.subtasks.length}
          <p class="muted">{t('No description fetched yet.')}</p>
        {/if}
      </div>
      <aside class="present-side">
        <div class="present-est">
          <span class="data">{detail.size ?? '?'}</span><span class="small muted">{unit}</span>
        </div>
        {#if present.action}
          <div class="card stack">
            <button class="btn" class:primary={!present.action.active(detail.key)} type="button" disabled={busy} onclick={act}>
              <Icon name={present.action.active(detail.key) ? 'undo' : 'add'} />{present.action.label(detail.key)}
            </button>
          </div>
        {/if}
        <dl class="kv">
          <dt>{t('Earmarked for')}</dt>
          <dd>{#if detail.earmark}<span class="data">{t('Sprint {id}', { id: detail.earmark })}</span>{:else}<span class="muted">{t('Not earmarked')}</span>{/if}</dd>
          {#if detail.epic}<dt>{t('Epic')}</dt><dd>{detail.epic}</dd>{/if}
          {#if detail.type}<dt>{t('Type')}</dt><dd>{detail.type}</dd>{/if}
          {#if detail.priority}<dt>{t('Priority')}</dt><dd>{detail.priority}</dd>{/if}
          {#if detail.assignee}<dt>{t('Assignee')}</dt><dd>{detail.assignee}</dd>{/if}
          {#if detail.labels.length}<dt>{t('Labels')}</dt><dd>{detail.labels.join(', ')}</dd>{/if}
          {#if detail.trackerSprint}<dt>{t('Sprint in {tracker}', { tracker: view?.tracker ?? '' })}</dt><dd class="data">{detail.trackerSprint}</dd>{/if}
        </dl>
        <p class="small muted flush">
          {t('Arrow keys step through, Esc closes.')}
          {#if present.action}{t('Space does the action above.')}{/if}
        </p>
      </aside>
    </div>
  {:else if error}
    <div class="present-body"><div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div></div>
  {:else}
    <div class="present-body"><p class="muted">{present.keys.length === 0 && store.view ? t('There is nothing to show.') : t('Loading…')}</p></div>
  {/if}
</div>

<style>
  .grow {
    flex: 1;
  }
  .flush {
    margin: 0;
  }
  .prose {
    white-space: pre-wrap;
    margin: 0;
  }
  .done {
    text-decoration: line-through;
    color: var(--text-muted);
  }
</style>
