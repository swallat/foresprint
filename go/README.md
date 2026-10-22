# Foresprint Go core

The 1.0 core of Foresprint, ported from Python (`src/foresprint`). One program, no Python at
the user's side. The window shell is Wails; this folder has the core, the command line and the
tests.

Status: the core and the command line are ported; the window (Wails) follows the design approval.

```
cd go
go test ./...          # includes the comparison with ../golden (Python reference results)
golangci-lint run ./...
go build ./cmd/foresprint
```

The module path is `github.com/swallat/foresprint` with `go.mod` in this folder; when the Python
sources are removed, `go.mod` moves to the repository root and nothing else changes.

## Packages

| Package | Purpose |
|---|---|
| `internal/golden` | Loads the references of `../golden` and compares results with them. |
| `internal/pyrand` | `random.Random` of Python (Mersenne Twister, seeding, `random()`, `getrandbits`, `choice`): the Monte Carlo draws are identical for the same seed. |
| `internal/holidays` | Holidays and weekends of every country and region of the Python `holidays` library, from embedded data (see below). |
| `internal/i18n` | Texts: English source texts, one JSON file per language in `data/` (see below). |
| `internal/config` | `settings.json` of the user (language, theme, data folders); same file and format as the Python version. |
| `internal/cli` | The command line: commands are subcommands of the one program (cobra), plain output. |
| `internal/pytext` | `str.splitlines` and other places where Python's text functions differ from Go's. |
| `internal/yamlmerge` | Three-way merge of YAML value trees at key level (lists with `id`, forecasts by timestamp). Works on the tree of `value.go`, not on text. |
| `internal/git` | The `git` program: finding it, calls with a time limit that can be aborted, recognising Git's messages (`Classify`, kinds, hints), checking server addresses, connection check, changes, commit, tags, create and clone a data repository. |
| `internal/gittest` | Helpers for tests with real repositories (bare server, clones). Only imported by tests. |
| `internal/difflib` | Python's `difflib` (SequenceMatcher, grouped opcodes, `unified_diff`) with identical output. |
| `internal/gitsync` | State, fetch, "Save and share" (commit, merge at key level, validate, push with retry, merge request instead of push), conflicts and their decisions, remote server setup, branches, rescue after a detached HEAD. The YAML codec (`yamlx`) and the data check (`validate.CheckFolder`) are the defaults; `SetCodec` and `SetValidator` replace them in tests. |
| `internal/datasvc` | The "Data" area of the window: status and chip, Save, Refresh, conflicts, history and restore, labels, Settings > Storage. Neutral words, plain structs with JSON names and no context, so the window binds the `Store` methods as they are (flows D1 to D6). |
| `internal/githistory` | Discard (with trash and rollback), history, restore a version, take back a commit, tags (also on the server). |
| `internal/signin` | Token sign-in over Git's credential helper (`git credential approve/reject`); the token is never stored or shown by the program. |
| `internal/pymath` | The arithmetic of Python the results depend on: the compensated `sum()` of floats (Python 3.12+), `math.fsum`, `statistics.median`/`fmean`, `round`, and the number formats `{:,.2f}` and `{:g}`. A sum that has to match Python is calculated with these, not with a loop. |
| `internal/calendar` | Sprint IDs and the following sprints, workweeks, workdays, holidays of a country and region (`calendar.py`). |
| `internal/engine` | Rounding, rolling average, trend modes, `Compute` (`engine.py`). |
| `internal/capacity` | Capacity per person and sprint, expected absence rate (`capacity.py`). |
| `internal/forecast` | Timeline, capacity source, `Build`, Planning inputs, freezing the plan (`forecast.py`). |
| `internal/analysis` | Ranges, focus factor, buffer hint, horizon, Monte Carlo completion (`analysis.py`). |
| `internal/formulas` | The calculation path of every figure: steps and explanations as texts (`formulas.py`). |
| `internal/textfmt` | Number format of the language, capacity rounding, Markdown code spans of external text (the helpers of `report.py` and `git.py` the formulas need). |
| `internal/products` | Distribution of the sprint quantity over the products: standard shares, rows and totals, production state, totals per PO, balance (`products.py`). |
| `internal/planning` | New in 1.0 (no Python original): plannable amount and small stuff, production demand against production time (traffic light), points ↔ person days. Formulas of flows.md, decisions 19 and 20. |
| `internal/coretest` | Test helper: loads the golden team folders with `storage` and turns results into the JSON form of the Python references (snake case keys, dates as YYYY-MM-DD). |

