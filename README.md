# sprintforecast

Velocity and capacity forecast for Scrum teams. It answers one question above all: **how much
can the team plan in the next sprint?** It answers it mid-sprint too, so product owners can plan
ahead while the current sprint is still running. The data is plain YAML in a Git repository; a
local web UI and a command line read and write the same files.

## Features

- **Git is the database:** YAML files, one sprint per file, easy to diff and merge; no server.
- **Guided input:** assistants for planning, review and absences explain every field and check
  plausibility. Planning follows the meeting: absences, Forecast PLAN and planned amounts,
  commitment.
- **Capacity from a people list:** memberships with period and FTE, plannable absences per
  sprint, public holidays and working week per country and region (worldwide, through the
  `holidays` library).
- **Transparent calculation:** normalized velocity, moving average and trend, configurable per
  team, every figure traceable with the numbers substituted.
- **Several products:** default distribution, PO pre-planning, planning and done per product,
  with charts and balance; the product list can change over time.
- **Supplementary analyses:** range, focus factor, buffer, "When will it be done?" (Monte Carlo).
- **Excel round trip:** export a workbook with real formulas and import the yellow cells back.
- **Self-updating:** checks daily for a new version and installs it after exit (can be turned
  off).
- **Extensible:** plugins add commands and pages, for example imports.
- **Unit-neutral:** the estimation unit, story points (SP) or person days (PD), is a team setting.
- **English and German:** UI, command line and report in both languages; the YAML files are
  always English (keys and comments).

## Installation

