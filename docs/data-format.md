# Data format

All data lives in plain YAML files inside the data folder, one subfolder per team. Keys and
comments are always English, regardless of the UI language; only the report `FORECAST.md` and
the minutes follow the configured language. The layout of a data repository is described in
[Data repository](data-repository.md).

```
teams/
└─ team-a/
   ├─ team.yaml                  # settings
   ├─ people.yaml                # people and memberships
   ├─ products.yaml              # optional
   ├─ sprints/2026.20.yaml ...   # one file per sprint
   ├─ FORECAST.md                # generated report
   └─ protokolle/                # generated minutes of planning meetings
```

## Features

Not every team needs everything. Four features can be switched on independently (Settings page
or the `features` section in `team.yaml`) and are **off for new teams**:

| Feature (`features.<name>`) | Effect when on | When off |
|---|---|---|
| `products`: product distribution | product list, PO pre-planning, planning and done per product, default distribution, balance | these pages and inputs are omitted |
| `po`: PO assignment | PO column per product, totals per PO (useful only together with `products`) | no PO column, no totals per PO |
| `production`: production access | mark people as authorized, amount with production access in planning/review (per product, or per sprint without product distribution), bottleneck note | no marking, no inputs, no note |
| `tickets`: ticket pre-planning | tickets from the tracker (Jira or CSV export) are assigned to projects and distributed over future sprints: project list with target dates, earmarks, project traffic light, refinement list (`projects.yaml`, `tickets.yaml`, `preplan.yaml`, section `tracker` in `team.yaml`) | the three files are not read, there is no page and no command for it |

Switching a feature off deletes nothing: values already recorded stay in the files and reappear
as soon as the feature is switched on again. **Older `team.yaml` files without `features`**
remain usable as before: while loading, `products` counts as on if products are recorded, `po`
if a product has a PO, and `production` if a person is marked as authorized; the section is
written the next time the settings are saved.

## `team.yaml`

Settings; everything is optional except `name`, and `sprintforecast settings TEAM` changes them
with guidance:

```yaml
name: Team A
unit: PT                    # PT or SP (capacity is always PT)
features:                   # optional features, all false for new teams
  products: false           # product distribution
  po: false                 # PO assignment
  production: false         # production access
  tickets: false            # ticket pre-planning (see below)
sprint:
  length_days: 14
  numbering: yearly         # 2026.1, 2026.2 ... | sequential: 1, 2, 3 ...
  first: {id: '2026.20', start: 2026-10-14}   # sprint running now or starting next; only needed while no sprint file exists
forecast:
  reference_capacity: 67    # reference for the normalized velocity
  window: 5                 # moving average
  roadmap_share: 0.8        # plannable share of the Forecast PLAN (rest: small items)
  rounding: 1               # Forecast PLAN is rounded down (capacity: unrounded internally)
  trend_mode: flat          # flat (default) | classic | linear; the latter two extrapolate noise
  horizon: 3                # future sprints in the forecast
  product_basis: plan       # default per product from: plan (Forecast PLAN) | roadmap
capacity:
  overhead_share: 0.0       # flat deduction for Scrum ceremonies
  overhead_days: 1          # optional: fixed deduction in PD per person and sprint (x FTE);
                            # replaces overhead_share (the same deduction in two units, not added)
  absence_history: 4        # default 4: reduce the capacity of sprints with unknown absences by
                            # the average absences of the last 4 sprints with confirmed absences
                            # (0 = no estimate, then no deduction)
  country: DE               # optional (default DE): ISO country code for holidays and weekend
  region: NW                # region within the country (state, province), e.g. NW, CA, ON
  workweek: auto            # optional: auto (as in the country) | mon-fri | sun-thu | mon-sat
  rounding: 1               # optional: decimals of the displayed capacity and of the capacity
                            # frozen in the review (rounded half up); the forecast is unrounded
tracker:                    # only with features.tickets, see "Ticket pre-planning" below
  kind: csv
```

`PT` is the German abbreviation for person days (PD) and is the value stored in the files.

## `people.yaml`

People are never deleted; only their memberships are ended:

```yaml
people:
- id: ben
  name: Ben
  region: BY                # optional, otherwise the team's region
  country: AT               # optional: a different country for this person (holidays, weekend)
  workweek: mon,tue,wed,thu # optional: own working week, e.g. a 4-day week (otherwise country/team)
  production_access: true   # optional: may work on tickets that need production access
  memberships:
  - {from: 2025-01-01, to: 2026-05-31, fte: 1}
  - {from: 2026-06-01, to: null, fte: 0.5}
```

