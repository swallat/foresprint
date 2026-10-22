<script lang="ts">
  import { app } from '../lib/app.svelte';
  import { t } from '../lib/i18n.svelte';
  import Icon from '../lib/Icon.svelte';
  import type { IconName } from '../lib/icons';
  import { link } from '../lib/router.svelte';
  import type { StorageState } from '../lib/types';

  // The storage chip of the top bar (flows.md section 5). Colour is never the only signal: icon
  // and word are always shown.
  interface Look {
    tone: '' | 'ok' | 'warn' | 'bad';
    icon: IconName;
    text: string;
    to: string;
  }

  function look(state: StorageState, n: number): Look {
    switch (state) {
      case 'dirty':
        return { tone: 'warn', icon: 'cloud_upload', text: t('Unsaved changes'), to: '/data' };
      case 'incoming':
        return { tone: 'warn', icon: 'cloud_download', text: t('{n} new changes', { n }), to: '/data' };
      case 'conflict':
        return { tone: 'bad', icon: 'call_split', text: t('Conflict'), to: '/data/conflicts' };
      case 'decided':
        return { tone: 'warn', icon: 'task_alt', text: t('All decided, Save finishes'), to: '/data/conflicts' };
      case 'pending':
        return { tone: 'warn', icon: 'cloud_upload', text: t('Saved, not shared yet'), to: '/data' };
      case 'local':
        return { tone: '', icon: 'cloud_off', text: t('Saved on this computer only'), to: '/settings/storage' };
      case 'problem':
        return { tone: 'bad', icon: 'error', text: t('Storage problem'), to: '/settings/storage' };
      case 'offline':
        return { tone: '', icon: 'cloud_off', text: t('Offline, saving locally'), to: '/data' };
      case 'mr':
        return { tone: 'warn', icon: 'merge', text: t('Waiting for merge request'), to: '/data' };
      case 'readonly':
        return { tone: '', icon: 'lock', text: t('Read only'), to: '/data' };
      case 'locked':
        return { tone: 'warn', icon: 'lock', text: t('Locked'), to: '/data' };
      default:
        return { tone: 'ok', icon: 'cloud_done', text: t('Saved'), to: '/data' };
    }
  }

  const l = $derived(look(app.status.storage, app.status.incoming));
</script>

<a class="chip-status {l.tone}" href={link(l.to)} title={t('Storage status')}>
  <Icon name={l.icon} />
  <span class="hide-narrow">{app.status.detail || l.text}</span>
</a>
