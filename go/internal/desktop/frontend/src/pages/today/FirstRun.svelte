<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { api } from '../../lib/api';
  import DemoChoice from '../../lib/ui/DemoChoice.svelte';
  import { app, enterDemo, leaveDemo, loadTeams, selectTeam } from '../../lib/app.svelte';
  import { t } from '../../lib/i18n.svelte';
  import Icon from '../../lib/Icon.svelte';
  import { followWizard, tour, wizard } from '../../lib/tour/tour.svelte';
  import { current, go, link } from '../../lib/router.svelte';
  import type { PageProps } from '../../lib/routes';
  import { derivePattern, joinPath, needsToken, repoName, safeToStore, suggestedSprintId, suggestedStart } from '../../lib/setup';
  import { dayPlaceholder, formatDayInput, parseDayInput } from '../../lib/format';
  import type { Problem, Region, SetupKind, SetupState } from '../../lib/types.setup';
  import type { TicketSource } from '../../lib/types.today';
  import Banner from '../../lib/ui/Banner.svelte';
  import PageHead from '../../lib/ui/PageHead.svelte';

  let { params }: PageProps = $props();
  void params;

  // The first-start wizard (flows.md F1 and D1). Short steps; the person can go back at any
  // time. Nothing is written before the step that needs it, and a token is never kept here: it
  // goes to Git's credential helper at once. The draft (no secrets) is remembered, so that the
  // window can be closed in between.
  type Step = 'storage' | 'signin' | 'team' | 'tickets' | 'done';
  type StorageKind = 'keep' | SetupKind;
  type TeamChoice = 'existing' | 'demo' | 'new';

  interface Draft {
    step: Step;
    kind: StorageKind;
    address: string;
    parent: string;
    folder: string;
    name: string;
    email: string;
    team: TeamChoice;
    existing: string;
    teamName: string;
    country: string;
    region: string;
    sprintId: string;
    pattern: string;
    // As typed, in the form of the language (20.10.2026).
    start: string;
    source: TicketSource;
    trackerUrl: string;
    trackerQuery: string;
  }

  const monday = suggestedStart();
  const empty: Draft = {
    step: 'storage',
    kind: 'clone',
    address: '',
    parent: '',
    folder: '',
    name: '',
    email: '',
    team: 'new',
    existing: '',
    teamName: '',
    country: 'DE',
    region: '',
    sprintId: suggestedSprintId(monday),
    pattern: '',
    start: formatDayInput(monday),
    source: 'packages',
    trackerUrl: '',
    trackerQuery: '',
  };

  const KEY = 'foresprint.setup';
  function restore(): Draft {
    try {
      const raw = localStorage.getItem(KEY);
      // The data folder is not made yet after a restart, so the draft begins at the first step.
      if (raw) {
        const saved = JSON.parse(raw) as Partial<Draft>;
        // The date is kept as YYYY-MM-DD, so that a change of language cannot read it differently.
        return { ...empty, ...saved, start: saved.start ? formatDayInput(parseDayInput(saved.start)) || saved.start : empty.start, step: 'storage' };
      }
    } catch {
      /* no stored draft, or storage blocked: start fresh */
    }
    return { ...empty };
  }

  const d = $state<Draft>(current.query.only === 'storage' && current.query.add !== 'team' ? { ...empty } : restore());
  const dayFormat = () => dayPlaceholder({ day: t('DD'), month: t('MM'), year: t('YYYY') });
  // From the team selection ("Create a new team"): storage and sign-in are done already, so the
  // wizard starts at the team and offers nothing but a new team. It is not kept as a draft.
  const addRequested = current.query.add === 'team';
  let adding = $state(addRequested);
  // From Settings, Storage ("Run first-start setup again"): only the storage (and the name) is asked
  // for; the teams are not touched and the person can leave at any time. Not kept as a draft.
  let storageOnly = $state(!addRequested && current.query.only === 'storage');
  if (addRequested) {
    d.kind = 'keep';
    d.team = 'new';
    d.step = 'team';
  }
  let info = $state<SetupState>();
  let regions = $state<Region[]>([]);
  let os = $state('linux');
  let token = $state('');
  let tokenOk = $state(false);
  let guide = $state('');
  let username = $state('');
  let problem = $state<Problem | null>(null);
  let message = $state('');
  let serverOk = $state('');
  let busy = $state(false);
  // What the data folder was made from (kind, address, target); the same choice is not made twice.
  let applied = '';

  $effect(() => {
    if (adding || storageOnly) return;
    // An address with credentials in it is never written down (the core rejects it anyway).
    const snapshot = JSON.stringify({ ...d, start: parseDayInput(d.start) || d.start, address: safeToStore(d.address) ? d.address : '', trackerUrl: safeToStore(d.trackerUrl) ? d.trackerUrl : '' });
    try {
      localStorage.setItem(KEY, snapshot);
    } catch {
      /* the draft is only a convenience */
    }
  });

  // A guided flow shows this wizard: the tour asks for a step, and a step of the wizard moves the tour.
  $effect(() => {
    const want = wizard.request;
    if (!want) return;
    wizard.request = '';
    if (want !== d.step && steps.includes(want as Step)) d.step = want as Step;
  });
  $effect(() => {
    followWizard(d.step);
  });

  // A new step is announced: focus moves to its heading.
  let first = true;
  $effect(() => {
    void d.step;
    if (first) {
      first = false;
      return;
    }
    void tick().then(() => {
      const h = document.querySelector<HTMLElement>('.wizard h2');
      h?.setAttribute('tabindex', '-1');
      h?.focus();
    });
  });

  onMount(async () => {
    try {
      // The wizard works on the real data folder.
      if (app.demo && !tour.flow) await leaveDemo(); // a guided flow runs the wizard on the demo team
      info = await api.SetupState();
      regions = await api.SetupRegions();
      os = (await api.Info()).os;
      d.name ||= info.name;
      d.email ||= info.email;
      if (info.teams.some((x) => !x.problem) && d.kind === 'clone' && !d.address) d.kind = 'keep';
      if (adding && !info.teams.some((x) => !x.problem)) {
        // No team of the real data yet (only the demo was open): the full wizard asks for the storage.
        adding = false;
        Object.assign(d, restore());
      }
    } catch (e) {
      fail(null, String(e));
    }
  });

  const hasTeams = $derived((info?.teams ?? []).filter((x) => !x.problem));
  const cloneTarget = $derived(d.parent ? joinPath(d.parent, repoName(d.address), os) : '');
  const patternHint = $derived((parseDayInput(d.start) ? derivePattern(d.sprintId, parseDayInput(d.start)) : ''));
  const country = $derived(regions.find((r) => r.country === d.country));
  const steps = $derived<Step[]>(storageOnly ? ['storage', 'signin', 'done'] : adding ? ['team', 'tickets', 'done'] : d.team === 'new' ? ['storage', 'signin', 'team', 'tickets', 'done'] : ['storage', 'signin', 'team', 'done']);
  const index = $derived(Math.max(0, steps.indexOf(d.step)));
  const labels: Record<Step, () => string> = {
    storage: () => t('Storage'),
    // only a server needs a sign-in; for a folder on this computer the step asks for the name
    signin: () => (d.kind === 'clone' ? t('Sign-in') : t('Name')),
    team: () => t('Team'),
    tickets: () => t('Tickets'),
    done: () => t('Finish'),
  };

  const sources: { key: TicketSource; icon: 'sync' | 'edit_note' | 'pin'; title: () => string; text: () => string }[] = [
    { key: 'packages', icon: 'edit_note', title: () => t('Work packages in Foresprint'), text: () => t('No tracker. You create work packages by hand; everything else works as with a tracker.') },
    { key: 'none', icon: 'pin', title: () => t('No tickets'), text: () => t('No backlog. You plan amounts per product and project, and the commitment is a number.') },
    { key: 'tracker', icon: 'sync', title: () => t('Connect a tracker (Jira)'), text: () => t('Tickets are only read; the tracker is not changed unless you switch that on later.') },
  ];

  /** Shows a problem or a plain message; returns whether there is one. */
  function fail(p: Problem | null | undefined, text = ''): boolean {
    problem = p ?? null;
    message = text;
    return !!p || !!text;
  }

  async function pickParent(): Promise<void> {
    const got = await api.PickFolder(t('Choose the folder the data is copied into'));
    if (got) d.parent = got;
  }

  async function pickFolder(): Promise<void> {
    const got = await api.PickFolder(t('Choose the data folder'));
    if (got) d.folder = got;
  }

  async function checkServer(): Promise<void> {
    serverOk = '';
    fail(null);
    busy = true;
    try {
      const r = await api.SetupCheckServer(d.address);
      if (r.ok) serverOk = r.empty ? t('Reachable. The repository is still empty.') : t('Reachable.');
      else fail(r.problem);
    } finally {
      busy = false;
    }
  }

  async function guideFor(): Promise<void> {
    if (!needsToken(d.address)) return;
    const g = await api.SetupGuide(d.address);
    guide = g.steps;
    username = g.username;
  }

  /** Hands the token to the credential helper; returns whether the server takes it. */
  async function testToken(): Promise<boolean> {
    fail(null);
    const was = busy;
    busy = true;
    try {
      const p = await api.SetupSignIn(d.address, username, token);
      tokenOk = !p;
      return !fail(p);
    } catch (e) {
      tokenOk = false;
      fail(null, String(e));
      return false;
    } finally {
      token = ''; // never kept in the window
      busy = was;
    }
  }

  async function saveIdentity(): Promise<boolean> {
    if (!d.name.trim() || !d.email.trim()) return true; // optional here; saving asks again
    return !fail(await api.SetupIdentity(d.name.trim(), d.email.trim()));
  }

  /** Makes the data folder as chosen. Runs once, on leaving the step that needs it. */
  async function applyStorage(): Promise<boolean> {
    if (d.kind === 'keep') return true;
    const target = d.kind === 'clone' ? cloneTarget : d.folder;
    const key = [d.kind, d.address, target].join('|');
    if (applied === key) return true;
    const r = await api.SetupStorage(d.kind, d.address, target);
    if (fail(r.problem)) return false;
    applied = key;
    info = await api.SetupState();
    const usable = info.teams.filter((x) => !x.problem);
    if (usable.length > 0) {
      d.team = 'existing';
      d.existing = usable[0]?.key ?? '';
    } else if (d.team === 'existing') d.team = 'new';
    return true;
  }

  /** Where Cancel leads: back to where the wizard was opened from; '' on a first start without any team. */
  const leaveTo = $derived(storageOnly ? '/settings/storage' : adding ? '/today' : hasTeams.length > 0 && !tour.flow ? '/today' : '');

  /** Storage is set: on to the end, or, if the data has no team at all, on to the team step. */
  function afterStorage(): void {
    if (storageOnly && info && !info.teams.some((x) => !x.problem)) {
      storageOnly = false;
      d.team = 'new';
      d.step = 'team';
    } else d.step = storageOnly ? 'done' : 'team';
  }

  function missingStorage(): string {
    if (d.kind === 'clone') {
      if (!d.address.trim()) return t('Enter the address of the repository.');
      if (!d.parent) return t('Choose the folder the data is copied into.');
    } else if (d.kind !== 'keep' && !d.folder) return t('Choose a folder.');
    return '';
  }

  function missingTeam(): string {
    if (d.team === 'existing' && !d.existing) return t('Choose a team.');
    if (d.team !== 'new') return '';
    if (!d.teamName.trim()) return t('Enter a name for the team.');
    if (!d.sprintId.trim()) return t('Enter the ID of the first sprint.');
    if (!parseDayInput(d.start)) return t('Enter the start of the first sprint as a date ({format}).', { format: dayFormat() });
    return '';
  }

  function missingTracker(): string {
    if (d.source === 'tracker' && (!d.trackerUrl.trim() || !d.trackerQuery.trim())) {
      return t('Enter the address of the tracker and the query that selects the tickets.');
    }
    return '';
  }

  async function next(): Promise<void> {
    if (busy) return;
    fail(null);
    busy = true;
    try {
      if (d.step === 'storage') {
        if (fail(null, missingStorage())) return;
        if (d.kind !== 'clone' && !(await applyStorage())) return;
        if (d.kind === 'clone') await guideFor();
        if (d.kind === 'clone' || !d.name) d.step = 'signin';
        else afterStorage();
      } else if (d.step === 'signin') {
        if (token && !(await testToken())) return;
        if (!(await saveIdentity())) return;
        if (d.kind === 'clone' && !(await applyStorage())) {
          if (problem?.kind === 'auth') tokenOk = false;
          return;
        }
        afterStorage();
      } else if (d.step === 'team') {
        if (d.team === 'existing' && !hasTeams.some((x) => x.key === d.existing)) d.existing = hasTeams[0]?.key ?? '';
        if (fail(null, missingTeam())) return;
        d.step = d.team === 'new' ? 'tickets' : 'done';
      } else if (d.step === 'tickets') {
        if (fail(null, missingTracker())) return;
        d.step = 'done';
      }
    } finally {
      busy = false;
    }
  }

  function goTo(step: Step): void {
    fail(null);
    d.step = step;
  }

  async function back(): Promise<void> {
    if (index === 0 && leaveTo) {
      // The data folder may have been changed by a step already taken: read the teams again.
      if (applied) await loadTeams();
      return go(leaveTo);
    }
    const prev = steps[index - 1];
    if (prev) goTo(prev);
  }

  async function finish(): Promise<void> {
    if (busy) return;
    fail(null);
    busy = true;
    try {
      if (storageOnly) {
        // The data folder may have changed: read the teams again and keep the selected one if it is still there.
        await loadTeams();
        go('/settings/storage');
        return;
      }
      if (d.team === 'demo') {
        await enterDemo();
      } else if (d.team === 'new') {
        const made = await api.SetupCreateTeam({
          name: d.teamName,
          country: d.country,
          region: d.region,
          firstSprintId: d.sprintId,
          firstStart: parseDayInput(d.start),
          namingPattern: d.pattern.trim(),
          lengthDays: 14,
          source: d.source,
          trackerUrl: d.trackerUrl,
          trackerQuery: d.trackerQuery,
        });
        // In a guided flow the wizard only pretends: the team it "made" exists in the mock only.
        if (!app.demo) {
          await loadTeams();
          await selectTeam(made.key);
        }
      } else if (!app.demo) {
        await loadTeams();
        await selectTeam(d.existing);
      }
      try {
        localStorage.removeItem(KEY);
      } catch {
        /* nothing to remove */
      }
      go('/today');
    } catch (e) {
      fail(null, String(e));
    } finally {
      busy = false;
    }
  }

  async function lookAround(): Promise<void> {
    d.team = 'demo';
    await finish();
  }

  const summary = $derived({
    storage:
      d.kind === 'keep'
        ? t('The data folder as it is: {folder}', { folder: info?.dataDir ?? '' })
        : d.kind === 'clone'
          ? t('Copied from {address}', { address: d.address })
          : d.kind === 'open'
            ? t('Opened: {folder}', { folder: d.folder })
            : t('Started new: {folder}', { folder: d.folder }),
    team: d.team === 'demo' ? t('Team Atlas (demo)') : d.team === 'new' ? d.teamName : (hasTeams.find((x) => x.key === d.existing)?.name ?? d.existing),
    work:
      d.team !== 'new'
        ? ''
        : d.source === 'tracker'
          ? t('From a tracker, connected under Tickets and tracker')
          : d.source === 'packages'
            ? t('Work packages in Foresprint')
            : t('No tickets'),
  });
