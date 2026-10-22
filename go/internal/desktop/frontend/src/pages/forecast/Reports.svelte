<script lang="ts">
  import { api } from '../../lib/api';
  import { app, refreshStatus, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { ImportPreview } from '../../lib/types.forecast';
  import Banner from '../../lib/ui/Banner.svelte';

  let report = $state('');
  let problem = $state('');
  let preview = $state<(ImportPreview & { team: string }) | undefined>();
  let busy = $state(false);

  $effect(() => {
    const team = app.team;
    void app.rev; // saved or imported data: read the report again
    let stale = false;
    report = '';
    problem = '';
    preview = undefined;
    if (!team) return;
    api
      .ForecastReport(team)
      .then((r) => {
        if (!stale) report = r;
      })
      .catch((e) => {
        if (!stale) problem = String(e);
      });
    return () => {
      stale = true;
    };
  });

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(report);
      toast(t('Report copied to the clipboard.'), 'ok');
    } catch {
      toast(t('The clipboard is not available. Save the report as a file instead.'), 'bad');
    }
  }

  async function save(kind: 'markdown' | 'excel'): Promise<void> {
    try {
      const r = await api.ForecastSave(app.team, kind);
      if (!r.cancelled) toast(t('Saved as {path}.', { path: r.path }), 'ok');
    } catch (e) {
      toast(String(e), 'bad');
    }
  }

  async function pick(): Promise<void> {
    busy = true;
    const team = app.team;
    try {
      const p = await api.ExcelImportPreview(team);
      if (team !== app.team) return;
      preview = p.cancelled ? undefined : { ...p, team };
    } catch (e) {
      preview = undefined;
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }

  async function apply(): Promise<void> {
    if (!preview) return;
    busy = true;
    try {
      const files = await api.ExcelImportApply(preview.team, preview.path, preview.hash);
      toast(t('{n} files written. Check the result and save.', { n: files.length }), 'ok');
      preview = undefined;
      app.rev++;
      await refreshStatus();
    } catch (e) {
      toast(String(e), 'bad');
    } finally {
      busy = false;
    }
  }
</script>

<div class="stack-lg">
  <section class="card stack" aria-labelledby="rp-export">
    <h2 id="rp-export">{t('Export')}</h2>
    {#if problem}
      <Banner tone="bad">{problem}</Banner>
    {:else}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex: a scrollable region must be reachable by keyboard -->
      <pre class="report" tabindex="0" aria-label={t('Markdown report')}>{report}</pre>
    {/if}
    <div class="row">
      <button class="btn primary" type="button" disabled={!report} onclick={copy}><Icon name="content_copy" size={18} />{t('Copy')}</button>
      <button class="btn" type="button" onclick={() => save('markdown')}><Icon name="download" size={18} />{t('Report as file')}</button>
      <button class="btn" type="button" onclick={() => save('excel')}><Icon name="download" size={18} />{t('Excel workbook')}</button>
    </div>
  </section>

  <section class="card stack" aria-labelledby="rp-import">
    <h2 id="rp-import">{t('Import Excel')}</h2>
    <p class="small muted">{t('Reads a workbook from the Excel export. You see every change first; nothing is written before you confirm.')}</p>
    <div class="row">
      <button class="btn" type="button" disabled={busy} onclick={pick}><Icon name="upload_file" size={18} />{t('Choose workbook')}</button>
    </div>
    {#if preview}
      {#if preview.noTeam}
        <Banner tone="warn">{t('The workbook names no team (older export); it is not checked whether it belongs to this team.')}</Banner>
      {/if}
      {#if preview.changes.length === 0}
        <Banner tone="info">{t('No changes compared to the existing files.')}</Banner>
      {:else}
        <div class="tw">
          <table class="t">
            <thead><tr><th>{t('File')}</th><th>{t('Value')}</th><th>{t('Before')}</th><th>{t('New')}</th></tr></thead>
            <tbody>
              {#each preview.changes as c, i (i)}
                <tr><td class="data">{c.file}</td><td class="data">{c.path}</td><td class="data">{c.old}</td><td class="data"><strong>{c.new}</strong></td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if preview.more > 0}<p class="small muted">{t('… and {n} more changes', { n: preview.more })}</p>{/if}
        {#each preview.untouched as f (f)}<p class="small muted">{t('Not in the workbook, stays unchanged: {file}', { file: f })}</p>{/each}
        <div class="row">
          <button class="btn primary" type="button" disabled={busy} onclick={apply}>{t('Write changes')}</button>
          <button class="btn" type="button" disabled={busy} onclick={() => (preview = undefined)}>{t('Discard')}</button>
        </div>
      {/if}
    {/if}
  </section>
</div>

<style>
  .stack-lg {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
  .report {
    margin: 0;
    padding: 12px;
    max-height: 320px;
    overflow: auto;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-ctl);
    font: 12px/16px var(--font-data);
    white-space: pre;
  }
  p {
    margin: 0;
  }
</style>
