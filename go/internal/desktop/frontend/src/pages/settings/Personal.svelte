<script lang="ts">
  import { app, setCalcMode, setLanguage, setTheme, toast, type CalcMode } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import type { PageProps } from '../../lib/routes';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  async function change(apply: () => Promise<void>): Promise<void> {
    try {
      await apply();
    } catch (e) {
      toast(String(e), 'bad');
    }
  }
</script>

<PageHead title={t('Personal settings')} lead={t('Valid for you on this machine, not for the team.')} />

{#if app.prefs}
  <div class="card stack form">
    <div class="field">
      <label for="p-lang">{t('Language')}</label>
      <select id="p-lang" class="input" value={app.prefs.language} onchange={(e) => change(() => setLanguage(e.currentTarget.value))}>
        {#each app.prefs.languages as l (l.code)}
          <option value={l.code}>{l.label}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="p-theme">{t('Theme')}</label>
      <select id="p-theme" class="input" value={app.prefs.theme} onchange={(e) => change(() => setTheme(e.currentTarget.value))}>
        {#each app.prefs.themes as th (th.code)}
          <option value={th.code}>{th.label}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="p-calc">{t('Calculations next to numbers')}</label>
      <select id="p-calc" class="input" aria-describedby="p-calc-hint" value={app.calcMode} onchange={(e) => setCalcMode(e.currentTarget.value as CalcMode)}>
        <option value="off">{t('Hidden')}</option>
        <option value="icon">{t('Calculator icon')}</option>
        <option value="inline">{t('Always shown')}</option>
      </select>
      <p id="p-calc-hint" class="muted small">{t('Help > Calculations explains every formula in any case.')}</p>
    </div>
    <p class="muted small">{t('Density follows with the settings package.')}</p>
  </div>
{/if}

<style>
  .form {
    max-width: 720px;
  }
  .form p {
    margin: 0;
  }
</style>
