# Command line and configuration

The window and the command line read and write the same files. This page lists every command,
how the data directory is found, the settings and the environment variables.

## Data directory and reference date

**Data directory:** `--data PATH`, otherwise the environment variable `FORESPRINT_DATA`,
otherwise the **current directory** if it contains teams, otherwise the **remembered data
folder** (window: *Settings > Storage*; command line: `foresprint data-dir PATH`). Teams are
subfolders with a `team.yaml`; if a directory has none but a subfolder `teams` with teams, that
one is used. If the window finds no data folder, it guides you through choosing, creating or
cloning one. `--as-of DATE` (or `FORESPRINT_AS_OF`) sets the date that counts as "today",
for retrospectives and tests.

## Commands at a glance

Window and command line are one program (Go, see [go/README.md](../go/README.md)); the
commands write the same files as the window.

| Command | What it does |
|---|---|
| `foresprint gui` (or no command: a double click) | open the window |
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
| `foresprint excel TEAM [--output PATH]` / `excel-import TEAM FILE [--apply]` | Excel export and import; what the workbook does not hold (product owners, estimation unit, sprint naming, person kinds, pre-planning details) stays as it is on import |
| `foresprint tickets TEAM [--fetch \| --import FILE \| --handover [--overwrite]] [--apply] [--commit] [--sprints N] [--variant median\|conservative\|optimistic]` | ticket pre-planning: read tickets from Jira (`--fetch`, read-only) or a tracker CSV export, distribute them over future sprints, project traffic light with the range of the conservative, median (Forecast PLAN) and optimistic variants, refinement list (feature `tickets`); `--handover` proposes the sums per sprint and product as the PO pre-planning (`--apply` writes where nothing is entered, `--overwrite` also replaces entered values); `--test-connection`, `--set-token` and `--write-labels` (earmarks as `planned_for_<sprint>` labels) for Jira, see [Jira import](jira.md) |
| `foresprint storage [server ADDRESS \| sign-in ADDRESS \| identity \| share \| branch \| save \| refresh \| history]` | Settings > Storage and the Data area on the command line, the same service as the window: show the setup, set the server (checked first), hand a token to Git's credential helper (never stored by Foresprint; read from the terminal without echo, or one line from standard input), name and email for saves, way to share, branches, save (`-m`, `--anyway`), refresh, history |
| `foresprint check [--strict]` | validate all data (CI, before a commit) |
| `foresprint settings TEAM` | change team settings |
| `foresprint serve` | show the window as a page of the browser, on this computer only (not in the CLI-only build); prints a link with a secret key (stop with Ctrl+C), see [The window](window.md#showing-foresprint-in-the-browser) |
| `foresprint data-dir [PATH]`, `language [de\|en]`, `shortcut`, `update` | remembered data folder, UI language, desktop launcher, update |
| `foresprint completion bash\|zsh\|fish\|powershell`, `version` | Tab completion script, version |
| `foresprint help [TOPIC]` | workflow, terms, fields, team settings, commands |

`--data PATH` and `--as-of DATE` go before the command; `--commit` on the editing commands
commits the change to Git. The full sprint workflow is in
[Sprint workflow](sprint-workflow.md).

## Language

English is the default. Switch in **Settings > Personal** or with
`foresprint language de` (back with `foresprint language en`); the choice is remembered.
`FORESPRINT_LANG=de` takes precedence. Command, option and environment variable names are
English in both languages. The YAML files are English regardless of the language; only the report
`FORECAST.md` and the minutes follow the configured language.

## Configuration

- **Team settings** (`team.yaml`): estimation unit, features (products, PO, production
  access), sprint length and numbering, reference capacity, window, plannable share, trend
  mode, overhead, country, region and working week. Change them with `foresprint settings
  TEAM` or the *Settings > Team* page; every key is explained in [Data format](data-format.md)
  and `foresprint help team`.
- **Environment variables:** `FORESPRINT_DATA` (data directory), `FORESPRINT_AS_OF`
  (date that counts as today), `FORESPRINT_LANG` (`en` or `de`), `FORESPRINT_AUTOUPDATE`
  (`on`, `notice` or `off`), `FORESPRINT_JIRA_TOKEN` (see [Jira import](jira.md)),
  `FORESPRINT_NO_BACKGROUND_FETCH` (`1` switches off the background fetch of the window).

## Updating

`foresprint` checks at most once a day for a newer version and points it out after the command
or the app exits; it never installs by itself. `foresprint update` updates now
(`--check` only checks, `--force` reinstalls); `foresprint update --auto on|off` or
`FORESPRINT_AUTOUPDATE` controls the daily check. Details in [Installation](installation.md#updating).
