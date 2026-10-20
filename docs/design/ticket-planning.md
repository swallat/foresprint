# Design: Ticket pre-planning and tracker integration (optional)

Status: draft, version 6 (19 October 2026); implementation progress in section 10. This version
**replaces version 5 completely**; it is the only valid design for the Jira integration.
Implementation starts on release 0.6.0 (the PR wave of October 2026 is merged), see section 10. Everything that
applies without a ticket system (calculation, operation, data folder, synchronisation) is in
[core.md](core.md).

What is dropped compared to version 5: the snapshot model (planning and review state), the
review proposal from ticket remainders, the balance, the multi-product weighting and the phases
T0 to T4. What is new: projects with a target date, the automatic distribution of tickets across
future sprints, the timeline, the refinement list, configurable assignment rules and the
later write-back of a label.

## 1. Starting point and goal

In Jira, tickets that are not yet refined may no longer be pulled into future sprints.
The previous earmark ("this ticket goes into sprint 44") therefore no longer has a place.
At the same time, every ticket has an estimate (from the refinement, from the rough estimate or
assigned by the PO), a project assignment, and every project has a target date.

The tool should therefore answer:

1. **Into which sprint must a ticket go at the latest so that its project's target date holds?**
   For this, the tool distributes the tickets automatically across future sprints, taking into
   account dependencies and the sprint budget from the forecast.
2. **Does a project meet its target date?** Traffic light per project and timeline across all projects.
3. **What has to be refined by when?** Refinement list per sprint.
4. **Which earmark applies?** Manual earmarks by the PO, the real Jira sprint and (later) a
   label in Jira are merged in a clear order of precedence.

The target audience is product owners. The forecast core stays unchanged; the pre-planning reads
its results (Forecast PLAN, default distribution per product, production access) and writes
at most the sums per product as a proposal into the PO pre-planning (section 10, step 4).

## 2. Principles

- **Can be switched off.** `features.tickets` (default `false`). Without the switch there is no page,
  no menu entry, no files and no loaded module; the app works as before.
- **Generally applicable and open source.** The code contains no assumptions about an instance: no
  URLs, field names, projects, labels or rules as defaults. Everything instance- and team-specific
  lives in the team's configuration in the data repo (without secrets).
- **Source interchangeable.** Tickets come from an interface `TicketSource`: CSV import and
  Jira first, GitHub and GitLab later (section 7.4). Manual maintenance is equivalent. The
  calculation core (distribution) knows no source.
- **Read-only, with one exception.** Towards the tracker, only reads happen. The only write,
  not before step 5 and switchable off: the label `planned_for_<sprint_id>` (section 6.6).
- **Who is responsible for what.** The tracker is responsible for ticket data and the real sprint assignment.
  The tool is responsible for projects, earmarks (planning intent) and the distribution.
- **Deterministic and explainable.** The distribution is a fixed order without randomness; for
  every ticket it can be said why it is in its sprint.
- **Capacity and forecast work without a tracker.** The integration complements, it is never
  a prerequisite.

## 3. Non-goals (for now)

- No replacement for the ticket system, no ticket editing beyond the label.
- No import of old sprints, no review proposal from ticket data (the sprint file remains the
  only source for commitment, done and not done).
- No conversion between person-days and story points.
- No optimisation (no "best" distribution); the greedy distribution from section 5 suffices and
  stays traceable.
- No multi-product ticket: a ticket belongs to exactly one project and thus one product;
  contradictions are shown, not weighted.
- No rule of thumb "latest sprint" from the fulfilment history (rejected).
- Epic roadmap with Monte Carlo: deferred; it follows later from the projects.

## 4. Domain model

### 4.1 Terms

| Term | Meaning |
|---|---|
| **Ticket** | Unit of work from the tracker or entered by hand: key, title, status, project, estimate, remaining, origin of the estimate (`refined`, `rough`, `manual`, `none`), real sprint according to the tracker (`in_sprint`), rank, dependencies (`depends_on`), labels, components, epic |
| **Project** | Undertaking with target date, product, priority and assignment rules (`match:`); a project belongs to exactly one product. "Project" here is not a Jira project but a topic of the PO |
| **Earmark** | Intent of the PO to put a ticket into a future sprint without pulling it there in Jira. Created by hand or by the distribution |
| **Budget** | What a sprint can still take on for pre-planning, per product (section 5.1) |
| **Target sprint** | Last sprint whose end lies before the project's target date |

