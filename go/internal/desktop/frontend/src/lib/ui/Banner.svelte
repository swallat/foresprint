<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from '../Icon.svelte';
  import type { IconName } from '../icons';

  interface Props {
    tone?: 'info' | 'warn' | 'bad';
    children: Snippet;
    action?: Snippet;
  }
  let { tone = 'info', children, action }: Props = $props();
  const icon: Record<string, IconName> = { info: 'info', warn: 'warning', bad: 'error' };
</script>

<div class="banner {tone}" role={tone === 'bad' ? 'alert' : 'status'}>
  <Icon name={icon[tone] ?? 'info'} />
  <div class="grow">{@render children()}</div>
  {#if action}{@render action()}{/if}
</div>
