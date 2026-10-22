<script lang="ts">
  import { app, refreshStatus, toast } from '../../lib/app.svelte';
  import { api } from '../../lib/api';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PackageImportPreview } from '../../lib/types.settings';
  import Banner from '../../lib/ui/Banner.svelte';

  /** False while the choice "work packages" is not saved yet: the import writes to the saved team. */
  let { ready }: { ready: boolean } = $props();

  let busy = $state(false);
  let preview = $state<(PackageImportPreview & { team: string }) | undefined>();

  // A preview belongs to one team; another team must not apply it.
  $effect(() => {
    if (preview && preview.team !== app.team) preview = undefined;
  });

  async function pick(): Promise<void> {
    busy = true;
    const team = app.team;
    try {
      const p = await api.PackageImportPreview(team);
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
      const r = await api.PackageImportApply(preview.team, preview.path, preview.hash);
      toast(r.message, 'ok');
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

<section class="card stack" aria-labelledby="pi-h">
  <h2 id="pi-h">{t('Import work packages')}</h2>
  <p class="small muted">
    {t('Reads a CSV or Excel table with a header row (title, status, type, priority, assignee, product, project, estimate, labels, description and more). You see every change first; nothing is written before you confirm. A key that exists is updated, a new key is added at the end of the backlog.')}
  </p>
  {#if !ready}
    <Banner tone="info">{t('Apply the choice "Work packages in Foresprint" first; the import writes to the saved team.')}</Banner>
  {/if}
  <div class="row">
    <button class="btn" type="button" disabled={busy || !ready} onclick={pick}><Icon name="upload_file" size={18} />{t('Choose table')}</button>
  </div>
  {#if preview}
    {#if preview.unmapped.length > 0}
      <Banner tone="warn">{t('Columns without a matching field are ignored: {names}', { names: preview.unmapped.join(', ') })}</Banner>
    {/if}
    {#if preview.problems.length > 0}
      <Banner tone="warn">
        <strong>{t('Rows that are skipped:')}</strong>
        <ul class="plain">
          {#each preview.problems as p (p.row)}<li>{t('Row {row}: {msg}', { row: p.row, msg: p.msg })}</li>{/each}
        </ul>
      </Banner>
    {/if}
    {#if preview.changes.length === 0}
      <Banner tone="info">{t('No changes compared to the existing work packages.')}</Banner>
    {:else}
      <p class="small">{t('{new} new, {updated} updated', { new: preview.new, updated: preview.updated })}</p>
      <div class="tw">
        <table class="t">
          <thead><tr><th>{t('Key')}</th><th>{t('Title')}</th><th>{t('What happens')}</th></tr></thead>
          <tbody>
            {#each preview.changes as c, i (i)}
              <tr>
                <td class="data">{c.key}</td>
                <td>{c.title}</td>
                <td><span class="chip {c.update ? 'warn' : 'ok'}">{c.update ? t('Updated') : t('New')}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if preview.more > 0}<p class="small muted">{t('… and {n} more work packages', { n: preview.more })}</p>{/if}
      <div class="row">
        <button class="btn primary" type="button" disabled={busy} onclick={apply}>{t('Import work packages')}</button>
        <button class="btn" type="button" disabled={busy} onclick={() => (preview = undefined)}>{t('Discard')}</button>
      </div>
    {/if}
  {/if}
</section>

<style>
  p,
  ul {
    margin: 0;
  }
  .plain {
    padding-left: 18px;
  }
</style>