### 4.2 Estimate and remaining

Two values per ticket, both with a configurable source (section 6.2):

- **Estimate** (`estimate`): refinement or rough value, does not change during the work.
- **Remaining** (`remaining`): current remaining effort; equal to the estimate until work starts.

The distribution calculates with `planning_uses: remaining` (remaining if filled, otherwise estimate;
default) or `planning_uses: estimate`. A ticket with neither counts as **unestimated**, is
not distributed and is shown at the top of the page. The PO can store an own estimate in
`preplan.yaml` (`manual`).

### 4.3 Storage in the data repo (per team)

| File | Content | Written by |
|---|---|---|
| `team.yaml`, section `tracker:` | source, query, field names, rules (section 6.1) | setup |
| `projects.yaml` | projects with target date, product, priority, `match:` | PO |
| `tickets.yaml` | last import state: key, title, numbers, status, sprint, dependencies, assignment | import (CSV or tracker) |
| `preplan.yaml` | manual earmarks (ticket → sprint, note) and own estimates | PO |

The distribution itself is **not stored**; it is recalculated from these files and the forecast on
every load. Secrets (tokens) are never in these files.

## 5. Distribution

### 5.1 Budget per sprint and product

```
Budget[s, p] = DefaultShare[p] × Base[s]  −  Σ (tickets already in sprint s according to the tracker, product p)
```

- `Base[s]` is configurable per **product and project**: the plannable share of the Forecast PLAN
  (`roadmap_share`, default) or the whole Forecast PLAN. Project budget = default share of its
  product from `products.distribution`. Production access is added as `production_available`
  when the feature is active.
- Horizon as in `analysis.completion`: up to 26 sprints; beyond the people list, the average
  of the last sprints counts as capacity.
- Tickets that are already in a future sprint according to the tracker (`in_sprint`) are fixed points
  and consume budget, but are not distributed. The same applies to manual earmarks from
  `preplan.yaml`.

### 5.2 Order and placement

1. **Projects** by target date, then priority; tickets within a project by rank.
2. **Topologically** by `depends_on`; a cycle is an error that is shown.
3. Each ticket goes into the **earliest sprint** from (latest sprint of its dependencies
   + `dependency_gap`) whose remaining budget for its product suffices. `dependency_gap` is configurable
   per team: `1` (default, the sprint after) or `0` (the same sprint is allowed).
4. A ticket that is **larger than a whole sprint budget** is not distributed and is reported as "too
   large, split". Unestimated tickets likewise ("unestimated").
5. Result: sprint per ticket, fill level per sprint and product, list "not distributable".

### 5.3 Project traffic light

For each project, the sprint of its last ticket is compared with the target sprint:

| Traffic light | Condition |
|---|---|
| **on track** | last sprint is at least one sprint before the target sprint |
| **tight** | last sprint is the target sprint |
| **missed** | last sprint is after the target sprint, or a ticket is not distributable |

### 5.4 Refinement list

For each future sprint, the tickets whose estimate is `rough` or `manual`, with deadline = planning
of the sprint. This is the answer to "what has to be refined by when". Tickets with unclear
refined status (section 6.3) are listed separately above.

### 5.5 Uncertainty (step 4)

The distribution is calculated three times: with the lowest, the median and the highest
normalized velocity from `analysis.band` (conservative, median, optimistic). In the conservative
variant, rough estimates are multiplied by `rough_factor` (team setting, default 1.5).
The median variant is shown; traffic light and timeline show the range.

The shown median variant is the **Forecast PLAN** of the sprint as the forecast calculates it,
not a separately computed median; only the conservative and optimistic variants recalculate the
plan of every horizon sprint from the lowest and highest normalized velocity (`analysis.band`).
The variants differ in nothing else, except that `rough_factor` is applied in the conservative
variant only (to rough estimates and to tickets with unclear refined status, not to refined or
manual estimates). With fewer than two sprints with velocity there is no range. Greedy placement
is not monotone across variants: earliest and latest are the minimum and maximum over the three.

## 6. Input data and configuration

### 6.1 `team.yaml`, section `tracker:`

