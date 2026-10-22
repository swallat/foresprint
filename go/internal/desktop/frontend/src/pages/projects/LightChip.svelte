<script lang="ts">
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { Light } from '../../lib/types.projects';

  interface Props {
    light: Light;
    /** Own text instead of the default wording of the light. */
    label?: string;
  }
  let { light, label }: Props = $props();

  // The icon repeats what the colour says, so the light never relies on colour alone.
  const text = $derived(
    label ?? (light === 'ok' ? t('on track') : light === 'warn' ? t('tight') : light === 'bad' ? t('at risk') : t('no light')),
  );
</script>

<span class="chip {light === 'none' ? '' : light}">
  {#if light === 'ok'}<Icon name="check_circle" size={16} />{:else if light === 'warn'}<Icon name="error" size={16} />{:else if light === 'bad'}<Icon name="cancel" size={16} />{/if}
  {text}
</span>