| `internal/sources` | Ticket sources: CSV export of Jira, Jira Data Center client (REST v2, token from the environment or the keychain), field resolution, field suggestions, the one label write. Python-compatible CSV reader, float parsing and `difflib`; compared with `golden/expected/sources`. |
| `internal/ticketimport` | Ticket import: planning what a fetch changes (new, changed, removed, earmarks, projects, sprint end dates), applying it, and planning the `planned_for_*` label writes. Takes the sprint ends through a small interface until the forecast is wired in; compared with `golden/expected/ticketimport`. |
| `internal/excel` | Excel output of a team: real formulas with the engine's cached results, the data sheets the import reads, charts. Built with excelize; the types of cached results and the chart extension are corrected in the file. Compared with `golden/expected/excel` (cells read back from the Python workbook). Also the Excel import (own xlsx reader with openpyxl's value semantics, plan and apply), compared with `golden/expected/excel_import` (85 workbooks: documents, error texts, changes, written files). |
| `internal/sprintwrite` | New in 1.0: optional write-back of the planned sprint to the tracker (plan with preview and per-ticket opt-out, apply, undo; decision 10). Needs `JiraSource.EnableSprintWrite`; only the two Agile requests "issues to sprint" and "issues to backlog" are allowed. |
| `internal/workpackages` | New in 1.0: work packages kept in Foresprint (`arbeitspakete.yaml`): keys like AP-424, ranks, import from a CSV or Excel table (`excel.Table`), merge with the existing packages. |
| `internal/model` | The data types (team, people, products, sprints, ticket pre-planning), port of `model.py`. Optional values are pointers, dates are UTC midnight `time.Time`, maps with a file order are `OrderedMap`. |
| `cmd/foresprint` | The program. |

## Data format in 1.0

Everything 1.0 adds is optional and written only when it has a value, so a 0.8 file reads and
writes back unchanged (the golden round trips prove it).

| File | Addition |
| --- | --- |
| `team.yaml` | `tracker.kind: packages` (work packages kept in Foresprint; no tickets = `features.tickets` off); `features.projects` (read `projects.yaml` without tickets); `sprint.naming` (list of `{from, pattern}`), `sprint.pro_forma` (names); `estimation: {factor, changes: [{from, unit, factor}]}`; tracker: more `fields` (status, acceptance, product, project, refined, production), `production_label`, `production_rules` (`{match, share}`), `write_sprint`, `removed_target` (backlog, pro_forma, next), `package_prefix` |
| `people.yaml` | `kind: guest` or `external` (member is not written) |
| `abwesenheiten.yaml` | `absences: {<person>: [{from, to, confirmed}]}`, dates only, never a reason |
| `projects.yaml` | `products` (list; with one product the 0.8 key `product` stays), `start`, `end`, `state` (finished, cancelled), `open_scope`, `milestones`, `contingent: {total, per_month}` |
| `tickets.yaml` / `arbeitspakete.yaml` | work package fields `description`, `acceptance`, `assignee`, `product`, `subtasks`, `comments`; `arbeitspakete.yaml` has the format of `tickets.yaml` and replaces it for `kind: packages` |
| `preplan.yaml` | `production` (`{ticket, share, note}`), `overrides` (`{ticket, product, project, daily}`) |
| `sprints/<id>.yaml` | `name`, `committed_tickets`, `carry` (`{ticket, rest, target}`), `rest_next`, `projects` (values per project, no tickets); prognoses: `label`, `finish`, `carry`, `rest_next` |

`model.FormatSprintName` fills a naming pattern ({JJJJ} {JJ} {NN} {N} {LFD} {Q} {MM} {KW}).
`tracker.kind` accepts `packages`, so the message of the check lists it (known deviation from
the Python reference).

## Texts

`internal/i18n/data/<code>.json` maps English source texts to the translation; a text without
entry shows in English. `de.json` is generated from the Python table by `scripts/gen_locales.py`
(CI checks it) until Python is removed. Texts that only exist in the Go core go to
`<code>.<name>.json` (for example `de.cli.json`) and are merged. Another language is another
file, nothing else changes. Language: `FORESPRINT_LANG` > saved setting > English.
`i18n.T` keeps rich markup of the Python texts, `i18n.P` (command line) removes it before the
values are filled in.

## Command line

A command is a file in `internal/cli` that calls `Register` in an `init` function and returns a
`*cobra.Command`; global options (`--data`, `--as-of`) and the streams come with the `Env`.
Exit codes: 0 success, 1 the command failed (`cli.Failf`), 2 wrong use. Shell completion:
`foresprint completion bash|zsh|fish|powershell`; `cli.TeamNames` and `cli.SprintIDs` complete
team and sprint arguments.

The command names and options are those of the Python version. Output is plain text (tables
and lines) instead of Python's panels; the questions of the guided commands come in the same
order and write the same files.

