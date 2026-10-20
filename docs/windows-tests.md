# Windows checks (`scripts/windows-tests.ps1`)

The script checks what only shows up on a real Windows machine and writes a Markdown report
that you send back to the developers. It changes no user settings (no `git config`, no
persistent environment variables, no registry writes). All test data lives in a temp folder
that is deleted at the end.

## Prerequisites

- Windows 10 or 11, Windows PowerShell 5.1 or PowerShell 7
- `foresprint` installed as a uv tool (`uv tool install …`), `git` and `uv` in the PATH
- for the login check: the https and/or SSH address of your data repository
- **close all foresprint windows first** (otherwise the script skips the app check)

## Running

In the folder of this repository (after `git pull`), without changing the execution policy
permanently:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-tests.ps1
```

If the file was downloaded and Windows reports it as blocked, run
`Unblock-File .\scripts\windows-tests.ps1` once beforehand.

The report is written to the **current PowerShell folder** as
`foresprint-windows-bericht-YYYYMMDD-HHMM.md` (if that location is not writable, to the temp
folder; the script says so right at the start). It contains no credentials (tokens and
credentials in addresses are replaced by `***`, the profile folder by `%USERPROFILE%`); still,
skim it before passing it on.

Useful parameters:

| Parameter | Effect |
|---|---|
| `-Nur Zeilenenden,Symlink` | only these checks (`App`, `Uv`, `Anmeldung`, `Zeilenenden`, `Sperre`, `Symlink`, `Interaktiv`), comma-separated, no spaces |
| `-HttpsUrl …` / `-SshUrl …` | addresses for the login check (otherwise the script asks; Enter skips) |
| `-WartezeitSekunden 30` | wait time after closing the app window (default 20) |
| `-OhneRueckfragen` | no input; prompts and interactive checks are skipped |
| `-MitAutoUpdate` | run the app and the script's CLI calls with the configured self-update (default: off, only for these processes) |
| `-Bericht PATH` | write the report file somewhere else |
| `-PythonExe PATH` | the installation's Python, in case it is not found |

## What is checked

Duration without prompts about 2 to 3 minutes; the interactive questions come on top.

1. **Start and quit the app.** The script starts `foresprint-app` with a temporary data
   repository (only for this start, via `FORESPRINT_DATA`), waits for server and window,
   and lists all processes. Then it closes the window like the close button would
   (`CloseMainWindow`; if that does not work, or the app starts in Firefox or the default
   browser, it asks you to close the window yourself), waits 20 seconds and checks via
   `Get-CimInstance Win32_Process` that nothing is still running: no `foresprint-app.exe`,
   no `python(w).exe` with foresprint/streamlit, no browser with
   `--user-data-dir=…\foresprint\…`, no `uv.exe` update. If processes remain, the report
   names them together with the time at which they ended later. It also shows `app.log` and
   `update.log` from `%APPDATA%\foresprint`. Leftover processes are terminated by the
   script at the end.
2. **Installation (uv tool).** `uv tool list`; on request (prompt j/N, only with the app
   closed) `uv tool upgrade --reinstall foresprint`, which is also how the app updates
   itself, and the reinstall touches every file (if a process still locks something, this is
   where it shows).
3. **Login (Git).** `credential.helper` with its origin, Git Credential Manager,
   `gh auth status`, SSH agent and `git ls-remote` against your https and SSH address.
   Addresses with credentials are rejected. A Credential Manager login window may open; time
   limit 90 s.
4. **Line endings.** The script creates a data repository through the app logic (team `demo`,
   sprints via `foresprint sprints`), commits, clones it three times (your `core.autocrlf`
   setting, `autocrlf=true`, `autocrlf=false`) and checks: `git status`/`git diff` empty,
   `foresprint check` without errors, saving again changes nothing. The repository
   carries the `.gitattributes` (YAML with LF) that the app creates in new data repositories,
   so the protected state is what gets checked. Older repositories without that file are not
   covered.
5. **Locked file.** Holds a YAML file with an exclusive lock (`FileShare.None`) and with a read
   lock (`FileShare.Read`) and saves through the app logic. Expected: file unchanged, no
   `*.tmp` leftovers, and an understandable message instead of a raw system error
   (`PermissionError` is reported as **HINWEIS**).
6. **Symlink permission.** Creates a symbolic link in the temp folder (`mklink` first, because
   `New-Item` in Windows PowerShell 5.1 requires administrator rights even in developer mode)
   and reports administrator and developer mode. Lacking the permission is not an app error;
   only one development test (symlink) is skipped then.
7. **Interactive checks** (only with input): network disconnected, protected branch, and the
   visuals (landing page, step bar, tables, server mask, conflict page, what-if/history,
   calendar texts/calculation path, English UI). Per question `J`, `N` or Enter (skip), then a
   note. For these you open the app yourself (shortcut). These checks leave things behind that
   you undo yourself: reconnect the network, a commit on the protected branch (better use a
   test repository), set the language back to German.

## Result values

| Value | Meaning |
|---|---|
| OK | expectation met |
| FEHLER | expectation violated (details in the report) |
| HINWEIS | noteworthy or not fully checkable, but no hard error |
| ÜBERSPRUNGEN | not run (prerequisite missing, no prompts, not Windows) |

## What the script creates or changes on your machine

- temp folder `%TEMP%\foresprint-wintest-…` (deleted at the end; if it remains, the script
  names the path)
- the report file in the current folder
- by starting the app (check 1): its usual files under `%APPDATA%\foresprint` (`app.log`
  is overwritten) and the browser profile under `%LOCALAPPDATA%\foresprint`
- read only, never changed: Git configuration, SSH agent, registry (developer mode)

## Known limits

- The locked-file test checks the app's save function, not the UI on top of it; whether the UI
  shows a message is only stated by the HINWEIS text in the report.
- A browser that does not let the window be closed (e.g. Firefox instead of Edge/Chrome)
  forces manual closing.
- The script is tested on Linux with PowerShell 7 for syntax and the platform-independent
  helper functions (`tests/test_windows_script.py`, runs in CI); the Windows parts (process
  list, locks, closing the window) run for the first time on your machine.
- Only what is still the same process is cleaned up (start time compared): process IDs may
  belong to someone else by then.
