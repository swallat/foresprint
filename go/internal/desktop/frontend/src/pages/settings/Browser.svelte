<script lang="ts">
  import { browser, copyBrowserLink, inBrowserPage, loadBrowser, openInBrowser, stopBrowser } from '../../lib/browserAccess.svelte';
  import { t } from '../../lib/i18n.svelte';
  import { live } from '../../lib/liveData.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { PageProps } from '../../lib/routes';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  $effect(() => {
    void loadBrowser();
  });
</script>

<PageHead title={t('Browser')} lead={t('Show Foresprint as a page of your browser, for example next to Jira while sharing your screen.')} />

<div class="stack gap">
  {#if inBrowserPage}
    <Banner tone="info">{t('This page is already shown in the browser. Switch the access on or off in the window of the program.')}</Banner>
  {:else if !browser.available}
    <Banner tone="info">{t('This build has no browser access.')}</Banner>
  {:else}
    <div class="card">
      <h2>{browser.running ? t('The browser access is on') : t('The browser access is off')}</h2>
      {#if browser.running}
        <p class="data small" data-browser-url>{browser.url}</p>
      {/if}
      <div class="row">
        <button class="btn primary" type="button" onclick={openInBrowser}><Icon name="open_in_new" />{t('Open in browser')}</button>
        <button class="btn" type="button" onclick={copyBrowserLink}><Icon name="content_copy" />{t('Copy browser link')}</button>
        <button class="btn ghost" type="button" disabled={!browser.running} onclick={stopBrowser}><Icon name="stop_circle" />{t('Switch off')}</button>
      </div>
      <p class="small muted">{t('The link only works on this computer and contains a secret key. It is new on every start and void once you switch the access off or close the program. When you share your screen, share the tab, not the link.')}</p>
      <p class="small muted">{t('Changes show up in the other view within a second or two; the page is shown anew unless you are typing in a field. Updates of the program are made in the window.')}</p>
      <p class="small muted" data-live>
        {#if inBrowserPage}
          {live.streamAt ? t('Connection to the program: alive, last message {time}.', { time: new Date(live.streamAt).toLocaleTimeString() }) : t('Connection to the program: no message yet.')}
          <br />
        {/if}
        {#if live.at}
          {t('Last change of the other view: {time}, {what}.', {
            time: new Date(live.at).toLocaleTimeString(),
            what: live.what === 'applied' ? t('page updated') : live.what === 'typing' ? t('waiting, you are typing') : t('taken as your own work'),
          })}
        {:else}
          {t('This view has not seen a change of the other view yet.')}
        {/if}
      </p>
    </div>
  {/if}
</div>
