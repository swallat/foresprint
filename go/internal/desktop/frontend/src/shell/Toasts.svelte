<script lang="ts">
  import { app, dismissToast } from '../lib/app.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each app.toasts as toast (toast.id)}
    <div class="toast" class:bad={toast.tone === 'bad'}>
      <span>{toast.text}</span>
      {#if toast.action}
        <button type="button" onclick={() => { toast.action?.run(); dismissToast(toast.id); }}>{toast.action.label}</button>
      {/if}
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    left: 50%;
    transform: translateX(-50%);
    bottom: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 60;
  }
  .toasts :global(.toast) {
    position: static;
    transform: none;
  }
  .toast.bad {
    outline: 2px solid var(--bad);
  }
</style>
