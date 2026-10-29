<script lang="ts">
  // Sprint > Minutes (flows.md D23): the Markdown files that each save of pre-planning, planning
  // and review writes into protokolle/. Superseded versions stay as files and are marked.
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { parse, type Inline } from '../../lib/markdown';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';
  import SprintFigures from '../../lib/plan/SprintFigures.svelte';
  import SprintMeta from '../../lib/sprints/SprintMeta.svelte';
  import StageNav from '../../lib/sprints/StageNav.svelte';
  import type { MinutesRow, MinutesText } from '../../lib/types.review';

  let { params }: PageProps = $props();
  void params;

  let all = $state(false);
  let rows = $state<MinutesRow[]>([]);
  let open = $state<{ row: MinutesRow; text: MinutesText } | undefined>();
  let error = $state('');
  let loaded = $state(false);

  let seq = 0;
  async function load() {
    if (!app.team) return;
    const mine = ++seq;
    try {
      const next = await api.SprintMinutes(app.team, all ? '' : app.sprint);
      if (mine !== seq) return;
      rows = next;
      error = '';
      loaded = true;
      shown++; // a file asked for before the list changed is not shown
      open = undefined;
    } catch (e) {
      if (mine === seq) error = String(e);
    }
  }

  $effect(() => {
    void [app.team, app.sprint, all];
    void load();
  });

  const kindName = (k: MinutesRow['kind']) => (k === 'review' ? t('Review') : k === 'planning' ? t('Sprint planning') : t('Pre-planning'));

  let shown = 0;
  async function show(row: MinutesRow) {
    const mine = ++shown;
    try {
      const text = await api.MinutesText(app.team, row.file);
      if (mine !== shown) return; // another file was asked for meanwhile
      open = { row, text };
      error = '';
    } catch (e) {
      error = String(e);
    }
  }

  async function openFile(path: string) {
    try {
      await api.OpenFile(path);
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  async function copyPath(path: string) {
    try {
      await navigator.clipboard.writeText(path);
      toast(t('Path copied.'));
    } catch {
      toast(path);
    }
  }

  const blocks = $derived(open ? parse(open.text.text) : []);
</script>

{#snippet spans(parts: Inline[])}{#each parts as p, i (i)}{#if p.bold}<strong>{p.text}</strong>{:else}{p.text}{/if}{/each}{/snippet}

<PageHead title={t('Sprint minutes')} lead={t('Every save of the pre-planning, the planning and the review writes a minutes file.')} />
<SprintMeta />
<StageNav stage="minutes" />

{#if app.team && app.sprint}<SprintFigures />{/if}

{#if error}
  <div class="banner bad" role="alert"><Icon name="error" /><div class="grow">{error}</div></div>
{/if}

<div class="row bar">
  <button type="button" class="chip filter" class:on={!all} aria-pressed={!all} onclick={() => (all = false)}>{t('Only sprint {id}', { id: app.sprint })}</button>
  <button type="button" class="chip filter" class:on={all} aria-pressed={all} onclick={() => (all = true)}>{t('All sprints')}</button>
  <span class="small muted end">{t('The files live in the folder protokolle/ and go to the team with the next save.')}</span>
</div>

{#if loaded && rows.length === 0}
  <div class="banner info" role="status">
    <Icon name="description" />
    <div class="grow">{all ? t('There are no minutes yet.') : t('There are no minutes for {id} yet. They appear when you save the pre-planning, the planning or the review.', { id: app.sprint })}</div>
  </div>
{:else if rows.length > 0}
  <div class="tw">
    <table class="t">
      <thead>
        <tr>
          <th scope="col">{t('Sprint')}</th>
          <th scope="col">{t('Kind')}</th>
          <th scope="col">{t('Written')}</th>
          <th scope="col">{t('File')}</th>
          <th scope="col">{t('Version state')}</th>
          <th scope="col"><span class="sr">{t('Open')}</span></th>
        </tr>
      </thead>
      <tbody>
        {#each rows as r (r.file)}
          <tr class:old={r.obsolete} class:sel={open?.row.file === r.file}>
            <td class="data">{r.sprint}</td>
            <td>{kindName(r.kind)}</td>
            <td class="data">{r.at}</td>
            <td class="data file">{r.file}</td>
            <td>
              {#if r.obsolete}
                <span class="chip warn"><Icon name="history" size={14} />{t('superseded')}</span>
              {:else}
                <span class="chip ok">{t('current')}</span>
              {/if}
            </td>
            <td>
              <button type="button" class="btn" onclick={() => show(r)} aria-label={t('Show {file}', { file: r.file })}>
                <Icon name="visibility" />{t('Show')}
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

{#if open}
  <section class="card doc" aria-labelledby="doc-h">
    <div class="row head">
      <h2 id="doc-h">{kindName(open.row.kind)} {open.row.sprint}</h2>
      {#if open.row.obsolete}<span class="chip warn"><Icon name="history" size={14} />{t('superseded')}</span>{/if}
      <span class="grow"></span>
      <button type="button" class="btn" onclick={() => open && openFile(open.text.path)}><Icon name="open_in_new" />{t('Open as file')}</button>
      <button type="button" class="btn" onclick={() => open && copyPath(open.text.path)}><Icon name="content_copy" />{t('Copy path')}</button>
      <button type="button" class="btn ghost icon" aria-label={t('Close')} onclick={() => (open = undefined)}><Icon name="close" /></button>
    </div>
    <p class="small muted data file">{open.row.file}</p>
    <div class="md">
      {#each blocks as b, i (i)}
        {#if b.kind === 'h1'}<h3>{@render spans(b.inline)}</h3>
        {:else if b.kind === 'h2' || b.kind === 'h3'}<h4>{@render spans(b.inline)}</h4>
        {:else if b.kind === 'p'}<p>{@render spans(b.inline)}</p>
        {:else if b.kind === 'ul'}
          <ul>{#each b.items as item, j (j)}<li>{@render spans(item)}</li>{/each}</ul>
        {:else if b.kind === 'table'}
          <div class="tw">
            <table class="t">
              <thead><tr>{#each b.head as h, j (j)}<th scope="col">{@render spans(h)}</th>{/each}</tr></thead>
              <tbody>
                {#each b.rows as row, j (j)}<tr>{#each row as c, k (k)}<td>{@render spans(c)}</td>{/each}</tr>{/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/each}
    </div>
  </section>
{/if}

<style>
  .bar {
    margin-bottom: 12px;
  }
  .end {
    margin-left: auto;
  }
  tr.old td {
    color: var(--text-muted);
  }
  tr.old .file {
    text-decoration: line-through;
  }
  tr.sel td {
    background: var(--primary-weak);
  }
  .doc {
    margin-top: 16px;
  }
  .head h2 {
    margin: 0;
    font: 600 16px/24px var(--font-ui);
  }
  .grow {
    flex: 1;
  }
  .md h3 {
    margin: 8px 0;
    font: 600 18px/26px var(--font-ui);
  }
  .md h4 {
    margin: 16px 0 6px;
    font: 600 14px/20px var(--font-ui);
  }
  .md p,
  .md ul {
    margin: 4px 0;
    max-width: 90ch;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
</style>
