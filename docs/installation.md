# Installation and updates

The short version is in the [README](../README.md#installation). This page has the details.

## What the installer does

One command installs [uv](https://docs.astral.sh/uv/) if needed, downloads Python 3.14 and
installs sprintforecast with the web UI.

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/foresprint/main/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/install.sh | sh
```

Then open a new terminal. Running the script again updates the installation. The script asks
about [plugins](plugins.md#plugins-with-the-installer) and remembers the answer; the
environment variables `SPRINTFORECAST_WITH`, `SPRINTFORECAST_REF` and `SPRINTFORECAST_NO_SHORTCUT`
skip the prompt.

Remove: `uv tool uninstall sprintforecast`.

From PyPI (once the package is published, see [releasing.md](releasing.md)):
`pipx install "foresprint[web,excel,jira]"` or `uv tool install "foresprint[web,excel,jira]"`.

Manually, without the script:

```bash
uv tool install "sprintforecast[web,excel,jira] @ https://github.com/swallat/foresprint/archive/refs/heads/main.zip"
```

The extra `[excel]` provides the Excel export and import; without it the commands `excel` and `excel-import` and the download on the forecast page report that `xlsxwriter` or `openpyxl` is missing. The extra `[jira]` provides the Jira import of the ticket pre-planning (`sprintforecast tickets TEAM --fetch`, see [jira.md](jira.md)); without it that command reports that `httpx` is missing, the CSV import works regardless. The extra also brings the package `keyring`, which stores the Jira token in the operating system keychain (web page *Jira connection* or `tickets TEAM --set-token`); the environment variable `SPRINTFORECAST_JIRA_TOKEN` needs nothing. An installation without the extras is upgraded with `uv tool install --force "sprintforecast[web,excel,jira] @ ..."` (the updater keeps the extras it was installed with).

## Git

Git is needed for plugins from Git repositories and for creating, committing, sharing, viewing
the history of and cloning the data (`sprintforecast data-dir PATH` also requires a Git
repository). Without Git the app runs with a data folder that is not a repository (`--data`,
`SPRINTFORECAST_DATA` or "Use without Git" on the Data folder page), but without these
functions.

For creating, committing, sharing, history and cloning, Git does not have to be in the PATH: the
app also looks in the usual places (on Windows `%LOCALAPPDATA%\Programs\Git`, Scoop and
`%ProgramFiles%\Git`; on macOS and Linux Homebrew, `/usr/local/bin`, `~/.local/bin`,
`~/.nix-profile/bin`). An installation without administrator rights is therefore enough (Git for
Windows installed for your own user account only); afterwards reopen the app and the
"Foresprint" launcher once. Updating the app (through `uv`, with plugins from Git
addresses) works then as well: if Git is only outside the PATH, the app appends its folder to
the PATH for the `uv` call (only there, not system-wide and not for the subsequent restart of
the app). The first installation through the install script is not affected by this: plugins
from Git addresses need Git in the PATH there.

If Git is not found, the install script says so at the end (the installation itself still
succeeds). A ZIP download of the data (GitHub/GitLab "Download source code") is not a repository
because it lacks the hidden `.git` folder; use "Clone repository" on the Data folder page
instead.

### Login to the server

The app never keeps credentials itself; the credential service of the computer does. For https
servers the Data folder page has **Set up sign-in**: you paste an access token (the page names
the permission to give it, for GitLab `write_repository`), and the app hands it once to Git's
credential service with `git credential approve`. It does not store the token, write it to a
file or log, or show it again, and it checks the result with `git ls-remote`; a rejected token is
removed again. If no credential helper is configured, the app offers (on click, for your user only,
never in the repository) the one that fits the computer: `manager` on Windows, `osxkeychain` on
macOS, `libsecret` on Linux if its helper is installed. It never sets `store` and hands no token
to it; on Linux without a secure helper it only explains the options. SSH keys are not created.
The start page shows a **Setup** checklist (Git, data folder, server, sign-in, name and email)
until everything is done; it only reads and can be hidden. When a login fails, the app explains the next step for the operating system it
runs on and reads (read-only, nothing is changed) the Git setting `credential.helper`:
on Windows the Git Credential Manager that comes with Git for Windows, on macOS the Keychain
(`osxkeychain`), on Linux `libsecret` or `gh auth setup-git`. A plain-text store
(`credential.helper store`) is reported as a warning and never recommended.

## Desktop launcher

The script creates a launcher **"Foresprint"**: on Windows on the desktop and in the Start
menu, on macOS in `~/Applications` (plus an alias on the desktop), on Linux as an application
entry and on the desktop. It starts the web UI as an app window (on Windows without a console
window); on the first start the UI guides you through setting up the data folder. Create it
again with `sprintforecast shortcut`; the log is `app.log` next to the plugin selection.

## Updating

Automatic, similar to Claude Code: when a command starts, sprintforecast checks in the
background at most once a day whether a newer version exists (field `version` in
`pyproject.toml` of the installed branch). If there is one, it is installed **after the
command exits** with `uv tool upgrade --reinstall sprintforecast` and applies from the next
start; plugins and the Python version are kept. On Windows the update waits until the program is
closed (running programs are locked there).

| Command / variable | Effect |
|---|---|
| `sprintforecast update` | check and update now (`--check`: check only, `--force`: reinstall) |
| `sprintforecast update --auto notice` | only point out new versions; `--auto off` switches off, `--auto on` back on |
| `SPRINTFORECAST_AUTOUPDATE=on\|notice\|off` | like `--auto`, takes precedence (for managed machines, for example) |

**In the web UI:** at startup the check runs in the background; if a new version exists, it
appears in the sidebar (on the next page render after the check; the UI does not wait for it).
It is installed when the app is closed, or immediately with **Update now and restart**: the app
exits, updates and reopens (same data directory, same options).

Log and state live next to the plugin selection (`update.log`, `update.json`). Installations
pinned to a tag (`SPRINTFORECAST_REF=v...`) are not updated automatically. Running the install
script again still works.

> For maintainers: a new version is detected only when `version` in `pyproject.toml` (and
> `__version__`) is raised.
