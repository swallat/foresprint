# Golden files

Reference results of the Python core, for the Go port (`go/`). The Go core has to produce the
same numbers, the same dates, the same texts and, for YAML, the same bytes.

Everything below `inputs/` and `expected/` is generated. Do not edit it by hand:

```
uv run python scripts/golden.py            # rewrite golden/
uv run python scripts/golden.py --check    # CI: fails if golden/ differs from the Python core
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
| `expected/calendar/*.json` | Workdays and weekends, sprint ids, country list, holidays (a sample with names, plus a digest of every calendar of the library). |

JSON files are written with Python's `json` (floats as `repr`, so they round-trip exactly). A
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
change the Python side or the reference in the same pull request as the Go code and say why.
Never loosen a comparison to make a test pass.

## Adding references for another module

Copy `scripts/golden_ext/_template.py` to `scripts/golden_ext/<module>.py`. Each module owns its
sub-folder `expected/<module>/`, so the porting threads do not edit the same files.

## Python is the reference, not the target

On `main` Python only gets bug fixes from now on. A bug fix there changes the references: run
`scripts/golden.py` and review the diff of `golden/` in the same pull request (CI checks it).
