<script lang="ts">
  import { link } from '../../lib/router.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import FieldPick, { isKnownField } from '../../lib/settings/FieldPick.svelte';
  import { parseNumber } from '../../lib/settings/diff';
  import { app } from '../../lib/app.svelte';
  import RuleEditor from '../../lib/rules/RuleEditor.svelte';
  import type { TrackerFields, TrackerSettings } from '../../lib/types.settings';

  interface Props {
    draft: TrackerSettings;
    /** Names of the fields of the tracker, for suggestions. */
    fieldNames: string[];
    /** The fields as saved, to tell whether the hits below belong to the field in the draft. */
    applied: TrackerFields;
    /** Tickets of the last import that have a value, per mapped value. */
    hits: Record<string, number>;
    /** Tickets of the last import. */
    total: number;
    /** The team uses production access: the production share is mapped as well. */
    production: boolean;
    tracker: string;
    /** The refined label as saved; its hits are counted from the stored tickets. */
    appliedLabel: string;
  }
  let { draft = $bindable(), fieldNames, applied, hits, total, production, tracker, appliedLabel }: Props = $props();

  /** The mapped field exists in the tracker; how many tickets of the last import have a value. */
  const known = (name: string) => isKnownField(name, fieldNames);

  function removeRuleField(i: number): void {
    draft.ruleFields.splice(i, 1);
  }
</script>