**FTE and working week:** `fte` is the share of the **person's working days** (1 = all of their
working days). The working week (`workweek`) defines which weekdays those are. Model part-time
work only **once**, otherwise it is deducted twice. Example with 10 working days (Mon-Fri) in the
sprint:

| Entry | Capacity |
|---|---|
| `workweek: mon-fri` (default), `fte: 0.8` | 10 x 0.8 = **8 PD** |
| `workweek: mon,tue,wed,thu`, `fte: 1` | 8 working days x 1 = **8 PD** |
| `workweek: mon,tue,wed,thu`, `fte: 0.8` (counted twice!) | 8 x 0.8 = 6.4 PD |
| `workweek: mon-fri`, `fte: 0.5` (half days) | **5 PD** |

## `products.yaml` (optional)

Never delete products; end them with `to:` instead:

```yaml
products:
- {id: webshop, name: Webshop, po: Alex, from: null, to: null}
- {id: partner, name: Partner portal, share: 0.1}  # 10 % of the capacity by agreement
- {id: portal, name: Customer portal, po: Bea, from: 2026-09-02, to: null}
- {id: legacy, name: Legacy system, po: Bea, from: null, to: 2026-09-15}
```

## Ticket pre-planning (optional)

With `features.tickets` on, three more files per team describe the tickets of the tracker and
the PO's plan for them (design: [ticket-planning.md](design/ticket-planning.md)). The
distribution over future sprints is never stored; it is recalculated from these files and the
forecast on every load.

### `team.yaml`, section `tracker:`

Where the tickets come from and how they are interpreted. All values are examples; field names
are the **display names** of the tracker (as in the header of a Jira CSV export):

```yaml
tracker:
  kind: csv                      # csv | jira (see below)
  fields:
    estimate: Story Points       # column "Custom field (Story Points)" in the export
    remaining: Remaining Points  # optional; without it the estimate is used
    epic: Epic Link              # optional; without it the "Parent" column is used
  planning_uses: remaining       # remaining (if filled, otherwise estimate) | estimate
  refined_label: Refined         # label that marks a refined ticket
  refined_also_if:               # counts as refined even without the label (same rule language
    any:                         # as match: below)
      - in_sprint: [true]
      - none:
          - status: [To Do]
  project_match_order: [epic, component, label]   # which match wins between two projects
  dependency_gap: 1              # 1 = a dependent ticket goes at least one sprint later, 0 = same
  budget_basis: roadmap_share    # roadmap_share (PLAN × roadmap_share) | plan (whole PLAN)
  rough_factor: 1.5              # only the conservative variant multiplies rough estimates (and
                                 # those of tickets with unclear refined status) by it; the
                                 # median and optimistic variants count them as they are
  sprint_names:                  # optional: tracker sprint name → sprint id of the tool, only when
    Sprint 42: '2026.21'         # the names differ
```

**Jira (`kind: jira`).** `sprintforecast tickets TEAM --fetch` reads the tickets straight from
Jira Data Center (setup: [jira.md](jira.md)); the CSV import stays available as an offline
fallback. Additional keys:

```yaml
tracker:
  kind: jira
  base_url: https://jira.example.org    # http or https; with a context path: https://host/jira
  query: 'project = ABC AND resolution = Unresolved AND issuetype not in subTaskIssueTypes() ORDER BY Rank'   # JQL; sub-tasks would be counted twice
  fields:
    estimate: Story Points       # display names of the instance, as in the Jira UI; the tool
    remaining: Remaining Points  # resolves them to customfield_… ids (GET /rest/api/2/field)
    epic: Epic Link              # "Parent" (or "Übergeordnet") takes the parent issue as epic
  link_type: Blocks              # optional, default Blocks: issue link type whose inward side
                                 # ("is blocked by") becomes depends_on
```

- `base_url` and `query` are required (error otherwise); the address must not contain credentials, parameters (`?…`) or a fragment (`#…`); a missing `fields.estimate` is a warning.
  Plain `http` is accepted with a warning (the token would travel unencrypted); credentials in the
  address are an error.
- A field name that does not exist or exists twice in the instance stops the import with a
  message that names the candidates' ids; write the id (`customfield_10016`) instead of the name
  to disambiguate. The sprint, rank and epic link fields are found by their schema, not by their
  (localized) name.