```yaml
features:
  tickets: true

tracker:
  kind: jira                     # jira | csv   (later: github, gitlab)
  base_url: https://jira.example.org
  query: 'project = ABC AND resolution = Unresolved ORDER BY Rank'
  fields:                        # display names of the instance, resolved via /rest/api/2/field
    estimate: Ursprüngliche Story-Punkte
    remaining: Story-Punkte
    epic: Epos-Verknüpfung       # alternatively: Übergeordnet
  planning_uses: remaining       # remaining | estimate
  refined_label: Refined
  refined_also_if:               # counts as refined even if the label is missing
    any:
      - in_sprint: true
      - status_not: [To Do]
  project_match_order: [epic, component, label]
  dependency_gap: 1              # 0 = dependency may be in the same sprint
  budget_basis: roadmap_share    # roadmap_share | plan; can be overridden per product/project
  rough_factor: 1.5
  write_labels: false            # step 5: write planned_for_<sprint_id> to Jira
```

All values are examples; the code contains none of them as a default. The setup proposes
fields and status values from the instance and stores the selection.

### 6.2 Where estimate and remaining come from

`fields.estimate` and `fields.remaining` name the fields by their **display name**; the tool
resolves them to the field ID (`customfield_…`) when connecting and reports when a name is ambiguous
or unknown. If `remaining` is missing in the instance, it may be omitted; the tool then calculates
with the estimate only. For the CSV import, the columns are named as in the Jira export
("Custom field (Ursprüngliche Story-Punkte)" or "Benutzerdefiniertes Feld (…)").

### 6.3 Refined or not

A ticket counts as refined if it carries the `refined_label` **or** fulfils a condition from
`refined_also_if` (in practice the label is sometimes forgotten). The import preview
shows a list "refined status unclear": tickets that count as refined only via the additional
condition, or that carry the label but have no estimate. Until clarified, the estimate counts
as `rough`.

### 6.4 Project assignment and assignment rules

Each project carries its criteria in `projects.yaml` under `match:`. A ticket belongs to the
project whose rule it fulfils. If two projects match, `project_match_order` decides by
the **source** of the match (default: epic before component before label); if two projects match via
the same source, that is a contradiction that appears in the preview and stays "without
project" until clarified.

```yaml
# projects.yaml
schema: 1
projects:
  - id: payment-v2
    name: Payment processing v2
    product: shop
    target: 2027-03-31
    priority: 1
    budget_basis: plan             # optional, overrides the team default
    match:                         # short form: lists are OR-combined
      epic: [ABC-100, ABC-101]
      label: [payment]

  - id: migration
    name: Database migration
    product: platform
    target: 2027-01-15
    priority: 2
    match:                         # long form: any (OR), all (AND), none (exclusion)
      all:
        - component: [Database]
        - none:
            - label: [maintenance, hotfix]
        - any:
            - epic: [ABC-200]
            - status: [Ready]
```

Rule language:

- **Leaf** = one source (`epic`, `component`, `label`, `status`, `issue_type`, `in_sprint`)
  with a list of values; the values of a leaf are OR-combined.
- **Short form:** several leaves directly under `match:` are OR-combined (any match
  suffices).
- **Long form:** `any` (at least one), `all` (all), `none` (none); can be nested arbitrarily.
- The same language applies to `refined_also_if` and to the product assignment without a project.
- Validation rejects empty lists, unknown sources and short and long form in the same
  `match:`.

### 6.5 Reconciliation on import

| State in the tracker | Reaction |
|---|---|
| Ticket in current or future real sprint | counts as planned; counts against the budget of that sprint; a deviating earmark is discarded and the deviation is shown |
| Ticket done | earmark is dropped, hint |
| Ticket no longer in the query | earmark stays with a warning until its sprint is over; the next import then drops it |
| Ticket deleted or not readable | warning "not verifiable", earmark stays visible |
| Estimate or remaining changed | new number, distribution recalculates |
| Ticket without project or with two projects | list "to be assigned" in the preview |
| Unknown epic | list "unknown epic" (candidate for a new project) |

The import has two stages like the Excel import: preview (new, changed, done, to be assigned,
refined unclear) and then apply to `tickets.yaml`.

### 6.6 Writing back a label (step 5)

If `write_labels: true`, the tool sets the label `planned_for_<sprint_id>` on the ticket when
earmarking and removes an existing `planned_for_*` label; writes happen only on change and
after a preview. On import, such labels are read as earmarks.