{#snippet stand(key: string, value: string, saved: string)}
  {#if !value}
    <span class="muted small">–</span>
  {:else if !known(value)}
    <span class="chip warn"><Icon name="warning" size={14} />{t('Not found in {tracker}', { tracker })}</span>
  {:else if key && value === saved && key in hits && total > 0}
    <span class="data small">{hits[key]} / {total}</span>
    {#if hits[key] === 0}<span class="chip warn"><Icon name="warning" size={14} />{t('No ticket has a value')}</span>{/if}
  {:else if key && value !== saved}
    <span class="small muted">{t('After applying and fetching')}</span>
  {:else}
    <span class="muted small">–</span>
  {/if}
{/snippet}

<div class="card full">
  <h2>{t('Field mapping and rules')}</h2>
  <p class="small muted lead">
    {t('For every value in Foresprint: read it from a field in {tracker} or determine it by a rule in Foresprint. The query above only limits which tickets are read. Rules use one language for all trackers. A value set by hand in Foresprint always wins.', { tracker })}
  </p>

  <div class="tw">
    <table class="t map">
      <thead>
        <tr><th>{t('Value in Foresprint')}</th><th>{t('Source')}</th><th>{t('Field or rule')}</th><th>{t('Hits')}</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>{t('Estimate')}</td>
          <td><span class="small muted">{t('Field')}</span></td>
          <td><FieldPick label={t('Field for the estimate')} names={fieldNames} bind:value={draft.fields.estimate} /></td>
          <td>{@render stand('estimate', draft.fields.estimate, applied.estimate)}</td>
        </tr>
        <tr>
          <td>{t('Remaining effort')}</td>
          <td><span class="small muted">{t('Field')}</span></td>
          <td><FieldPick label={t('Field for the remaining effort')} names={fieldNames} bind:value={draft.fields.remaining} /></td>
          <td>{@render stand('remaining', draft.fields.remaining, applied.remaining)}</td>
        </tr>
        <tr>
          <td>{t('Epic')}</td>
          <td><span class="small muted">{t('Field')}</span></td>
          <td><FieldPick label={t('Field for the epic')} names={fieldNames} bind:value={draft.fields.epic} /></td>
          <td>{@render stand('epic', draft.fields.epic, applied.epic)}</td>
        </tr>
        <tr>
          <td>{t('Status')}</td>
          <td><span class="small muted">{t('Field')}</span></td>
          <td><FieldPick label={t('Field for the status')} names={fieldNames} bind:value={draft.fields.status} /></td>
          <td>{@render stand('status', draft.fields.status, applied.status)}</td>
        </tr>
        <tr>
          <td>{t('Acceptance criteria')}</td>
          <td><span class="small muted">{t('Field')}</span></td>
          <td><FieldPick label={t('Field for the acceptance criteria')} names={fieldNames} bind:value={draft.fields.acceptance} /></td>
          <td>{@render stand('', draft.fields.acceptance, applied.acceptance)}</td>
        </tr>
        <tr>
          <td>{t('Product')}</td>
          <td>
            <select class="input" aria-label={t('Source of the product')} bind:value={draft.productBy}>
              <option value="rule">{t('Rules per product')}</option>
              <option value="field">{t('Field in {tracker}', { tracker })}</option>
            </select>
          </td>
          <td>
            {#if draft.productBy === 'rule'}
              <a class="btn" href={link('/team/products')}><Icon name="edit" />{t('Rules on the Products page')}</a>
            {:else}
              <FieldPick label={t('Field for the product')} names={fieldNames} bind:value={draft.fields.product} />
            {/if}
          </td>
          <td>{@render stand('product', draft.fields.product, applied.product)}</td>
        </tr>
        <tr>
          <td>{t('Project')}</td>
          <td>
            <select class="input" aria-label={t('Source of the project')} bind:value={draft.projectBy}>
              <option value="rule">{t('Rules per project')}</option>
              <option value="field">{t('Field in {tracker}', { tracker })}</option>
            </select>
          </td>
          <td>
            {#if draft.projectBy === 'rule'}
              <a class="btn" href={link('/projects')}><Icon name="edit" />{t('Rules on the Projects page')}</a>
            {:else}
              <FieldPick label={t('Field for the project')} names={fieldNames} bind:value={draft.fields.project} />
            {/if}
          </td>
          <td>{@render stand('project', draft.fields.project, applied.project)}</td>
        </tr>
        <tr>
          <td>{t('Refined')}</td>
          <td>
            <select class="input" aria-label={t('Source of “refined”')} bind:value={draft.refinedBy}>
              <option value="rule">{t('Label and rule')}</option>
              <option value="field">{t('Field in {tracker}', { tracker })}</option>
            </select>
          </td>
          <td>
            <div class="stackcell">
            {#if draft.refinedBy === 'rule'}
              <label class="inline">
                <span class="small muted">{t('Label that marks refined tickets')}</span>
                <input class="input data" aria-label={t('Label that marks refined tickets')} bind:value={draft.refinedLabel} />
              </label>
              <label class="inline">
                <RuleEditor team={app.team} owner={{ kind: 'setting', id: 'refined' }} name={t('“also refined if”')} bind:value={draft.refinedRule} allowEmpty />
              </label>
            {:else}
              <FieldPick label={t('Field for “refined”')} names={fieldNames} bind:value={draft.fields.refined} />
            {/if}
            </div>
          </td>
          <td>
            {#if draft.refinedBy === 'rule' && draft.refinedLabel && draft.refinedLabel === appliedLabel && total > 0}
              <span class="data small">{hits.refinedLabel ?? 0} / {total}</span>
              {#if !hits.refinedLabel}
                <span class="chip warn"><Icon name="warning" size={14} />{t('No ticket has this label')}</span>
              {:else if hits.refinedLabelNoEstimate}
                <span class="chip warn"><Icon name="warning" size={14} />{t('{n} of them have no estimate and count as not refined', { n: hits.refinedLabelNoEstimate })}</span>
              {/if}
            {:else if draft.refinedBy === 'rule' && draft.refinedLabel}
              <span class="small muted">{t('After applying and fetching')}</span>
            {:else}
              {@render stand('refined', draft.fields.refined, applied.refined)}
            {/if}
          </td>
        </tr>
        {#if production}
          <tr>
            <td>{t('Production share')}</td>
            <td>
              <select class="input" aria-label={t('Source of the production share')} bind:value={draft.productionBy}>
                <option value="rule">{t('Rules')}</option>
                <option value="field+rule">{t('Field in {tracker}, otherwise rules', { tracker })}</option>
                <option value="manual">{t('By hand only')}</option>
              </select>
            </td>
            <td>
              {#if draft.productionBy === 'field+rule'}
                <FieldPick label={t('Field for the production share')} names={fieldNames} bind:value={draft.fields.production} />
              {:else if draft.productionBy === 'manual'}
                <span class="small muted">{t('In Pre-plan, Plan or the ticket. Rules and label are removed when you apply this.')}</span>
              {:else}
                <span class="small muted">{t('List below')}</span>
              {/if}
            </td>
            <td>{@render stand('production', draft.fields.production, applied.production)}</td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>

  {#if production && draft.productionBy !== 'manual'}
    <div class="sect">
      <h3>{t('Rules for the production share')}</h3>
      <p class="small muted">
        {t('The first matching rule counts.')}
        {#if draft.productionBy === 'field+rule'}{t('Only for tickets without a value in the field.')}{/if}
        {t('A value set by hand always wins.')}
      </p>
      <label class="inline narrow">
        <span class="small muted">{t('Label that means 100 percent')}</span>
        <input class="input data" aria-label={t('Label that means 100 percent')} placeholder={t('not set')} bind:value={draft.productionLabel} />
      </label>
      {#each draft.prodRules as r, i (i)}
        <div class="prodrule">
          <RuleEditor team={app.team} owner={{ kind: 'setting', id: `production-${i}` }} name={t('production rule {n}', { n: i + 1 })} bind:value={r.rule} />
          <div class="row">
            <label class="inline">
              <span class="small muted">{t('Production %')}</span>
              <input
                class="input data num"
                style="width:80px"
                inputmode="numeric"
                aria-label={t('Production share of rule {n}', { n: i + 1 })}
                value={r.percent}
                onchange={(e) => (r.percent = Math.max(0, Math.min(100, parseNumber(e.currentTarget.value) ?? r.percent)))}
              />
            </label>
            <button class="btn ghost" type="button" onclick={() => draft.prodRules.splice(i, 1)}>
              <Icon name="delete" />{t('Remove rule {n}', { n: i + 1 })}
            </button>
          </div>
        </div>
      {:else}
        <p class="small muted">{t('No rule yet.')}</p>
      {/each}
      <div class="row add">
        <button class="btn" type="button" onclick={() => draft.prodRules.push({ rule: '', percent: 100 })}><Icon name="add" />{t('Add rule')}</button>
        <span class="small muted">{t('Example:')} <span class="data rule-txt">component = "Operations"</span> → 100 %</span>
      </div>
    </div>
  {/if}

  <div class="sect">
    <h3>{t('Fields for rules')}</h3>
    <p class="small muted">
      {t('Always there:')} {#each draft.fixedSources as s, i (s)}<span class="data">{s}</span>{i < draft.fixedSources.length - 1 ? ', ' : ''}{/each}.
      {t('Register further fields of {tracker} here; then every rule can use them.', { tracker })}
    </p>
    <div class="tw">
      <table class="t">
        <thead>
          <tr><th>{t('Name in rules')}</th><th>{t('Field in {tracker}', { tracker })}</th><th aria-label={t('Actions')}></th></tr>
        </thead>
        <tbody>
          {#each draft.ruleFields as f, i (i)}
            <tr>
              <td><input class="input data" style="width:160px" aria-label={t('Name in rules')} bind:value={f.name} /></td>
              <td><FieldPick label={t('Field in {tracker}', { tracker })} names={fieldNames} bind:value={f.display} /></td>
              <td>
                <button class="btn icon ghost" type="button" aria-label={t('Remove field')} onclick={() => removeRuleField(i)}><Icon name="delete" /></button>
              </td>
            </tr>
          {:else}
            <tr><td colspan="3" class="muted">{t('No extra fields.')}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="row add">
      <button class="btn" type="button" onclick={() => draft.ruleFields.push({ name: '', display: '' })}><Icon name="add" />{t('Add field')}</button>
    </div>
  </div>
</div>

<style>
  .full {
    grid-column: 1 / -1;
  }
  .lead {
    margin: 0 0 8px;
  }
  table.map td {
    white-space: normal;
    vertical-align: middle;
  }
  table.map td:last-child .input {
    width: 100%;
    min-width: 220px;
  }
  .stackcell {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 4px 0;
  }
  table.map td {
    height: auto;
  }
  .inline {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .narrow {
    max-width: 280px;
    margin-bottom: 8px;
  }
  .sect {
    margin-top: 16px;
  }
  h3 {
    margin: 0 0 4px;
    font: 600 14px/20px var(--font-ui);
  }
  .sect p {
    margin: 0 0 8px;
  }
  .add {
    margin-top: 8px;
  }
  .prodrule {
    border: 1px solid var(--border);
    border-radius: var(--r-ctl);
    padding: 12px;
    margin-bottom: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
