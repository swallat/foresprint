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

Not every team needs everything. Three features can be switched on independently (Settings page
or the `features` section in `team.yaml`) and are **off for new teams**:

| Feature (`features....`) | Effect when on | When off |
|---|---|---|
| `products`: product distribution | product list, PO pre-planning, planning and done per product, default distribution, balance | these pages and inputs are omitted |
| `po`: PO assignment | PO column per product, totals per PO (useful only together with `products`) | no PO column, no totals per PO |
| `production`: production access | mark people as authorized, amount with production access in planning/review (per product, or per sprint without product distribution), bottleneck note | no marking, no inputs, no note |

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
sprint:
  length_days: 14
  numbering: yearly         # 2026.1, 2026.2 ... | sequential: 1, 2, 3 ...
  first: {id: '2026.20', start: 2026-10-14}   # only needed while no sprint file exists
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
Markdown file `teams/<team>/protokolle/<sprint>-<meeting>-<date>-<time>.md`; older versions stay
readable. If a meeting becomes void (for example when a frozen Forecast PLAN is released), its
previous minutes are renamed to `..._obsolet_<date>-<time>.md`. The minutes are committed with the
data like every other file.