| Group | Commands |
|---|---|
| Set up | `init`, `settings`, `data-dir`, `language` |
| Maintain data | `people`, `absences`, `product-list`, `sprints`, `rename-sprint` |
| Spreadsheet | `excel` (export), `excel-import FILE` (preview, `--apply` writes) |
| Sprint workflow | `planning`, `review`, `products` (`--preplanning`) |
| Results | `forecast` (`--explain`), `capacity`, `analysis`, `report`, `check` |
| Tickets | `tickets` (`--import`, `--fetch`, `--handover`, `--write-labels`, `--test-connection`, `--set-token`; `--apply` writes) |
| Help | `help [workflow\|terms\|fields\|team\|commands]`, `version`, `completion` |

Try it with the demo team (copy it first, the guided commands write into the folder):

```
cp -r ../examples/teams /tmp/demo-data
foresprint --data /tmp/demo-data --as-of 2026-10-15 forecast demo
foresprint --data /tmp/demo-data --as-of 2026-10-15 absences demo
```

Not ported on purpose: `web`, `shortcut` and `update` (the window and installer replace them).
Settings and their texts are in `internal/settings`; the help texts come from
`internal/guide/data/guide.json`, generated by `scripts/gen_guide.py` (CI checks it).

### Testing the guided commands

`scripts/golden_ext/cli_flows.py` lists scenarios: arguments, typed answers and optional seed
files. Each one runs the Python command on a copy of `examples/teams` and records the exit code
and every file written or deleted (`golden/expected/cliflows`). `internal/cli/flows_test.go`
replays them against the Go command and compares the files byte for byte. A new command or
option gets scenarios there; regenerate with `uv run python scripts/golden.py`. Never run
exploratory Python commands with `--data examples/teams`, they write into the demo data.

## Holiday data

`internal/holidays/data/holidays.zip` is generated by `scripts/gen_holidays.py` from the Python
library `holidays` (all countries and regions, 2001-2050, names in German and English). It is
committed so that building needs no Python; CI fails if it is not what the locked `holidays`
version gives (`gen_holidays.py --check`).

- At every release the release workflow regenerates it with the newest `holidays` and attaches it
  to the release page (artifact `holidays-data`); the Go build puts it at the path above before
  `go build`.
- The workflow `holidays-update.yml` runs monthly (from the default branch, see its header),
  upgrades `holidays` in `uv.lock`, regenerates the file and the dependent golden files and opens
  a pull request that lists the changed countries.
- The golden digests of `../golden` belong to the committed file. A build that swaps in newer
  data must not run the holiday golden tests against it (or regenerate `golden/` with the same
  library version first).
- Another language: add it to `LANGUAGES` in the generator. The format has one name column per
  language; readers look the column up by code.
- Years outside 2001-2050 have no holidays (`holidays.Covers`). Loading at run time is not part
  of 1.0.

## Rules for the port

- Python is the reference. Every ported function gets a golden test; see `../golden/README.md`.
- Rounding: Python's `round` rounds half to even, Go's `math.Round` half away from zero. Use the
  helpers of the engine (`round_down`, `round_half_up` are explicit in Python) and test the limits.
- arm64 may fuse multiply and add. Wrap products in `float64(...)` where the result must match
  Python in the last digits.
- Dates are calendar dates, not instants: no time zone arithmetic. Where `time.Time` is used it is
  UTC midnight.
- YAML is written byte for byte like PyYAML `safe_dump(width=100, sort_keys=False,
  allow_unicode=True)`. `golden/expected/yaml` has the cases, `yaml-messy` the awkward ones.
- Texts for users are English in code and files; German comes from the catalog.

## Where Go differs from Python on purpose

- Sprint IDs are read with ASCII digits only (`2026.7`); Python's `int()` also takes other
  scripts' digits. IDs are file names, so this is no loss; `scripts/golden_ext/calendar_ids.py`
  leaves such IDs out of the reference.
- Years outside 2001-2050 have no holidays (see Holiday data); Python's library calculates any
  year.
- A sprint's `note` is always text in Go; Python keeps a bare number as a number
  (`sprint/note-number` in the golden known differences).
- Files are written with mode 0644; there is no team cache; integers beyond 64 bits in YAML
  are refused with an error. Configuration is handled by `internal/config`.
- An error is a typed value with a `Message(lang)` for the user text, not an exception with a
  translated string.

## Port plan

Six parallel steps after phase 0 (details in the decision paper of the project):

1. Model, storage, YAML writer.
2. Calendar, capacity, forecast, analysis, formulas.
3. Check, pre-planning, rules, protocol, report, diff.
4. Git, sharing, merge.
5. Jira, CSV, tickets, Excel.
6. Command line, texts, settings.