- Which sprint counts for a ticket in several sprints: the active one, else the first future one,
  else the last one listed. It is mapped to a sprint id like a CSV sprint name (`sprint_names`).
- `link_type` is the only Jira-specific setting besides address and query. It is written only
  when it differs from `Blocks`.
- **No secrets in this file.** A key such as `token`, `password` or `secret` in the `tracker`
  section is an error (`check` reports it; the value is never shown). The token lives in the
  environment variable `SPRINTFORECAST_JIRA_TOKEN` or in the operating system keychain.

### `projects.yaml`

The PO's projects (not Jira projects): each one has a target date, a product (only with
`features.products`), a priority and an assignment rule under `match:`. A ticket belongs to the
project whose rule it fulfils; when two projects match, `project_match_order` decides by the
source of the match, and two matches via the same source leave the ticket unassigned.

```yaml
schema: 1
projects:
- id: payment-v2
  name: Payment processing v2
  product: shop
  target: 2027-03-31
  priority: 1                    # lower = more important when target dates are equal
  budget_basis: plan             # optional, overrides tracker.budget_basis
  match:                         # short form: the leaves are OR-combined
    epic: [ABC-100, ABC-101]
    label: [payment]
- id: migration
  name: Database migration
  target: 2027-01-15
  match:                         # long form: any (OR), all (AND), none (exclusion), nestable
    all:
    - component: [Database]
    - none:
      - label: [maintenance, hotfix]
```

Rule sources: `epic`, `component`, `label`, `status`, `issue_type`, `in_sprint` (`true`,
`false` or a sprint id). Validation rejects empty lists, unknown sources and short and long form
in the same `match:`.

### `tickets.yaml`

The state of the last import, written by `sprintforecast tickets TEAM --import FILE --apply` or
`--fetch --apply`;
not meant to be edited by hand:

```yaml
schema: 1
imported: 2026-10-19 14:00:00
source: export.csv             # file name of the CSV, or "jira <host>" after --fetch
tickets:
- key: ABC-123
  title: Checkout form
  status: In Progress
  issue_type: Story
  estimate: 5.0
  remaining: 3.0
  estimate_source: refined       # refined | rough | none (manual comes from preplan.yaml)
  in_sprint: '2026.21'           # real sprint according to the tracker, as sprint id; only a
                                 # current or future sprint (a closed one is not the ticket's sprint)
  rank: '0|i000kf:'              # rank of the tracker, compared as text (quote it: ends in a colon)
  epic: ABC-100
  labels: [payment, Refined]
  components: [Checkout]
  depends_on: [ABC-120]          # must be finished first ("is blocked by")
  project: payment-v2
```

A ticket carried over from a closed sprint counts as not being in a sprint (`in_sprint` is
empty, `sprint_name` keeps the name): the `in_sprint` rule source sees only a current or future
tracker sprint.

### `preplan.yaml`

Manual earmarks of the PO (ticket → future sprint) and own estimates for tickets without a
usable estimate; each ticket at most once per list:

```yaml
schema: 1
earmarks:
- {ticket: ABC-130, sprint: '2026.23', note: agreed with marketing}
estimates:
- {ticket: ABC-140, estimate: 8, note: rough guess until refinement}
```

An earmark is dropped by the next import when the tracker puts the ticket into a current or
future sprint, or when the ticket is done; it stays (with a warning) when the ticket is missing
from the import. An earmark for a sprint that is over is ignored by the distribution, reported by
the check and dropped by the next import.

### Variants, range and handover to the PO pre-planning

`sprintforecast tickets TEAM` distributes the tickets three times; the variants differ only in the
plan per future sprint (the budget is its share, see the design):

| Variant | Plan per sprint | Tickets |
|---|---|---|
| `median` (shown) | the **Forecast PLAN** exactly as the forecast shows it (not a separately computed median) | sizes as they are |
| `conservative` | lowest normalized velocity of the history (like the range in `analysis`) × capacity of the sprint | rough estimates, and estimates of tickets with unclear refined status, × `rough_factor`; refined and manual estimates are not inflated |
| `optimistic` | highest normalized velocity of the history × capacity of the sprint | sizes as they are |

