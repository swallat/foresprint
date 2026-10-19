# Web UI

The web UI is a local [Streamlit](https://streamlit.io) application. It reads and writes the
**same YAML files** as the command line and validates everything before saving. See the
[README](../README.md) for installation and the quick start.

```bash
sprintforecast web                         # in the data directory
sprintforecast --data ../data-repo web     # or with a path
```

## Starting the UI

**As an app (default):** `sprintforecast web` opens the UI in its own window without an address
bar; closing the window also stops the server. `--app` is still accepted (the desktop launcher
and shortcuts use it). With `--no-app` a normal browser tab opens instead and the server runs
until Ctrl+C; with `--no-browser` no window opens at all and the server does not stop on its own
(for tests or remote access through port forwarding, for example). Browsers are searched in this
order, in the PATH (including Scoop and Chocolatey shims) and in the usual installation
locations (on Windows including the Scoop and Chocolatey directories):

1. App mode: Edge, Chrome, Comet, Chromium, Brave, Vivaldi
2. Firefox (no app mode any more) in a new window
3. The system's default browser
4. Nothing found: the address is shown and the server keeps running

`--browser PATH` or the environment variable `SPRINTFORECAST_BROWSER` forces a particular
browser. If port 8501 is taken, a free one is chosen automatically (`--port N` chooses another
port).

The UI runs at <http://localhost:8501>. It is reachable only on your own machine and needs no
hosting; the data stays in the local Git clone.

## First start: choosing a data folder

If the web UI finds no data folder (no teams, no Git repository), it guides you through the
setup: pick an existing folder (Git is recommended but not required: without Git there is no
commit; after "Use without Git" you continue with **New team**; the decision is remembered per
folder in the user settings and still applies after a reload or in a new tab), create a new data
repository (`git init`, `.gitignore`, a `teams` folder with `.gitattributes`) or clone the team's
shared data repository. The rules for finding the data directory are in the
[README](../README.md#quick-start).

## Pages

| Area | Page | Content |
|---|---|---|
| Tasks (in chronological order) | Start | three task tiles ("Prepare sprint", "Planning", "Close sprint"); each leads to the next sensible page depending on the sprint's state (for example absences unknown or only announced leads to Absences) |
| | Prepare sprint: Absences | table person x sprint with a live preview of capacity and forecast; state per sprint, explicit confirmation of "Nobody absent" |
| | PO pre-planning | per product, what should go into the sprint, compared with the default; total per PO; announced absences |
| | Planning | guided flow: 1. absences, 2. Forecast PLAN and planned amount per product, 3. commitment |
| | Close sprint (Review) | velocity, scope creep, done per product, not done / additionally done; the available person days are frozen |
| Evaluation | Forecast | forecast for the current and upcoming sprints (with range), history, chart, write report |
| | Analysis | supplementary: range, focus factor, buffer recommendation, "When will it be done?" |
| | Product distribution | evaluation only: default, PO pre-planning, planning and done per product; charts, history, balance; values are changed only on the boards (links on the page) |
| Manage team | Sprint calendar | upcoming sprints with start, last day and working days; create, adjust length |
| | People | one table (one row per membership period, FTE); IDs are assigned automatically; former members can be hidden |
| | Products | product list with PO and period (from/to); former products can be hidden |
| | Settings | all team settings; changes are shown before saving; **Change sprint IDs** renames a sprint and counts the following sprints on |
| | New team | create a team; asks for the first sprint (the one running now or starting next) before anything else |
| Data & help | Data folder | choose, create or clone a data folder (Git repository); enter, test and change the server (remote) |
| | Changes and history | discard open changes, history per team/sprint/file, restore an earlier state, manage tags |
| | Check | findings of all teams |
| | Help | tabs Workflow, Terms, Input fields, Team settings, Collaboration (Git) and Command line |

The start page offers the three tasks **Prepare sprint**, **Planning** and **Close sprint**; the
**Forecast** ("How much fits into the next sprint?") is under **Evaluation**. The sprint selector
is the same on every page (label "Sprint", same order, default: the current sprint) and applies
across pages. Product values (PO pre-planning, planning, done) are entered exclusively on the
boards; the **Product distribution** page is evaluation only. Without an open sprint, "Prepare
sprint" and "Planning" point to the sprint calendar.

On the task pages **Prepare sprint: Absences**, **PO pre-planning**, **Planning** and **Close
sprint (Review)** (in the order of the sidebar) a step bar at the top shows the state of the
selected sprint and switches between the four steps with one click; the active step has a blue
background. Completed steps carry a green check mark after their name (open steps have no mark);
the tooltip says "recorded for sprint ..." or "still open for sprint ...". The check mark comes
from the sprint data: for absences only for the state "confirmed" (recorded or explicitly "nobody
absent"; "announced" and "unknown" get no check mark, and the start page's "Prepare sprint" task
then leads to Absences as well), for PO pre-planning a recorded pre-planning per product, for
Planning the commitment, for Review the velocity. Teams without the Products feature have only
three steps, without PO pre-planning.

## Saving, committing and sharing

Every page saves to the YAML files. The sidebar shows under **Git** the state compared with the
server (not yet shared, new from others, offline, when last checked) and the open changes in the
data directory.

- **Save and share** first commits your own changes (after a review optionally with the tag
  `TEAM/SPRINT`), then fetches the others' state, merges both and uploads the result. The
  sidebar then lists what was taken over from others (who, when, which files). In a race
  (someone uploads in between) it fetches and uploads again. If the server has a completely
  different history (usually the wrong repository, such as a code repository), nothing is merged
  or uploaded; the operation stops with a message. Only after explicit confirmation in the sidebar
  (checkbox "Yes, merge both histories"; the default is to abort; the message names server and
  branch) are the histories merged anyway. Notes despite success (for example a tag that points to
  a different commit) appear below the result. A tag that already exists locally aborts the save
  before anything is committed. Different values in the same file (Anna's and Ben's absences in
  the same sprint, two different people in `people.yaml`) are merged automatically. Only when both
  sides changed the same value differently is editing locked, and the **Resolve conflicts** page
  asks per entry for "My change" or "Other change" (files deleted on one side are decided as a
  whole). The merge can also be aborted there; nothing is lost, your own commit remains. An open
  merge survives a restart of the app.
- **Full validation:** after every merge the data check runs. A technically clean merge can be
  invalid in substance (two people change different product shares that add up to 120 %): new
  errors stop the upload and the list shows them; after the correction, "Save and share" is
  enough, or deliberately **Share anyway**.
- **Stale forms:** if the files change while a page is open (sharing, another program), unsaved
  input is discarded with a notice and reloaded instead of overwriting others' changes. Conflict
  markers in a file (`<<<<<<<`) are detected before the YAML is loaded; the page then offers to
  restore the file.
- **Stable files:** files are always written with LF line endings, only when the content changed
  and through a temporary file; absences, done products and so on are sorted alphabetically so
  that simultaneous additions rarely collide.
- **Pull from server** takes over what others uploaded without uploading anything: it commits
  your open changes, fetches the server state and merges it. Conflicts and the confirmation for a
  foreign history work as for "Save and share" and also stay local. Use it to refresh the
  checkout before looking at the data; "Save and share" uploads the result later.
- **Check status** asks the server whether there is anything new and changes nothing. The server
  state is queried only then and when sharing.
- **Commit changes** commits locally only, without sharing.
- Error cases are explained in plain language with the next step: server unreachable, repository
  not found (check the address), certificate not trusted, upload rejected (new changes in the
  meantime or forbidden by the server), missing login (https access token or SSH key, credential
  manager; with SSH also the unknown server fingerprint), Git not installed, locked file, folder
  not writable or rejected by Git as unsafe, missing name/e-mail (asked for), incomplete merge
  (abort) and detached HEAD (back to the branch). Git never asks for a password in the background;
  the machine's login (credential manager, SSH agent) is used.

## Server (remote)

If a data folder has no server yet, the sidebar ("Set up server") points to the **Data folder**
page; the **Server (remote)** section there also changes the address. The address is checked
immediately (allowed are `https://...`, `ssh://...`, `git@server:path` and full folder paths;
`http://` only after explicit confirmation), **Test connection** asks the server for its branches
and changes nothing, **Save** checks again and saves only when the check passes. If the server
is demonstrably unreachable (network error, timeout) or lacks the local branch, the address can
be saved only with explicit confirmation; a repository that is not found (typo in the project
name), a rejected login or an untrusted certificate are never saved. If the new folder has no
data yet but the server does, the form warns and points to **Clone repository**. Credentials
(user name, password, token) in the address are rejected, never stored and never shown; the
login is handled as always by the machine's credential service, and if it is missing the app
explains the next step. The app creates no SSH keys and changes the global Git configuration
only on request and only for the name and e-mail of the commits. Several addresses or a separate
upload address (`pushurl`) as well as an open merge block saving. Whoever joins an existing team
is better off choosing **Clone repository**.

## Switching the data folder

The sidebar permanently shows the data folder (with its parent folder, for example
`data/teams`) and the branch; the list of recently used folders (up to 8, remembered in the user
settings) serves as a switch in the sidebar and on the **Data folder** page (where entries can
also be removed from the list). The data folder applies per browser window: if one window
switches, other open windows keep working in their folder; newly opened windows start in the
last chosen one. On switching, unsaved form input and all caches (teams, Git state) of the old
folder are discarded; pending tags, the commit message and open changes in the old folder stay
there and are back when you switch back.

**An open merge blocks writing:** as long as a merge or rebase is open, all team pages, **New
team** and plugin pages are replaced by the conflict resolution; on the **Changes and history**
page, restore, revert, discard and tags are disabled.

## Changes and history

On the **Changes and history** page (its own page): *Discard* single files or all open changes,
with a preview of what is lost and a confirmation (a copy lands in the trash under
`.git/sprintforecast-verworfen`). *History* per team, sprint or file (who, when, what).
*Restore* an earlier state is itself a commit and can be undone with "Revert this change"
(merges cannot be reverted this way). *Tags*: show, set retroactively on any commit and delete,
each also on the server (if that fails, the tag stays local and the app says so). "Compare with
server" (network, only on click) shows per tag whether it exists only locally, only on the server
or differs; local-only tags can be pushed with "Push to server", and tags that exist only on the
server can be deleted. When discarding, renames appear as "renamed: old -> new". If the user
settings cannot be saved (folder not writable), the app shows the message with the next step and
the switch or change does not happen.

Only the data directory is committed; spreadsheets (`*.xlsx` and so on) are rejected. The model is
"one branch, always in sync"; branches, rebase, force push and stash are deliberately not part of
the app. Sharing pushes straight to the branch, so there are no merge requests; on the server,
protect `main` of the data repository against force push and deletion (but do not require
reviews, or sharing is rejected). The Git state is cached briefly (5 seconds); changes made outside the app (editor,
terminal) therefore appear with a small delay, your own saves immediately.

## Updates in the web UI

At startup the UI checks for a new version in the background; if one exists, it appears in the
sidebar (on the next page render after the check; the UI does not wait for it). It is installed
when the app is closed, or immediately with **Update now and restart**: the app exits, updates
and reopens (same data directory, same options). See [Installation](installation.md#updating)
for the details.
