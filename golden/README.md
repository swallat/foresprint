# Golden files

Reference results of the Python version 0.8, for the Go core (`go/`). The Go core has to
produce the same numbers, the same dates, the same texts and, for YAML, the same bytes.

The files below `inputs/` and `expected/` are **frozen**: they were generated once from the
Python core (branch `main`, version 0.8.0) and are now ordinary test data, committed and
edited like code. There is no generator and no Python in this branch any more. If a result
changes on purpose, change the file in the same pull request as the Go code and say why in the
description; never loosen a comparison to make a test pass.

The one exception are the calendar files that depend on the version of the `holidays`
library (`expected/calendar/countries.json`, `holidays-sample.json`, `holidays-digest.json`):

```
uv run scripts/gen_holidays.py --golden           # rewrite them (the monthly workflow does)
uv run scripts/gen_holidays.py --golden --check   # compare only
```

## Layout

| Path | Content |
|---|---|
| `inputs/<case>/<team>/` | Synthetic team folders (YAML, as Foresprint writes them). The demo team is read from `examples/teams/demo`. |
| `expected/manifest.json` | The cases: name, folder, team, `today` (the date every result is calculated for). |
| `expected/cases/<case>/forecast.json` | `build_forecast`: every sprint with all metrics, averages, trends, plan, source of the capacity. |
| `.../capacity.json` | Capacity breakdown per person and sprint (teams with a people list). |
| `.../horizon.json` | Analysis: normalized history, bands, focus factor, buffer hint, horizon sprints. |
| `.../completion.json` | Monte Carlo completion with fixed seeds and run counts. |
| `.../preplan.json` | Ticket distribution (median, conservative, optimistic), project ranges, hand-over rows. |
| `.../check.json` | Findings of the data check (texts in English). |
| `expected/yaml/<case>.json` | YAML round trip: load, save again. Per file `identical` or not. |
| `expected/yaml/<case>/<file>` | The bytes Python writes for files that change on a round trip. |
| `expected/rng/streams.json` | Streams of `random.Random(seed)`: `random()`, `getrandbits(k)`, `_randbelow(n)`, `choice`. |
| `expected/engine/cases.json` | `engine`: rounding limits, rolling average, gaps, every trend mode on hand-made series, `compute` with gaps and plannings. |
| `expected/pymath/cases.json` | Python's `sum`, `fsum`, `median`, `fmean`, `round` and number formats (the Go port must match to the last bit). |
| `expected/formulas/<case>.json` | The calculation path of every sprint: steps, plain and structured explanation (English). `formulas-de/` has the German texts of four cases. |
| `expected/forecast_api/*.json` | Current, upcoming and history entries, default sprint per purpose, sprint lookups, Planning inputs, freezing the plan, calendar error texts. |
| `expected/products/*.json` | Product distribution of every sprint (rows, totals, production state, totals per PO), plan views, the balance over all sprints and the last three, standard shares for edge cases, labels, footnote. |
| `expected/textfmt/cases.json` | Number formats in both languages, Markdown code spans of awkward text, the absence notes. |
| `expected/calendar/ids.json`, `workweeks.json` | Odd sprint IDs and workweek values in every spelling. |
| `expected/calendar/*.json` | Workdays and weekends, sprint ids, country list, holidays (a sample with names, plus a digest of every calendar of the library). |

JSON files were written with Python's `json` (floats as `repr`, so they round-trip exactly). A
dictionary key that was `None` in Python is `"(none)"`.

## Cases

`demo` (the example team), `trend-flat|linear|classic` (trend modes, gaps, no people list),
`thin` (fewer sprints than the window), `people-days|people-share` (own countries, workweeks,
FTE changes, all absence states, year change), `tickets-simple|tickets-products` (distribution
with and without products, rules, dependencies, cycles, earmarks, estimates), `yaml-messy`
(hand-written files: comments, quoting, flow style, `5` vs `5.0`, `1.0e+1`).

All teams are invented. Never add real team data here.

## Using the references in Go

`go/internal/golden` loads them and compares with a small tolerance for floating point numbers
(`golden.Load`, `golden.Compare`, `golden.Cases`). Example: `go/internal/pyrand`.

A deliberate difference from Python (a bug fixed in the port, a changed rounding) is a decision:
change the reference in the same pull request as the Go code and say why.

## Adding references

New code gets ordinary Go tests with their expected values in the test or in a file next to it.
Add a case to this folder only for behavior that exists in version 0.8 as well.