Precedence on contradiction: **Jira sprint field > earmark in the tool > label.** If a ticket is
in a real sprint in Jira, the tool adopts that sprint, discards the deviating
earmark, shows the deviation and cleans up the label on the next write.

## 7. Integration

### 7.1 Jira Data Center

- **Personal access token** per person, header `Authorization: Bearer`. The token lives in an
  environment variable or in the operating system keychain; never in YAML, in the data repo, in logs
  or error messages. Input masked, "Test connection" via `/rest/api/2/myself`.
- Tickets via `/rest/api/2/search` with `fields=` (only required fields) and paging
  (`startAt`/`maxResults`); sprints via the Agile API; field names via `/rest/api/2/field`.
  Dependencies from issue links (type configurable, default "Blocks").
- All calls go through one function that allows only GET, plus exactly the one PUT for the
  label in step 5; a test enforces this.
- Visibility follows the person's permissions; tokens expire. Understandable messages
  on 401, 403 and TLS; "no result" never counts as "no work". The app stays fully
  usable without Jira.
- Cache only in the process, time-limited, separated by instance and account.
- Jira add-ons are not possible and are not required.

### 7.2 CSV import

Main path in step 1 and fallback when there is no network access: export from the advanced
Jira search ("all fields", without assignee and reporter). Column names follow the
Jira standard export ("Custom field (…)", "Benutzerdefiniertes Feld (…)", issue links as
"Inward issue link (Blocks)"). The column mapping uses the same field names as
`tracker.fields`.

### 7.3 Manual maintenance

Without a tracker, tickets and projects can be maintained directly in `tickets.yaml` and `projects.yaml`
(`kind: csv` without a file, or pure manual maintenance on the page). Everything else works
the same.

### 7.4 Other trackers (later)

The interface `TicketSource` delivers a neutral `Ticket`. For GitHub and GitLab the terms
map as follows:

| Term | Jira | GitHub | GitLab |
|---|---|---|---|
| Estimate | field (configurable) | label `estimate:<n>` or project field | weight |
| Sprint | sprint field | milestone | iteration or milestone |
| Project assignment | epic, component, label | label, milestone, project field | epic, label |
| Dependency | issue link | "blocked by" reference | blocking link |
| Refined | label | label | label |

These adapters are only built when a second integration is concretely pending; the interface
grows then, not before.

## 8. Presentation

One page **"Tickets"** (only with `features.tickets`), at the top a **filter** over products and
projects, individually deselectable; it applies to all parts of the page. Below:

1. **Project traffic light:** per project target date, target sprint, sprint of the last ticket, traffic light, number
   of tickets, open points (unestimated, too large, without project).
2. **Timeline:** all selected projects in one figure, sprints as columns, per project
   one bar from the first to the last sprint of its tickets, target date as a mark; colour by
   traffic light; in step 4 the range of the three variants as a lighter area.
3. **Sprint columns:** per future sprint one column with fill level (budget, used, free) and
   cards per ticket (key, short title, estimate, origin, project). Earmark and release
   via a select box; fixed points (real Jira sprint) are marked and cannot be moved.
4. **Refinement list:** per sprint the tickets to be refined with deadline.
5. **Not distributable:** unestimated, too large, cycle, without project.
6. **Import and maintenance:** import with preview, create and change projects, manual estimates.
7. **Report section** and proposal in the planning assistant (sums per product, step 4).

Timeline sketch (one bar per project, target date as `|`):

```
             S43      S44      S45      S46      S47      S48
Payment v2   ████████████████████████▌         |                 on track
Migration    ████████████████████████████████████████▌|          tight
Reporting             ████████████████████████████████████████▌  missed (target S46)
```

Sprint columns sketch (fill level and cards):

```
S44  Budget 21 · used 18 · free 3       S45  Budget 21 · used 20 · free 1
┌─────────────────────────────┐          ┌─────────────────────────────┐
│ ABC-123  Checkout API    5 R│ Payment  │ ABC-130  Refund          8 U│ Payment
│ ABC-125  Schema v2       8 R│ Migration│ ABC-131  Legacy data     5 R│ Migration
│ ABC-127  Export          5 M│ Reporting│ ABC-140  Dashboard       7 U│ Reporting
└─────────────────────────────┘          └─────────────────────────────┘
R = refined, U = rough (unrefined), M = own estimate      bold = fixed Jira sprint
```

