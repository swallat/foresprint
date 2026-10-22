# Command line and configuration

The web UI and the command line read and write the same files. This page lists every command,
how the data directory is found, the settings and the environment variables.

## Data directory and reference date

**Data directory:** `--data PATH`, otherwise the environment variable `FORESPRINT_DATA`,
otherwise the **current directory** if it contains teams, otherwise the **remembered data
folder** (web UI: *Data folder* page; command line: `foresprint data-dir PATH`). Teams are
subfolders with a `team.yaml`; if a directory has none but a subfolder `teams` with teams, that
one is used. If the web UI finds no data folder, it guides you through choosing, creating or
cloning one. `--as-of DATE` (or `FORESPRINT_AS_OF`) sets the date that counts as "today",
for retrospectives and tests.

## Commands at a glance

The 1.0 program (Go, see [go/README.md](../go/README.md)) has the same command names and
options. It prints plain text instead of panels, has no `web`, `shortcut` or `update`
(the window and the installer take over), and writes the same files.

| Command | What it does |
|---|---|
| `foresprint web` | start the web UI as an app window |
| `foresprint init TEAM` | create a team with guidance |
| `foresprint sprints TEAM [--create] [--end SPRINT=DATE]` | sprint calendar: upcoming sprints, end dates |
| `foresprint rename-sprint TEAM SPRINT NEW` | change a sprint ID; the saved sprints after it count on |
| `foresprint absences TEAM [SPRINT]` | record absences per person; with `--person NAME --from DATE [--to DATE] [--confirmed] [--remove]` it works on absence periods (`abwesenheiten.yaml`, dates only, never a reason) and shows the working days per sprint; `--periods` lists them |
| `foresprint people TEAM [--former] [--kind member\|guest\|external] [--until DATE]` | maintain the people list; `--kind` and `--until` apply to people added in this run (external people need an end date) |
| `foresprint sprint-naming TEAM [--pattern P [--from SPRINT]] [--clear]` | show or set the sprint naming pattern (`{JJJJ} {JJ} {NN} {N} {LFD} {Q} {MM} {KW}`) with a preview; duplicate names are marked |
| `foresprint estimation TEAM [--unit SP\|PT [--from SPRINT]] [--factor F] [--remove SPRINT]` | show or change the estimation unit over time and the story points per person day (0 = measured team rate) |
| `foresprint products TEAM [SPRINT] [--preplanning]` | distribution per product, PO pre-planning, balance |
| `foresprint product-list TEAM` | maintain products (PO, period) |
| `foresprint planning TEAM [SPRINT]` | record commitment and planning values |
| `foresprint review TEAM [SPRINT] [--commit]` | record velocity and scope creep, freeze capacity |
| `foresprint forecast TEAM [--explain SPRINT]` | forecast for the current and upcoming sprints |
| `foresprint capacity TEAM [SPRINT]` | capacity calculation in detail |
| `foresprint analysis TEAM [--remaining AMOUNT] [--total] [--share PERCENT]` | range, focus factor, buffer, completion |
| `foresprint report [TEAM] [--output PATH]` | write `FORECAST.md` |
| `foresprint excel TEAM [--output PATH]` / `excel-import TEAM FILE [--apply]` | Excel export and import |
| `foresprint tickets TEAM [--fetch \| --import FILE \| --handover [--overwrite]] [--apply] [--commit] [--sprints N] [--variant median\|conservative\|optimistic]` | ticket pre-planning: read tickets from Jira (`--fetch`, extra `[jira]`, read-only) or a tracker CSV export, distribute them over future sprints, project traffic light with the range of the conservative, median (Forecast PLAN) and optimistic variants, refinement list (feature `tickets`); `--handover` proposes the sums per sprint and product as the PO pre-planning (`--apply` writes where nothing is entered, `--overwrite` also replaces entered values); `--test-connection`, `--set-token` and `--write-labels` (earmarks as `planned_for_<sprint>` labels) for Jira, see [Jira import](jira.md) |
| `foresprint check [--strict]` | validate all data (CI, before a commit) |
| `foresprint settings TEAM` | change team settings |
| `foresprint data-dir [PATH]`, `language [de\|en]`, `shortcut`, `update` | remembered data folder, UI language, desktop launcher, update |
| `foresprint help [TOPIC]` | workflow, terms, fields, team settings, commands |

`--data PATH` and `--as-of DATE` go before the command; `--commit` on the editing commands
commits the change to Git. The full sprint workflow is in
[Sprint workflow](sprint-workflow.md).

## Language

English is the default. Switch in the sidebar of the web UI (**Sprache / Language**) or with
`foresprint language de` (back with `foresprint language en`); the choice is remembered.
`FORESPRINT_LANG=de` takes precedence. Command, option and environment variable names are
English in both languages. The YAML files are English regardless of the language; only the report
`FORECAST.md` and the minutes follow the configured language.

## Configuration

- **Team settings** (`team.yaml`): estimation unit, features (products, PO, production
  access), sprint length and numbering, reference capacity, window, plannable share, trend
  mode, overhead, country, region and working week. Change them with `foresprint settings
  TEAM` or the *Settings* page; every key is explained in [Data format](data-format.md)
  and `foresprint help team`.
- **Environment variables:** `FORESPRINT_DATA` (data directory), `FORESPRINT_AS_OF`
  (date that counts as today), `FORESPRINT_LANG` (`en` or `de`), `FORESPRINT_AUTOUPDATE`
  (`on`, `notice` or `off`), `FORESPRINT_BROWSER` (browser for the app window).
- **Web UI options:** `foresprint web --no-app` opens a browser tab instead of an app
  window, `--no-browser` only starts the server, `--port` and `--browser PATH` choose port and
  browser.

## Updating

`foresprint` checks at most once a day for a newer version and installs it after the command
or the app exits; plugins and the Python version are kept. `foresprint update` updates now
(`--check` only checks, `--force` reinstalls); `foresprint update --auto on|notice|off` or
`FORESPRINT_AUTOUPDATE` controls the automatic behaviour. Installations pinned to a tag are
not updated automatically. Details in [Installation](installation.md#updating).
