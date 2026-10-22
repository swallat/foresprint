<script lang="ts">
  // Editor of an assignment rule with a live preview. One component for products and projects
  // (flows.md decision 12): the same language, the same fields, the same preview. The text is
  // checked by the Go core (api.CheckRule), so what the editor accepts is what is saved.
  import { api } from '../api';
  import { openTicket } from '../app.svelte';
  import { t } from '../i18n.svelte';
  import Icon from '../Icon.svelte';
  import type { RuleOwner, RulePreview } from '../types.team';
  import { insertField } from './insert';

  interface Props {
    team: string;
    owner: RuleOwner;
    /** Name of the product or project, for the label. */
    name: string;
    /** The rule text; the parent keeps it. */
    value: string;
    /** True while the text is a rule (or empty and `allowEmpty`). The parent may disable Save. */
    valid?: boolean;
    /** A product may have no rule: an empty text is then fine. */
    allowEmpty?: boolean;
    /** The preview of the last check, for a parent that shows the counts elsewhere. */
    preview?: RulePreview | undefined;
  }
  let { team, owner, name, value = $bindable(), valid = $bindable(true), allowEmpty = false, preview = $bindable() }: Props = $props();

  const uid = $props.id();
  let area: HTMLTextAreaElement | undefined = $state();
  let fields = $state<string[]>([]);
  let failed = $state('');
  let run = 0;

  $effect(() => {
    const text = value;
    const key = `${team}|${owner.kind}|${owner.id}`;
    void key;
    const mine = ++run;
    if (allowEmpty && !text.trim()) {
      preview = undefined;
      failed = '';
      valid = true;
      return;
    }
    // Until the answer for this text is in, it does not count as a rule (Save must wait).
    valid = false;
    const timer = setTimeout(async () => {
      try {
        const result = await api.CheckRule(team, text, owner);
        if (mine !== run) return;
        preview = result;
        fields = result.fields;
        failed = '';
        valid = result.valid;
      } catch (e) {
        if (mine !== run) return;
        failed = e instanceof Error ? e.message : String(e);
        preview = undefined;
        valid = false;
      }
    }, 200);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    const forTeam = team;
    api
      .RuleFields(forTeam)
      .then((list) => {
        if (forTeam === team) fields = list;
      })
      .catch(() => {});
  });

  /** Short text for screen readers; the banner below has the details. */
  const status = $derived(
    failed ||
      (preview && !preview.valid
        ? `${t('Rule is not complete')}: ${preview.error ?? ''}`
        : preview
          ? t('{count} tickets match ({points} points).', { count: preview.matches, points: preview.points })
          : ''),
  );

  function insert(field: string) {
    if (!area) return;
    const at = area.selectionStart ?? value.length;
    const done = insertField(value, at, field);
    value = done.text;
    queueMicrotask(() => {
      area?.focus();
      area?.setSelectionRange(done.caret, done.caret);
    });
  }
</script>

<div class="stack rule-ed">
  <div class="field">
    <label for="re-{uid}">{t('Rule for {name}', { name })}</label>
    <textarea
      id="re-{uid}"
      class="input data rule-txt"
      rows="2"
      spellcheck="false"
      autocomplete="off"
      bind:value
      bind:this={area}
      aria-invalid={!valid}
      aria-describedby="rp-{uid}"
    ></textarea>
  </div>
  <div class="small muted">
    {t('Fields')}:
    {#each fields as f (f)}
      <button class="link data" type="button" onclick={() => insert(f)}>{f}</button>{' '}
    {/each}
    · {t('Operators')} <span class="data">= != ~ !~ IN NOT IN AND OR NOT ( )</span>
  </div>

  <span class="sr-only" aria-live="polite">{status}</span>
  <div id="rp-{uid}">
    {#if failed}
      <div class="banner bad"><Icon name="error" /><div class="grow">{failed}</div></div>
    {:else if preview && !preview.valid}
      <div class="banner warn">
        <Icon name="warning" />
        <div class="grow">
          <strong>{t('Rule is not complete')}:</strong>
          {preview.error}
          {#if preview.pos >= 0}<span class="muted small"> ({t('at position {pos}', { pos: preview.pos + 1 })})</span>{/if}
        </div>
      </div>
    {:else if preview}
      <div class="banner info">
        <Icon name="preview" />
        <div class="grow">
          {#if preview.matches === 1 && preview.moved === 0}
            {t('One ticket matches ({points} points).', { points: preview.points })}
          {:else if preview.moved > 0}
            {t('{count} tickets match ({points} points), {moved} of them are assigned differently today.', { count: preview.matches, points: preview.points, moved: preview.moved })}
          {:else}
            {t('{count} tickets match ({points} points).', { count: preview.matches, points: preview.points })}
          {/if}
          {#if preview.clash > 0}
            <span class="chip warn">{t('{count} also match another rule', { count: preview.clash })}</span>
          {/if}
          {#if preview.sample.length}
            <div class="small sample">
              {#each preview.sample as key (key)}
                <button class="link data" type="button" onclick={() => openTicket(key)}>{key}</button>{' '}
              {/each}
              {#if preview.matches > preview.sample.length}
                <span class="muted">{t('and {count} more', { count: preview.matches - preview.sample.length })}</span>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .rule-txt {
    font-variant-ligatures: none;
    font-feature-settings: 'calt' 0, 'liga' 0;
    resize: vertical;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .sample {
    margin-top: 4px;
  }
</style>
