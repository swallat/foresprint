<script lang="ts">
  import { api } from '../../lib/api';
  import { app } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import type { RuleCheck } from '../../lib/types.projects';

  // Stand-in for the rule editor of the team package (lib/rules/RuleEditor): a text field for the
  // expression with a live check. When RuleEditor exists, this file is replaced by it.
  interface Props {
    value: string;
    /** The project the rule belongs to; its own rule is not a conflict. */
    project: string;
    onchange: (value: string) => void;
  }
  let { value, project, onchange }: Props = $props();

  let check = $state<RuleCheck | undefined>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let seq = 0; // an older answer must not replace a newer one

  $effect(() => {
    const text = value;
    clearTimeout(timer);
    if (!text.trim()) {
      check = undefined;
      return;
    }
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const answer = await api.CheckRule(app.team, project, text);
        if (mine === seq) check = answer;
      } catch {
        if (mine === seq) check = undefined;
      }
    }, 300);
    return () => clearTimeout(timer);
  });
</script>

<div class="field">
  <label for="rule-text">{t('Rule from the tracker (optional)')}</label>
  <textarea
    id="rule-text"
    class="input data rule-ed"
    rows="2"
    spellcheck="false"
    placeholder={'epic = "SSV-12" OR label = "self-service"'}
    {value}
    oninput={(e) => onchange(e.currentTarget.value)}
  ></textarea>
  <span class="small muted">{t('Without a rule you assign tickets by hand.')}</span>
  {#if check}
    {#if check.error}
      <span class="err" role="alert"><Icon name="error" size={16} />{check.error}</span>
    {:else}
      <span class="small" role="status">
        {t('{n} tickets match.', { n: check.matches })}
        {#if check.keys.length}<span class="data">{check.keys.join(', ')}</span>{/if}
      </span>
      {#if check.conflicts.length}
        <span class="small warn-txt"><Icon name="warning" size={14} />{t('Also matches tickets of: {names}', { names: check.conflicts.join(', ') })}</span>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .err {
    color: var(--bad);
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .warn-txt {
    color: var(--warn);
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
</style>
