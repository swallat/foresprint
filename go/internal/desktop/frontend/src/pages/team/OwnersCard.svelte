<script lang="ts">
  // The product owners (POs) of the team: name, whether the PO works in the team with a share,
  // and removal with a handover of their products. POs are not part of the capacity unless
  // they are marked as working in the team (decision 11).
  import { api } from '../../lib/api';
  import { app, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { fmtNum, parseNum } from '../../lib/team/format';
  import type { Owner, Product, ProductsView, Step } from '../../lib/types.team';
  import Banner from '../../lib/ui/Banner.svelte';
  import SidePanel from '../../lib/ui/SidePanel.svelte';

  interface Props {
    /** Called after a PO step changed the people (a PO joined or left the team). */
    onchange: () => void | Promise<void>;
  }
  let { onchange }: Props = $props();

  let view = $state<ProductsView>();
  let failed = $state('');
  let newName = $state('');
  let removing = $state<Owner | null>(null);
  let handover = $state<Record<string, string>>({});

  const owners = $derived(view?.owners ?? []);
  const productsOf = (o: Owner): Product[] => (view?.products ?? []).filter((p) => p.po === o.id);
  const others = $derived(owners.filter((o) => o.id !== removing?.id));

  async function load() {
    try {
      view = await api.Products(app.team);
      failed = '';
    } catch (e) {
      failed = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    void app.team;
    load();
  });

  async function undo(token: number) {
    try {
      await api.Undo(app.team, token);
      toast(t('Change undone.'), 'ok');
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
    }
    await load();
    await onchange();
  }

  /** Runs one step of the PO management; shows the answer or the error. */
  async function run(step: () => Promise<Step>, message: string) {
    try {
      const result = await step();
      view = result.view;
      if (message) toast(message, 'ok', { label: t('Undo'), run: () => void undo(result.undo) });
      await onchange();
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'bad');
      await load();
      return false;
    }
  }

  async function add() {
    const name = newName.trim();
    if (!name) return;
    if (await run(() => api.AddOwner(app.team, name), t('{name} added as PO.', { name }))) newName = '';
  }

  function rename(o: Owner, value: string) {
    const name = value.trim();
    if (!name || name === o.name) return load();
    return run(() => api.RenameOwner(app.team, o.id, name), '');
  }

  function setInTeam(o: Owner, inTeam: boolean, fte = o.fte || 0.2) {
    return run(
      () => api.SetOwnerInTeam(app.team, o.id, inTeam, fte),
      inTeam ? t('{name} now works in the team.', { name: o.name }) : t('{name} no longer works in the team.', { name: o.name }),
    );
  }

  function setShare(o: Owner, text: string) {
    const fte = parseNum(text);
    if (!(fte > 0 && fte <= 1)) {
      toast(t('Enter a share between 0.1 and 1.0.'), 'bad');
      return load();
    }
    if (fte === o.fte) return;
    return setInTeam(o, true, fte);
  }

  function askRemove(o: Owner) {
    const list = productsOf(o);
    if (!list.length) {
      void confirmRemove(o, {});
      return;
    }
    const first = owners.find((x) => x.id !== o.id)?.id ?? '';
    handover = Object.fromEntries(list.map((p) => [p.id, first]));
    removing = o;
  }

  async function confirmRemove(o: Owner, who: Record<string, string>) {
    removing = null;
    await run(() => api.RemoveOwner(app.team, o.id, who), t('{name} removed as PO.', { name: o.name }));
  }
</script>

<section class="card" aria-labelledby="po-h">
  <h2 id="po-h">{t('Product owners')}</h2>
  <p class="small muted">
    {t('Each product has a PO. POs are not part of the capacity unless you mark them as working in the team with a share.')}
  </p>
  {#if failed}
    <Banner tone="bad">{failed}</Banner>
  {:else if view}
    {#if owners.length}
      <div class="tw">
        <table class="t">
          <thead>
            <tr>
              <th>{t('Name')}</th>
              <th class="num">{t('Products')}</th>
              <th>{t('Works in the team')}</th>
              <th class="num">{t('FTE')}</th>
              <th><span class="sr-only">{t('Actions')}</span></th>
            </tr>
          </thead>
          <tbody>
            {#each owners as o (o.id)}
              <tr>
                <td><input class="input name" value={o.name} aria-label={t('Name of PO {name}', { name: o.name })} onchange={(e) => rename(o, e.currentTarget.value)} /></td>
                <td class="num data">{o.products}</td>
                <td>
                  <input type="checkbox" checked={o.inTeam} aria-label={t('{name} works in the team', { name: o.name })} onchange={(e) => setInTeam(o, e.currentTarget.checked)} />
                </td>
                <td class="num">
                  {#if o.inTeam}
                    <input class="input data share" inputmode="decimal" value={fmtNum(o.fte)} aria-label={t('Share of {name}', { name: o.name })} onchange={(e) => setShare(o, e.currentTarget.value)} />
                  {:else}
                    <span class="muted">–</span>
                  {/if}
                </td>
                <td>
                  <button
                    class="btn icon ghost"
                    type="button"
                    aria-label={t('Remove PO {name}', { name: o.name })}
                    title={t('Remove')}
                    disabled={owners.length < 2}
                    onclick={() => askRemove(o)}
                  >
                    <Icon name="delete" />
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="muted">{t('No PO yet. Add the first one.')}</p>
    {/if}
    <form
      class="row add"
      onsubmit={(e) => {
        e.preventDefault();
        void add();
      }}
    >
      <label class="sr-only" for="po-new">{t('Name of the new PO')}</label>
      <input id="po-new" class="input" placeholder={t('Name of the new PO')} bind:value={newName} />
      <button class="btn" type="submit" disabled={!newName.trim()}><Icon name="person_add" />{t('Add PO')}</button>
    </form>
  {:else}
    <p class="muted">{t('Loading…')}</p>
  {/if}
</section>

{#if removing}
  {@const gone = removing}
  <SidePanel title={t('Remove PO {name}', { name: gone.name })} onclose={() => (removing = null)}>
    <p class="small muted">{t('Say who takes over each product of {name}. The PO then no longer exists; minutes and history keep the name.', { name: gone.name })}</p>
    {#each productsOf(gone) as p (p.id)}
      <div class="field">
        <label for="ho-{p.id}">{p.name}</label>
        <select id="ho-{p.id}" class="input" bind:value={handover[p.id]}>
          {#each others as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
        </select>
      </div>
    {/each}
    <div class="row">
      <button class="btn primary" type="button" onclick={() => confirmRemove(gone, handover)}>{t('Remove PO')}</button>
      <button class="btn" type="button" onclick={() => (removing = null)}>{t('Cancel')}</button>
    </div>
  </SidePanel>
{/if}

<style>
  .card {
    margin-top: 16px;
  }
  .name {
    width: 200px;
  }
  .share {
    width: 64px;
    text-align: right;
  }
  .add {
    margin-top: 12px;
    gap: 8px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
