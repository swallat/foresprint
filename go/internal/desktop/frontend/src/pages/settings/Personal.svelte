<script lang="ts">
  import { app, setCalcMode, setDensity, setLanguage, setTheme, toast } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { IconName } from '../../lib/icons';
  import { link } from '../../lib/router.svelte';
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

  interface Option {
    code: string;
    label: string;
    icon?: IconName;
  }

  const themes: Option[] = $derived([
    { code: 'system', label: t('System'), icon: 'computer' },
    { code: 'light', label: t('Light'), icon: 'light_mode' },
    { code: 'dark', label: t('Dark'), icon: 'dark_mode' },
  ]);
  const densities: Option[] = $derived([
    { code: 'compact', label: t('Compact') },
    { code: 'normal', label: t('Normal') },
    { code: 'roomy', label: t('Roomy') },
  ]);
  const calcModes: Option[] = $derived([
    { code: 'off', label: t('Hide'), icon: 'visibility_off' },
    { code: 'icon', label: t('As icon'), icon: 'calculate' },
    { code: 'inline', label: t('Always open'), icon: 'unfold_more' },
  ]);
</script>

<PageHead title={t('Personal settings')} lead={t('Valid for you on this machine, not for the team.')} />

{#snippet choice(name: string, label: string, options: Option[], current: string, set: (code: string) => Promise<void>)}
  <div role="group" aria-label={label}>
    <div class="small muted label">{label}</div>
    <div class="row">
      {#each options as o (o.code)}
        <button
          type="button"
          class="chip filter"
          class:on={current === o.code}
          aria-pressed={current === o.code}
          data-setting={name}
          onclick={() => change(() => set(o.code))}
        >
          {#if o.icon}<Icon name={o.icon} size={16} />{/if}{o.label}
        </button>
      {/each}
    </div>
  </div>
{/snippet}

{#if app.prefs}
  <div class="grid cols-2">
    <div class="card">
      <h2>{t('Appearance')}</h2>
      <div class="stack gap">
        {@render choice('theme', t('Theme'), themes, app.prefs.theme, setTheme)}
        {@render choice('density', t('Density of tables'), densities, app.prefs.density, setDensity)}
        <div>
          {@render choice('calc', t('Calculations'), calcModes, app.prefs.calcMode, setCalcMode)}
          <p class="small muted">
            {t('How calculations show next to numbers. Full explanations are always under')}
            <a href={link('/help/calculations')}>{t('Help > Calculations')}</a>.
          </p>
        </div>
      </div>
    </div>
    <div class="card">
      <h2>{t('Language')}</h2>
      <div class="field" style="max-width:240px">
        <label for="p-lang">{t('Language of the interface')}</label>
        <select id="p-lang" class="input" value={app.prefs.language} onchange={(e) => change(() => setLanguage(e.currentTarget.value))}>
          {#each app.prefs.languages as l (l.code)}
            <option value={l.code}>{l.label}</option>
          {/each}
        </select>
      </div>
      <p class="small muted">{t('More languages are possible: a translation file is enough, the interface itself stays the same.')}</p>
    </div>
  </div>
{/if}

<style>
  .gap {
    gap: 16px;
  }
  .label {
    margin-bottom: 6px;
  }
  p {
    margin: 8px 0 0;
  }
</style>
