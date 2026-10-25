<script lang="ts">
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import PageHead from './PageHead.svelte';

  interface Props {
    /** Source text of the page title. */
    title: string;
    /** Work package that builds this page (docs/desktop.md). */
    pkg: string;
    /** Where the page is specified, e.g. "flows.md F4". */
    spec: string;
  }
  let { title, pkg, spec }: Props = $props();
</script>

<PageHead title={t(title)} />
<div class="card placeholder">
  <Icon name="school" size={24} />
  <div>
    <p><strong>{t('This page is not built yet.')}</strong></p>
    <p class="muted small">{t('Work package {pkg}. Specification: {spec}.', { pkg, spec })}</p>
  </div>
</div>

<style>
  .placeholder {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    max-width: 720px;
  }
  p {
    margin: 0;
  }
</style>