The project table shows the last sprint of every variant and the traffic light of the median
variant; when the lights differ, the best and the worst one follow in brackets
(`tight (on track – missed)`). A project counts as on track in the range sense only when all three
variants are on track. Greedy placement is not monotone across variants, so earliest and latest
are the minimum and maximum over the variants. With fewer than two sprints with velocity there is
no range: only the median is shown, with a hint. `--variant median|conservative|optimistic` shows
the sprint table, the refinement list and the not-distributable list of that variant instead of
the median.

`sprintforecast tickets TEAM --handover` proposes the sums of the tickets per future sprint and
product (median variant: distributed tickets, earmarks and tickets in a tracker sprint, with the
sizes the distribution used) as `preplanned` of the sprint (`products:` below), rounded to the
team's `forecast.rounding`. It needs `features.products` and shows sprint, product, current value
and proposal without writing. With `--apply` it writes only where nothing is entered yet (a value
that equals the proposal stays untouched); a value the PO entered is never replaced unless
`--overwrite` is given. A sprint that exists only in the calendar gets its file when there is
something to write. `--sprints N` limits the future sprints (default 6), `--commit` commits the
changed sprint files.

## `sprints/<id>.yaml`

Empty fields are `null` (= not specified):

```yaml
id: '2026.21'               # in quotes!
start: 2026-10-14
end: 2026-10-28             # = start of the next sprint (exclusive); last day is 27 Oct
absences: {ben: 3, cem: 5}  # plannable absences (working days), without public holidays
capacity: null              # frozen in the review; set manually only without a people list
forecast_ist: 10
velocity: null
scope_creep: null           # share, 0.3 = 30 %
planning: {carryover: 0.25, backlog: 9.48, corrections: [1.5]}
forecast_plan: 10.1         # Forecast PLAN at planning (frozen), optional
absence_state: confirmed   # absence state: unknown | expected | confirmed. "confirmed" also
                           # without entries ("nobody absent", confirmed explicitly); "unknown":
                           # capacity from calendar and people, absences estimated from history.
                           # Older files without this field stay readable (the state is derived:
                           # entries, absences_confirmed: true or an already planned or reviewed
                           # sprint count as confirmed).
absences_confirmed: true   # only for older program versions; written together with "confirmed"
expected_absences: {anna: 2}   # PO pre-planning: announced absences (forecast); affect capacity
                           # and Forecast PLAN until the absences are confirmed
not_done: 1.5              # review, optional: amount that was not finished
additional_done: 0.5       # review, optional: done in addition to the commitment
                           # (velocity = commitment - not done + additionally done)
prognoses:                 # PO pre-planning: the team's forecasts for this open sprint
- at: 2026-10-16 09:30:00
  comment: Forecast from the daily   # where the assumption comes from
  forecast_ist: 10
  not_done: 2
  additional_done: 0.5
  expected_done: 8.5
  target: '2026.22'        # target sprint of the pre-planning
  plan: 9.9                # Forecast PLAN of the target sprint under this assumption
  preplanned: {webshop: 4}
products:                   # optional, per product ID
  webshop: {preplanned: 4, planned: 4.5, done: 4, production_planned: 1, production_done: 0.5}
                            # production_*: of which tickets with production access (optional)
production_planned: 1       # without product distribution (features.products off): amount with
production_done: 0.5        # production access planned or done, per sprint
```

The state "expected" in the file is shown as "announced" in the UI.

## `FORECAST.md`

`sprintforecast report [TEAM]` writes `teams/<team>/FORECAST.md`: a table of the last and the
upcoming sprints plus a Mermaid chart, in the configured UI language, so that it renders in the
web UI of GitHub or GitLab. The report ends with a section "Supplementary: range" from the
[analyses](calculation.md#supplementary-analyses). The template's workflow
`forecast.yml` regenerates the report on every push (see [Data repository](data-repository.md)).

## Minutes

Every save of a planning meeting (PO pre-planning, planning, review) in the web UI writes a
Markdown file `protokolle/<sprint>-<meeting>-<date>-<time>.md` in the team's folder; older versions
stay readable. Every save of a planning step (absences, scheduling, commitment) writes a new,
complete planning minute with the sections "Absences", "Scheduling" and "Commitment"; each
recorded section carries its own "As of" time (unchanged sections keep the earlier one), and steps
not yet saved read "not yet recorded". If a meeting becomes void (for example when a frozen Forecast PLAN is released), its
previous minutes are renamed to `..._obsolet_<date>-<time>.md`. The minutes are committed with the
data like every other file.
