# The window

Foresprint 1.0 is one program: a double click on the launcher (or `foresprint gui`) opens the
window. It reads and writes the **same YAML files** as the command line and validates everything
before saving. Nothing runs in a browser and no server is started; the data stays in the local
folder or Git clone. See the [README](../README.md) for installation and the quick start, and
[Installation](installation.md) for the launcher.

```bash
foresprint gui                        # in the data directory
foresprint --data ../data-repo gui    # or with a path
```

## First start: choosing a data folder

If the window finds no data folder (no teams), it guides you through the setup: pick an existing
folder, create a new data repository (`git init`, `.gitignore`, a `teams` folder with
`.gitattributes`) or clone the team's shared data repository. Git is recommended but not required:
without Git there is no history and no sharing. Recently used folders (up to 8) are remembered per
user and can be switched under **Settings > Storage**. The rules for finding the data directory are in
[Command line and configuration](cli.md#data-directory-and-reference-date).

## Pages

The navigation on the left has these groups. Pages for the ticket pre-planning appear only for teams
with the feature `tickets`.

| Group | Page | Content |
|---|---|---|
| | Today | what is due next in the sprint, findings (projects at risk, open tickets without an estimate) |
| | Backlog | the tickets in order: filter, sort, drag between backlog and sprints, with capacity and project dates changing at once; presentation view for the refinement or planning meeting |
| Sprints | Sprint overview | the sprints with their state |
| | Prepare | absences per person and sprint with a live preview of capacity and forecast; per cell announced or confirmed |
| | Pre-plan | per product, what should go into the sprint, compared with the default |
| | Plan | the planning with the Forecast PLAN, planned amounts per product, what-if and the commitment; the sprint gets a name here |
| | Review | velocity, scope creep, done per product; the available person days are frozen |
| | Minutes | the minutes of the planning meetings |
| Projects | Projects, project page | projects with milestones, end dates and contingents, a traffic light and a timeline; closing a project |
| | Forecast | the forecast for the current and upcoming sprints with its range, history, what-if, "When will it be done?" and the report |
| Team | People and absences | one table, one row per membership period with FTE; absence periods per person (dates only, never a reason) |
| | Products | product list with product owner and period |
| | Sprint calendar | upcoming sprints with start, last day and working days |
| Data | Overview | state of the data folder and the server, save and refresh |
| | Conflicts | resolve a merge conflict per value |
| | History and tags | history per team, sprint or file; restore an earlier state; tags |
| Settings | Team | all team settings; changes are shown before saving |
| | Tickets and tracker | tracker connection (Jira, CSV, work packages), field mapping, rules, import of a package |
| | Storage | folder or Git server, sign-in, name and e-mail for saves, way of sharing |
| | Personal | settings that only apply to you on this computer: language, theme (system, light, dark), density, how calculations are shown |
| | Updates | the update mode (`on`, `notice`, `off`) and the check for a new version |
| Help | Calculations, Guided flows | the formulas with your numbers, and the guided flows as a tutorial with the demo team |

Every figure opens its calculation. The sprint chosen in the header applies across pages.

## Saving, sharing and refreshing

Every page saves to the YAML files. The Data area shows the state compared with the server (not
yet shared, new from others, offline, when last checked) and the open changes.

- **Save** commits your own changes; **Save and share** first commits, then fetches the others'
  state, merges both and uploads the result. The window lists what was taken over from others
  (who, when, which files). In a race (someone uploads in between) it fetches and uploads again.
  If the server has a completely different history (usually the wrong repository), nothing is
  merged or uploaded until you confirm explicitly.
- **Merging by key:** different values in the same file (Anna's and Ben's absences in the same
  sprint, two different people in `people.yaml`) are merged automatically. Only when both sides
  changed the same value differently, editing is locked and the **Conflicts** page asks per entry
  for "mine" or "theirs". The merge can be aborted there; nothing is lost. An open merge survives a
  restart.
- **Validation:** after every merge the data check runs. A technically clean merge can be invalid
  in substance (two people change product shares that add up to 120 %): new errors stop the upload
  and are listed.
- **Refresh** takes over what others uploaded without uploading anything. The window also fetches
  in the background; set `FORESPRINT_NO_BACKGROUND_FETCH=1` to switch this off.
- **Stale forms:** if the files change while a page is open (sharing, another program), unsaved
  input is discarded with a notice instead of overwriting others' changes.
- **Stable files:** files are written with LF line endings, only when the content changed and
  through a temporary file; lists such as absences are sorted so that simultaneous additions rarely
  collide.
- **Errors** are explained in plain language with the next step: server unreachable, repository
  not found, certificate not trusted, upload rejected, missing login, Git not installed, locked
  file, folder not writable, missing name or e-mail, incomplete merge. Git never asks for a
  password in the background; the machine's credential manager or SSH agent is used.

The same functions are on the command line as `foresprint storage` (see
[Command line](cli.md)).

## Server (remote) and sign-in

**Settings > Storage** sets the server address. The address is checked immediately (allowed are
`https://...`, `ssh://...`, `git@server:path` and folder paths; `http://` only after explicit
confirmation). **Test connection** asks the server for its branches and changes nothing. An
address that is demonstrably unreachable, or a server without the local branch, can be saved only
with explicit confirmation; a repository that is not found, a rejected login or an untrusted
certificate are never saved. Credentials in the address are rejected, never stored and never shown.
For https servers, **Set up sign-in** hands an access token once to Git's credential helper and
checks it; Foresprint never stores or shows the token. It creates no SSH keys and changes the
global Git configuration only on request, and only the name and e-mail of the commits.

## Changes and history

On **Data > History and tags**: *Discard* single files or all open changes, with a preview of what
is lost. *History* per team, sprint or file (who, when, what). *Restore* an earlier state is itself
a commit and can be undone with "Revert this change". *Tags*: show, set on any commit and delete,
also on the server; local-only tags can be pushed.

Only the data directory is committed; spreadsheets (`*.xlsx` and so on) are rejected. The model is
"one branch, always in sync"; branches, rebase, force push and stash are deliberately not part of
the app.

## Servers that only take merge requests

By default sharing pushes straight to the branch. For servers that protect `main` and require merge
or pull requests, switch on **Share via merge request** in Settings > Storage (per data
repository, stored in its local Git configuration). "Save and share" then merges the server state
and uploads to your own branch; a further share updates the same request. `main` stays untouched
until the request is merged; then **Refresh** brings it in. The app never holds an access token and
never signs in to a web API; what happens after the push depends on the kind of server (detected
from the remote address, or chosen in Storage):

| Server | What the app does |
| --- | --- |
| GitLab | Asks the server through push options to create or update the merge request. The server must accept push options. |
| Forgejo / Gitea / Codeberg | AGit flow: pushes to `refs/for/<target>`; the pull request is created or updated by the push. If the server does not support it, the branch is uploaded instead. |
| GitHub | Uploads the branch and shows the link where you open the pull request. Auto-merge is up to the repository. |
| Other / unknown | Uploads the branch. If the server happens to understand GitLab push options, the merge request is created; otherwise you open it on the server. |

Without merge requests, protect `main` against force push and deletion only (no required reviews,
or sharing is rejected).

## Updates

The program checks at most once a day for a new version, in the background. What happens then is a
setting (**Settings > Updates**, or `foresprint update --auto on|notice|off`): install by itself,
only point it out, or do nothing. See [Installation](installation.md#updating).