</script>

<div class="wizard">
  <PageHead title={adding ? t('New team') : storageOnly ? t('Storage setup') : t('First start')} lead={t('A few short steps. You can go back at any time; everything stays changeable in the settings.')} />

  <nav class="stepper" aria-label={t('Steps')}>
    {#each steps as s, i (s)}
      <button type="button" class="step" class:active={i === index} class:done={i < index} aria-current={i === index ? 'step' : undefined} disabled={i >= index} onclick={() => goTo(s)}>
        <span class="n">{#if i < index}<Icon name="check" size={14} />{:else}{i + 1}{/if}</span>{labels[s]()}
      </button>
    {/each}
  </nav>

  {#if problem}
    <div class="gap">
      <Banner tone="bad">
        <strong>{problem.title || t('This did not work')}</strong> {problem.message}
        {#if problem.hint}<span class="block muted">{problem.hint}</span>{/if}
      </Banner>
    </div>
  {:else if message}
    <div class="gap"><Banner tone="warn">{message}</Banner></div>
  {/if}

  <div class="card body stack" data-tour="firstrun-step">
    {#if d.step === 'storage'}
      <h2>{t('Where does the team keep its data?')}</h2>
      <div class="stack" role="radiogroup" aria-label={t('Where does the team keep its data?')}>
        {#if hasTeams.length > 0}
          <div class="opt" class:on={d.kind === 'keep'}>
            <input type="radio" id="opt-kind-keep" name="kind" value="keep" bind:group={d.kind} />
            <span><label for="opt-kind-keep"><strong>{t('Keep the data folder as it is')}</strong></label><span class="block small muted">{t('{n} team(s) found in {folder}.', { n: hasTeams.length, folder: info?.dataDir ?? '' })}</span></span>
          </div>
        {/if}
        <div class="opt" class:on={d.kind === 'clone'}>
          <input type="radio" id="opt-kind-clone" name="kind" value="clone" bind:group={d.kind} />
          <span class="grow">
            <label for="opt-kind-clone"><strong>{t('Load from an address')}</strong></label>
            <span class="block small muted">{t('The team already has a repository on a server. Foresprint copies it to this computer.')}</span>
            {#if d.kind === 'clone'}
              <span class="fields">
                <span class="field"><label for="su-addr">{t('Address')}</label><input id="su-addr" class="input data" bind:value={d.address} placeholder="https://git.example.com/team/data.git" oninput={() => (serverOk = '')} /></span>
                <span class="row">
                  <button class="btn" type="button" disabled={busy || !d.address.trim()} onclick={checkServer}><Icon name="network_check" />{t('Test connection')}</button>
                  {#if serverOk}<span class="chip ok" role="status"><Icon name="check_circle" size={14} />{serverOk}</span>{/if}
                </span>
                <span class="row">
                  <button class="btn" type="button" onclick={pickParent}><Icon name="folder_open" />{t('Choose where to copy it')}</button>
                  <span class="data small grow">{cloneTarget || t('No folder chosen yet')}</span>
                </span>
              </span>
            {/if}
          </span>
        </div>
        <div class="opt" class:on={d.kind === 'open'}>
          <input type="radio" id="opt-kind-open" name="kind" value="open" bind:group={d.kind} />
          <span class="grow">
            <label for="opt-kind-open"><strong>{t('Open an existing folder')}</strong></label>
            <span class="block small muted">{t('A repository with the data of the team is already on this computer.')}</span>
            {#if d.kind === 'open'}
              <span class="fields row"><button class="btn" type="button" onclick={pickFolder}><Icon name="folder_open" />{t('Choose folder')}</button><span class="data small grow">{d.folder || t('No folder chosen yet')}</span></span>
            {/if}
          </span>
        </div>
        <div class="opt" class:on={d.kind === 'new'}>
          <input type="radio" id="opt-kind-new" name="kind" value="new" bind:group={d.kind} />
          <span class="grow">
            <label for="opt-kind-new"><strong>{t('Start a new one')}</strong></label>
            <span class="block small muted">{t('An empty repository for a new team. You can add the server address later.')}</span>
            {#if d.kind === 'new'}
              <span class="fields row"><button class="btn" type="button" onclick={pickFolder}><Icon name="folder_open" />{t('Choose folder')}</button><span class="data small grow">{d.folder || t('No folder chosen yet')}</span></span>
            {/if}
          </span>
        </div>
        <div class="opt off" aria-disabled="true">
          <input type="radio" disabled aria-label={t('Shared folder')} />
          <span><strong>{t('Shared folder')}</strong> <span class="chip">{t('after 1.0')}</span><span class="block small muted">{t('A file server or SharePoint follows after 1.0.')}</span></span>
        </div>
      </div>
    {:else if d.step === 'signin'}
      <h2>{d.kind === 'clone' ? t('Sign-in and name') : t('Your name')}</h2>
      <div class:grid={d.kind === 'clone'} class:cols-2={d.kind === 'clone'}>
        {#if d.kind === 'clone'}
        <div class="stack">
          {#if needsToken(d.address)}
            <div class="field">
              <label for="su-token">{t('Token')}</label>
              <input id="su-token" class="input data" type="password" autocomplete="new-password" bind:value={token} placeholder={t('Paste the token')} />
            </div>
            <div class="row">
              <button class="btn" type="button" disabled={busy || !token} onclick={testToken}><Icon name="verified_user" />{t('Test sign-in')}</button>
              {#if tokenOk}<span class="chip ok" role="status"><Icon name="check_circle" size={14} />{t('Sign-in works')}</span>{/if}
            </div>
            <p class="small muted">{t('The token goes to the credential helper of your system, not into the team data. A server that can be read without sign-in needs none; skip this part then.')}</p>
            {#if guide}<p class="small guide">{guide}</p>{/if}
            {#if info?.suggestedHelper}
              <div class="row">
                <span class="small">{t('This computer offers a credential helper: {name}.', { name: info.suggestedHelper })}</span>
                <button class="btn" type="button" onclick={async () => fail(await api.SetupEnableHelper(info?.suggestedHelper ?? ''))}>{t('Turn it on')}</button>
              </div>
            {/if}
          {:else}
            <p class="muted">{t('This address needs no sign-in.')}</p>
          {/if}
        </div>
        {/if}
        <div class="stack">
          {#if d.kind !== 'clone'}<p class="muted">{t('A folder on this computer needs no sign-in. Foresprint only needs your name for the history.')}</p>{/if}
          <div class="field"><label for="su-name">{t('Your name')}</label><input id="su-name" class="input" bind:value={d.name} /></div>
          <div class="field"><label for="su-mail">{t('Email')}</label><input id="su-mail" class="input" type="email" bind:value={d.email} /></div>
        </div>
      </div>
    {:else if d.step === 'team'}
      <h2>{t('Team')}</h2>
      <div class="stack" role="radiogroup" aria-label={t('Team')}>
        {#if hasTeams.length > 0 && !adding}
          <div class="opt" class:on={d.team === 'existing'}>
            <input type="radio" id="opt-team-existing" name="team" value="existing" bind:group={d.team} />
            <span class="grow">
              <label for="opt-team-existing"><strong>{t('Open a team from the data')}</strong></label>
              {#if d.team === 'existing'}
                <span class="fields field">
                  <label for="su-existing">{t('Team')}</label>
                  <select id="su-existing" class="input" bind:value={d.existing}>
                    {#each hasTeams as x (x.key)}<option value={x.key}>{x.name}</option>{/each}
                  </select>
                </span>
              {/if}
            </span>
          </div>
        {/if}
        <div class="opt" class:on={d.team === 'new'}>
          <input type="radio" id="opt-team-new" name="team" value="new" bind:group={d.team} />
          <span class="grow">
            <label for="opt-team-new"><strong>{t('Create a new team')}</strong></label>
            <span class="block small muted">{t('Name, region for holidays and the first sprint.')}</span>
            {#if d.team === 'new'}
              <span class="fields grid cols-2">
                <span class="field"><label for="su-tn">{t('Team name')}</label><input id="su-tn" class="input" bind:value={d.teamName} placeholder={t('e.g. Team North')} /></span>
                <span class="field">
                  <label for="su-country">{t('Country')}</label>
                  <select id="su-country" class="input" bind:value={d.country} onchange={() => (d.region = '')}>
                    {#each regions as r (r.country)}<option value={r.country}>{r.name}</option>{/each}
                  </select>
                </span>
                <span class="field">
                  <label for="su-region">{t('Region')}</label>
                  <select id="su-region" class="input" bind:value={d.region}>
                    <option value="">{t('Whole country')}</option>
                    {#each country?.regions ?? [] as r (r)}<option value={r}>{r}</option>{/each}
                  </select>
                </span>
                <span class="field"><label for="su-sid">{t('First sprint (running now or next)')}</label><input id="su-sid" class="input data" bind:value={d.sprintId} /></span>
                <span class="field">
                  <label for="su-pat">{t('Naming pattern of the sprints (optional)')}</label>
                  <input id="su-pat" class="input data" bind:value={d.pattern} placeholder={patternHint || t('e.g. Team {JJJJ}.{N}')} />
                  <span class="small muted">{patternHint && !d.pattern.trim() ? t('Read from the name: {pattern}. The next sprints are named the same way.', { pattern: patternHint }) : t('{JJJJ} year, {N} number in the year, {LFD} running number.')}</span>
                </span>
                <span class="field"><label for="su-sd">{t('First sprint starts on')}</label><input id="su-sd" class="input data" bind:value={d.start} placeholder={dayFormat()} /></span>
              </span>
            {/if}
          </span>
        </div>
        {#if !adding}
        <div class="opt" class:on={d.team === 'demo'}>
          <input type="radio" id="opt-team-demo" name="team" value="demo" bind:group={d.team} />
          <span><label for="opt-team-demo"><strong>{t('Open the demo team')}</strong></label><span class="block small muted">{t('Invented sample data to try things out. Nothing is read from or written to your data.')}</span>
            {#if d.team === 'demo'}<DemoChoice id="firstrun" />{/if}
          </span>
        </div>
        {/if}
      </div>
    {:else if d.step === 'tickets'}
      <h2>{t('Where does the work come from?')}</h2>
      <div class="stack" role="radiogroup" aria-label={t('Where does the work come from?')}>
        {#each sources as s (s.key)}
          <div class="opt" class:on={d.source === s.key}>
            <input type="radio" id={`opt-source-${s.key}`} name="source" value={s.key} bind:group={d.source} />
            <span class="grow">
              <label for={`opt-source-${s.key}`}><strong><Icon name={s.icon} size={16} /> {s.title()}</strong></label>
              <span class="block small muted">{s.text()}</span>
              {#if s.key === 'tracker' && d.source === 'tracker'}
                <span class="fields grid cols-2">
                  <span class="field"><label for="su-ju">{t('Address of the tracker')}</label><input id="su-ju" class="input data" bind:value={d.trackerUrl} placeholder="https://jira.example.com" /></span>
                  <span class="field"><label for="su-jq">{t('Query that selects the tickets (JQL)')}</label><input id="su-jq" class="input data" bind:value={d.trackerQuery} /></span>
                </span>
                <span class="block small muted">{t('The token and the fields are set under Settings, Tickets and tracker, where you can also test the connection.')}</span>
              {/if}
            </span>
          </div>
        {/each}
      </div>
    {:else}
      <h2>{t('Finish')}</h2>
      <Banner tone="info">{t('Everything is set up. You can change each point later in the settings.')}</Banner>
      <dl class="kv">
        {#if d.team !== 'demo' && !adding}<dt>{t('Storage')}</dt><dd>{summary.storage}</dd>{/if}
        {#if !storageOnly}<dt>{t('Team')}</dt><dd>{summary.team}</dd>{/if}
        {#if summary.work && !storageOnly}<dt>{t('Work')}</dt><dd>{summary.work}</dd>{/if}
      </dl>
    {/if}
  </div>

  <div class="row nav">
    <button class="btn" type="button" disabled={(index === 0 && !leaveTo) || busy} onclick={back}><Icon name="arrow_back" />{index === 0 && leaveTo ? t('Cancel') : t('Back')}</button>
    <span class="grow small muted">{adding || storageOnly ? '' : t('Your choices are kept as a draft.')}</span>
    {#if d.step === 'signin'}
      <button class="btn ghost" type="button" disabled={busy} onclick={next}>{t('Skip')}</button>
    {/if}
    {#if d.step === 'done'}
      <button class="btn primary" type="button" disabled={busy} onclick={finish}>{storageOnly ? t('Done') : t('Go to Today')}<Icon name="arrow_forward" /></button>
    {:else}
      <button class="btn primary" type="button" disabled={busy} onclick={next}>{busy ? t('Working…') : t('Next')}<Icon name="arrow_forward" /></button>
    {/if}
  </div>

  {#if d.step === 'storage' && !adding && !storageOnly}
    <div class="card around stack">
      <h2>{t('Just looking around?')}</h2>
      <p class="muted">{t('Open the demo team with invented data, or follow a guided walk-through. Your own data stays untouched.')}</p>
      <div class="row">
        <button class="btn" type="button" disabled={busy} onclick={lookAround}><Icon name="school" />{t('Open the demo team')}</button>
        <a class="btn" href={link('/help/guided')} onclick={() => void enterDemo()}><Icon name="route" />{t('Guided flows')}</a>
      </div>
    </div>
  {/if}
</div>

<style>
  .wizard {
    max-width: 800px;
    margin: 0 auto;
    padding: 24px 16px 64px;
  }
  .gap {
    margin-bottom: 12px;
  }
  .body {
    gap: 12px;
  }
  h2 {
    margin: 0;
    font-size: 16px;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .block {
    display: block;
  }
  .nav {
    margin-top: 16px;
  }
  .around {
    margin-top: 24px;
  }
  .stepper {
    flex-wrap: wrap;
  }
  .step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-radius: var(--r-ctl);
    color: var(--text-muted);
    background: var(--surface);
    border: 1px solid var(--border);
    white-space: nowrap;
    font: inherit;
  }
  .step.active {
    color: var(--primary);
    border-color: var(--primary);
    font-weight: 600;
  }
  .step:not(:disabled) {
    cursor: pointer;
    color: var(--text);
  }
  .step .n {
    font: 12px var(--font-data);
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--surface-2);
  }
  .step.done .n {
    background: var(--ok-weak);
    color: var(--ok);
  }
  .step.active .n {
    background: var(--primary);
    color: var(--on-primary);
  }
  .opt {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--r-card);
  }
  .opt > span > label:first-child,
  .opt > span > strong {
    cursor: pointer;
  }
  .opt.on {
    border-color: var(--primary);
    background: var(--primary-weak);
  }
  .opt.off {
    opacity: 0.7;
    cursor: default;
  }
  .opt input {
    margin-top: 3px;
  }
  .fields {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 8px;
  }
  .fields.grid {
    display: grid;
  }
  .fields.row {
    flex-direction: row;
  }
  .guide {
    white-space: pre-wrap;
  }
  a.btn {
    text-decoration: none;
    color: var(--text);
  }
  p {
    margin: 0;
  }
</style>