Streamlit suffices for filter, tables, select boxes and the two charts; an interactive
planning surface (drag-and-drop) is not a goal.

## 9. Architecture

```
sprintforecast/
  core: capacity, forecast, analysis, calendar   (knows neither sources nor pre-planning)
  model.py      + Ticket, Project
  storage.py    + projects.yaml, tickets.yaml, preplan.yaml
  preplan.py    budgets, order, placement, project traffic light, refinement list, variants
  sources/      neutral ticket model, interface TicketSource, csv.py, jira.py
                (jira as an optional extra: sprintforecast[jira])
  web/page_scripts/tickets.py, report, cli tickets
```

- The core never imports from `sources/` or `preplan.py` (enforced by a test).
- With `features.tickets: false` none of it is loaded.
- The Jira adapter is an optional extra in the same repo, not a plugin: the code contains nothing
  instance-specific, a separate registration mechanism is not needed.
- Terminology: the share for pre-planning is called "Plannable share" in the display (since #106,
  formerly "Roadmap share"); the YAML key stays `roadmap_share`.

## 10. Implementation steps

Start on release 0.6.0, always from a fresh `main`. One small pull request (or a stack)
per step, in English, with tests and `locale_en.py` entries.

| Step | Content | Modules touched |
|---|---|---|
| **1 Model and distribution** | `Ticket`, `Project` in `model.py`; `projects.yaml`, `tickets.yaml`, `preplan.yaml` in `storage.py`; `features.tickets`; validation (rule language, cycles, target dates); `preplan.py`; CLI `tickets` with CSV import (preview, apply) and output of distribution, traffic light and refinement list | model, storage, validate, cli, settings, locale_en, docs |
| **2 Jira import** | `sources/jira.py` as an extra: read JQL, resolve field names, refined rule, assignment rules, preview, write to `tickets.yaml`; token from environment or keychain; GET only | sources/, settings, cli |
| **3 Page** | page "Tickets" (section 8) without variants (done in `web/tickets_view.py`); report section and planning-assistant proposal follow | web/ui, web/page_scripts, report, i18n |
| **4 Variants and apply** | three variants with `rough_factor`; range in the timeline; apply the sums per product as `preplanned` into the PO pre-planning | preplan, analysis, web/ui |
| **5 Label to Jira** | set `planned_for_<sprint_id>` and remove the old one, only on change, with preview; read labels on import; precedence from 6.6 | sources/jira, preplan, web/ui |

Implemented so far: steps 1 and 2 (model, distribution, CSV and Jira import) and the command-line
part of step 4 (`tickets` with the range of the three variants, `--variant`, and `--handover` for
the sums per sprint and product as `preplanned`). The page and the timeline range (step 3 and the
rest of step 4) and step 5 follow.

Step 3 starts only when nothing big is open on `web/ui.py`. Later candidates: GitHub
and GitLab adapters, epic roadmap from the projects, export of the distribution (CSV), drag-and-drop.

## 11. Tests

- Distribution: examples with expected result (order, dependencies with `gap` 0 and 1,
  budget limit, ticket too large, unestimated ticket, cycle, fixed points from `in_sprint` and
  `preplan.yaml`); property test: no sprint over budget, each ticket at most once,
  dependencies never after their successor.
- Project traffic light and refinement list per case; three variants with factor.
- Rule language: short form, `any`/`all`/`none`, nesting, `project_match_order`, contradictions,
  invalid rules.
- Refined detection with label, additional condition and "unclear".
- Import: one test per reconciliation case from 6.5; CSV with German and English column names.
- Jira: no real network calls in CI (`httpx.MockTransport` with recorded
  responses); field name resolution; GET only (and from step 5 exactly the label PUT); token and
  ticket data never in logs or error messages; one manually triggered test against a real
  instance.
- `features.tickets: false`: no page, no menu entry, no loaded module; the core
  imports nothing from `sources/` or `preplan.py`.
- AppTest for the "Tickets" page (filter, earmark, release, import preview).

## 12. Open points

- The default precedence of the project assignment "epic before component before label" is an assumption and
  is to be confirmed by the owner.
- A CSV export from the real instance as a test basis for step 1; until then, development targets the
  column names of the Jira standard export.