One command installs [uv](https://docs.astral.sh/uv/) if needed, downloads Python 3.14 and
installs sprintforecast with the web UI. Git is needed for everything that commits, shares or
clones data; the app also finds Git outside the PATH (details in
[Installation](docs/installation.md)).

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.sh | sh
```

Then open a new terminal. The script also creates a desktop launcher **"Sprint-Forecast"**
(desktop and Start menu on Windows, `~/Applications` on macOS, application entry on Linux) that
opens the web UI as an app window; the first start guides you through setting up the data
folder. Running the script again updates the installation; it asks about
[plugins](docs/plugins.md#plugins-with-the-installer) and remembers the answer. The script
installs the extras `web`, `excel` (Excel export and import) and `jira` (Jira import of the ticket
pre-planning, read-only apart from the optional label write-back; see [docs/jira.md](docs/jira.md)).

Coming from the old name sprintforecast? `uninstall-old.sh` / `uninstall-old.ps1` remove the old installation
and keep your data ([details](docs/installation.md#removing-the-old-name-sprintforecast)).

## Quick start

```bash
cd sprint-data                     # data directory: one subfolder per team
sprintforecast web                 # web UI
sprintforecast help                # what to do when
sprintforecast forecast team-a     # forecast on the command line
```

**Windows PowerShell:**

```powershell
cd "$HOME\sprint-data"
sprintforecast web
```

Try the demo (in the folder of this repository):

```bash
sprintforecast --data examples/teams --as-of 2026-10-15 forecast demo
```

**Data directory:** `--data PATH`, otherwise the environment variable `SPRINTFORECAST_DATA`,
otherwise the **current directory** if it contains teams, otherwise the **remembered data
folder** (web UI: *Data folder* page; command line: `sprintforecast data-dir PATH`). Teams are
subfolders with a `team.yaml`; if a directory has none but a subfolder `teams` with teams, that
one is used. If the web UI finds no data folder, it guides you through choosing, creating or
cloning one. `--as-of DATE` (or `SPRINTFORECAST_AS_OF`) sets the date that counts as "today",
for retrospectives and tests.

## Commands at a glance

| Command | What it does |
|---|---|
| `sprintforecast web` | start the web UI as an app window |
| `sprintforecast init TEAM` | create a team with guidance |
| `sprintforecast sprints TEAM [--create] [--end SPRINT=DATE]` | sprint calendar: upcoming sprints, end dates |
| `sprintforecast rename-sprint TEAM SPRINT NEW` | change a sprint ID; the saved sprints after it count on |
| `sprintforecast absences TEAM [SPRINT]` | record absences per person |
| `sprintforecast people TEAM [--former]` | maintain the people list |
| `sprintforecast products TEAM [SPRINT] [--preplanning]` | distribution per product, PO pre-planning, balance |
| `sprintforecast product-list TEAM` | maintain products (PO, period) |
| `sprintforecast planning TEAM [SPRINT]` | record commitment and planning values |
| `sprintforecast review TEAM [SPRINT] [--commit]` | record velocity and scope creep, freeze capacity |
| `sprintforecast forecast TEAM [--explain SPRINT]` | forecast for the current and upcoming sprints |
| `sprintforecast capacity TEAM [SPRINT]` | capacity calculation in detail |
| `sprintforecast analysis TEAM [--remaining AMOUNT] [--total] [--share PERCENT]` | range, focus factor, buffer, completion |
| `sprintforecast report [TEAM] [--output PATH]` | write `FORECAST.md` |
| `sprintforecast excel TEAM [--output PATH]` / `excel-import TEAM FILE [--apply]` | Excel export and import |
| `sprintforecast tickets TEAM [--fetch \| --import FILE \| --handover [--overwrite]] [--apply] [--commit] [--sprints N] [--variant median\|conservative\|optimistic]` | ticket pre-planning: read tickets from Jira (`--fetch`, extra `[jira]`, read-only) or a tracker CSV export, distribute them over future sprints, project traffic light with the range of the conservative, median (Forecast PLAN) and optimistic variants, refinement list (feature `tickets`); `--handover` proposes the sums per sprint and product as the PO pre-planning (`--apply` writes where nothing is entered, `--overwrite` also replaces entered values); `--test-connection`, `--set-token` and `--write-labels` (earmarks as `planned_for_<sprint>` labels) for Jira, see [docs/jira.md](docs/jira.md) |
| `sprintforecast check [--strict]` | validate all data (CI, before a commit) |
| `sprintforecast settings TEAM` | change team settings |
| `sprintforecast data-dir [PATH]`, `language [de\|en]`, `shortcut`, `update` | remembered data folder, UI language, desktop launcher, update |
| `sprintforecast help [TOPIC]` | workflow, terms, fields, team settings, commands |

`--data PATH` and `--as-of DATE` go before the command; `--commit` on the editing commands
commits the change to Git. The full sprint workflow is in
[docs/sprint-workflow.md](docs/sprint-workflow.md).

## Language

English is the default. Switch in the sidebar of the web UI (**Sprache / Language**) or with
`sprintforecast language de` (back with `sprintforecast language en`); the choice is remembered.
`SPRINTFORECAST_LANG=de` takes precedence. Command, option and environment variable names are
English in both languages. The YAML files are English regardless of the language; only the report
`FORECAST.md` and the minutes follow the configured language.

## Data folder and Git

Git is the database: one sprint per YAML file, so POs and Scrum Masters can work in parallel and
every change has an author and a history. The web UI handles the everyday Git work without a
terminal: save and share, fetch others' changes, resolve conflicts per value, view the history,
restore an earlier state, manage tags (see [Web UI](docs/web-ui.md)).

This repository contains **only code and demo data**. Real team data lives in a separate data
repository inside your company's domain, created from the template
[`templates/daten-repo/`](templates/daten-repo) or from the web UI's *Data folder* page. See
[Data repository](docs/data-repository.md).

## Configuration

- **Team settings** (`team.yaml`): estimation unit, features (products, PO, production
  access), sprint length and numbering, reference capacity, window, plannable share, trend
  mode, overhead, country, region and working week. Change them with `sprintforecast settings
  TEAM` or the *Settings* page; every key is explained in [Data format](docs/data-format.md)
  and `sprintforecast help team`.
- **Environment variables:** `SPRINTFORECAST_DATA` (data directory), `SPRINTFORECAST_AS_OF`
  (date that counts as today), `SPRINTFORECAST_LANG` (`en` or `de`), `SPRINTFORECAST_AUTOUPDATE`
  (`on`, `notice` or `off`), `SPRINTFORECAST_BROWSER` (browser for the app window).
- **Web UI options:** `sprintforecast web --no-app` opens a browser tab instead of an app
  window, `--no-browser` only starts the server, `--port` and `--browser PATH` choose port and
  browser.

## Updating

sprintforecast checks at most once a day for a newer version and installs it after the command
or the app exits; plugins and the Python version are kept. `sprintforecast update` updates now
(`--check` only checks, `--force` reinstalls); `sprintforecast update --auto on|notice|off` or
`SPRINTFORECAST_AUTOUPDATE` controls the automatic behaviour. Installations pinned to a tag are
not updated automatically. Details in [Installation](docs/installation.md#updating).

## Documentation

- [Installation and updates](docs/installation.md): Git lookup, desktop launcher, manual
  installation, automatic updates
- [Web UI](docs/web-ui.md): pages, planning steps, saving and sharing with Git, server setup,
  data folders, changes and history
- [Sprint workflow](docs/sprint-workflow.md): what to do when, PO pre-planning and planning,
  longer or shorter sprints
- [Data format](docs/data-format.md): `team.yaml`, `people.yaml`, `products.yaml`, sprint
  files, `FORECAST.md`, minutes
- [Calculation](docs/calculation.md): formulas, capacity sources, trend modes, uncertainty,
  supplementary analyses
- [Jira import](docs/jira.md): ticket pre-planning from Jira Data Center with a personal access
  token (read-only; optional label write-back)
- [Plugins](docs/plugins.md): writing and installing plugins
- [Data repository](docs/data-repository.md): why Git, the template, separating code and data
- `sprintforecast help [workflow|terms|fields|team|commands]` and the *Help* page of the web UI

## Development

Prerequisite: [mise](https://mise.jdx.dev); Python and uv are pinned in `mise.toml`.

```bash
mise install
uv sync --all-extras
uv run sprintforecast --data examples/teams web   # run from source
uv run pytest
uv run ruff check && uv run ruff format --check
uv run python scripts/measure.py --md      # response-time measurement (see docs/performance.md)
```

### Release

1. Raise the version in `pyproject.toml` and `src/sprintforecast/__init__.py`, run `uv lock`,
   and merge into `main` through a pull request.
2. Tag the merge commit and push the tag:
   `git tag -a v0.4.2 -m "Version 0.4.2" && git push origin v0.4.2`.
3. The *Release* workflow (`.github/workflows/release.yml`) runs tests and lint, compares tag
   and version, builds wheel and source distribution (`uv build`) and writes the release page
   with the files and automatically generated notes (from the pull requests merged since the
   last tag).

For an existing tag, the release can be repeated under *Actions, Release, Run workflow*. The
normal CI also builds the packages on every push and stores them as the artifact `dist`.

## Contributing

Bug reports, questions and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md)
describes the setup, tests, lint, the translation rule and the CI.

## License

[EUPL-1.2](LICENSE) (European Union Public Licence). In short: use is free, including
commercial and in-house use. Whoever distributes a modified version or offers it publicly as a
service must publish the changes under the EUPL.

All language versions approved by the European Commission are equivalent (Art. 13 EUPL).
`LICENSE` contains the English text; the official German version is in
[Commission Implementing Decision (EU) 2017/863](https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32017D0863).
