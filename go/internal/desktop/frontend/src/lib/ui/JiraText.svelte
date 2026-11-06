<script lang="ts">
  // Shows text as the tracker keeps it (Jira wiki markup) with headings, lists, bold, links and
  // so on. Rendered from parsed data, never as HTML (see lib/jiraWiki.ts).
  import { openExternal } from '../external';
  import { parseWiki, type WikiBlock, type WikiInline } from '../jiraWiki';

  let { text }: { text: string } = $props();
  const doc = $derived(parseWiki(text));
</script>

{#snippet inl(items: WikiInline[])}
  {#each items as n, i (i)}
    {#if n.t === 'text'}{n.v}
    {:else if n.t === 'br'}<br />
    {:else if n.t === 'b'}<strong>{@render inl(n.c)}</strong>
    {:else if n.t === 'i'}<em>{@render inl(n.c)}</em>
    {:else if n.t === 's'}<s>{@render inl(n.c)}</s>
    {:else if n.t === 'u'}<u>{@render inl(n.c)}</u>
    {:else if n.t === 'sup'}<sup>{@render inl(n.c)}</sup>
    {:else if n.t === 'sub'}<sub>{@render inl(n.c)}</sub>
    {:else if n.t === 'cite'}<cite>{@render inl(n.c)}</cite>
    {:else if n.t === 'code'}<code>{n.v}</code>
    {:else if n.t === 'img'}<span class="muted data">{n.name}</span>
    {:else if n.t === 'link'}<a href={n.href} onclick={(e) => { e.preventDefault(); openExternal(n.href); }}>{@render inl(n.c)}</a>
    {/if}
  {/each}
{/snippet}

{#snippet blk(items: WikiBlock[])}
  {#each items as b, i (i)}
    {#if b.t === 'p'}<p>{@render inl(b.c)}</p>
    {:else if b.t === 'h'}
      <p class="jh jh{Math.min(b.level, 4)}" role="heading" aria-level={Math.min(b.level + 3, 6)}>{@render inl(b.c)}</p>
    {:else if b.t === 'list'}
      {#if b.ordered}
        <ol>{#each b.items as it, k (k)}<li>{@render inl(it.c)}{@render blk(it.sub)}</li>{/each}</ol>
      {:else}
        <ul>{#each b.items as it, k (k)}<li>{@render inl(it.c)}{@render blk(it.sub)}</li>{/each}</ul>
      {/if}
    {:else if b.t === 'quote'}<blockquote>{@render blk(b.c)}</blockquote>
    {:else if b.t === 'panel'}
      <div class="panel">{#if b.title}<strong>{b.title}</strong>{/if}{@render blk(b.c)}</div>
    {:else if b.t === 'code'}<pre><code>{b.v}</code></pre>
    {:else if b.t === 'hr'}<hr />
    {:else if b.t === 'table'}
      <div class="scroll">
        <table>
          <tbody>
            {#each b.rows as r, k (k)}
              <tr>{#each r as c, m (m)}{#if c.head}<th>{@render inl(c.c)}</th>{:else}<td>{@render inl(c.c)}</td>{/if}{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/each}
{/snippet}

<div class="jira">{@render blk(doc)}</div>

<style>
  .jira {
    overflow-wrap: anywhere;
  }
  .jira :global(p),
  .jira :global(ul),
  .jira :global(ol),
  .jira :global(blockquote),
  .jira :global(pre),
  .jira :global(.panel),
  .jira :global(.scroll) {
    margin: 0 0 8px;
  }
  .jira > :global(:last-child) {
    margin-bottom: 0;
  }
  .jira :global(ul),
  .jira :global(ol) {
    padding-left: 22px;
  }
  .jira :global(.jh) {
    font-weight: 600;
    margin-top: 12px;
  }
  .jira > :global(.jh:first-child) {
    margin-top: 0;
  }
  .jira :global(.jh1),
  .jira :global(.jh2) {
    font-size: 1.15em;
  }
  .jira :global(blockquote) {
    border-left: 3px solid var(--border, currentColor);
    padding-left: 10px;
    color: var(--text-muted);
  }
  .jira :global(pre) {
    overflow-x: auto;
    padding: 8px 10px;
    border-radius: 6px;
    background: var(--surface-2, rgba(128, 128, 128, 0.12));
  }
  .jira :global(code) {
    font-family: var(--font-data);
    font-size: 0.92em;
  }
  .jira :global(.panel) {
    border: 1px solid var(--border, currentColor);
    border-radius: 6px;
    padding: 8px 10px;
  }
  .jira :global(.scroll) {
    overflow-x: auto;
  }
  .jira :global(table) {
    border-collapse: collapse;
  }
  .jira :global(th),
  .jira :global(td) {
    border: 1px solid var(--border, currentColor);
    padding: 4px 8px;
    text-align: left;
    vertical-align: top;
  }
  .jira :global(hr) {
    border: 0;
    border-top: 1px solid var(--border, currentColor);
  }
</style>
