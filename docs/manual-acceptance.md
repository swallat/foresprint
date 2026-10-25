# Manual acceptance test plan

What CI cannot check: real operating systems, a real Jira, a real Git server, and a human looking
at the window. Run this plan before a release (beta or stable) and record the result per step.
Everything the automated tests cover (calculation, YAML round trips, the Jira client against a
fake) is deliberately not repeated here.

## How to use this plan

- Work through the areas in order; area priority is in the heading (**P1** must pass for a
  release, **P2** should, **P3** is optional).
- Record each step as `OK`, `FAIL`, `NOTE` (works, but surprising) or `SKIPPED` (not testable on
  this setup, say why). A `FAIL` or `NOTE` gets the system, the exact message text and, on Windows,
  `%LOCALAPPDATA%\Foresprint\logs\start.log`.
- Use the demo team ("Team Atlas") or a copy of a data folder. Never test against a live sprint, a
  live Jira sprint or the only copy of real data.
- Placeholders: `<TEAM>` (team folder), `<JIRA-URL>`, `<PROJECT>`, `<TEST-SPRINT>`, `<GIT-URL>`.
- Result table to hand back:

  | Step | System | Status | Message |
  |---|---|---|---|

- Pre-releases: the scripts on `main` may be older than the release under test. Use the scripts
  from the branch under test and set the version, for example
  `FORESPRINT_VERSION=1.0.0-beta.N` (see [Installation](installation.md)). Self-update does not
  offer a pre-release to a stable install, so a real update run needs two published versions (J2).

## A. Installation (P1)

Fresh machine or fresh user account, no earlier Foresprint.

| # | Step | Expected |
|---|---|---|
| A1 | Windows: run `install.ps1` of the branch under test with `$env:FORESPRINT_VERSION` set. | Archive downloaded, SHA-256 checked, program in `%LOCALAPPDATA%\Programs\foresprint`, Start menu and desktop launcher "Foresprint". If launcher creation is blocked by a policy, `foresprint shortcut` creates it afterwards. |
| A2 | macOS / Linux: run `install.sh` with `FORESPRINT_VERSION` set. | Checksum ok (with `cosign` installed the signature is checked too), program in `~/.local/bin`, launcher created (Linux: application entry; macOS: `~/Applications`). |
| A3 | New terminal: `foresprint --version`, `foresprint --help`. | Both print text, also on Windows with the window program; no console window flashes on a double click. |
| A4 | Open the launcher by double click (Start menu, desktop, and the exe in the file manager). | Window appears in front within seconds; Windows: no console window. On trouble read `start.log` (steps: program start, window created, page loaded). |
| A5 | Windows SmartScreen: download the archive in a browser, unpack, start. | The warning appears; "More info > Run anyway" works and matches the text in [Installation](installation.md). |
| A6 | macOS Gatekeeper: same with a browser download. | "Cannot verify developer" appears; both ways in [Installation](installation.md) (System Settings > Privacy & Security > Open Anyway, `xattr -d com.apple.quarantine`) work. |
| A7 | Linux without WebKit libraries. | The installer names the missing libraries and the command for the distribution; a direct start prints the missing `.so`; after installing the packages the window starts. |
| A8 | Linux without a desktop (server): command line only. | Works as described in [Installation](installation.md#linux-without-a-window-servers-ci), or `SKIPPED` if no such archive exists yet. |
| A9 | Tab completion: `foresprint completion bash` (zsh, fish, powershell). | Tab completes commands, team names, sprint ids. |
| A10 | `uninstall.sh --dry-run` / `uninstall.ps1 -DryRun`, then for real. | Dry run only lists. Real run removes program, launchers, cache; data folders, keychain entries and Git credentials stay. |

## B. First start and demo team (P1)

| # | Step | Expected |
|---|---|---|
| B1 | First start without a data folder. | Setup assistant without the sidebar; steps storage, sign-in, team, tickets, done; going back keeps input. |
| B2 | Enter the demo team. | Today shows a running sprint with numbers; no clone, nothing written to a real data folder; leaving the demo restores the previous folder. |
| B3 | Help > Guided flows: run every flow. | Highlight sits on the right element, Next/Back/End work, nothing in real data changes. A missing target shows the step without a frame (not an error). |
| B4 | Command palette (Ctrl/Cmd+K), Ctrl/Cmd+S (save and share), Ctrl+Shift+R (refresh). | Pages and tickets are searchable; the shortcuts do what the help says. |
| B5 | Personal > language German/English. | All visible text changes; no `{placeholder}` or leftover English in German mode. |
| B6 | Create a new team from scratch. | Name, first sprint id and start date accepted; Today explains what is still missing (for example people). |

## C. Existing 0.8 team (P1)

The core promise: YAML stays byte-identical until something is changed. Use a **copy** of a real
0.8 data folder.

| # | Step | Expected |
|---|---|---|
| C1 | Before opening, record checksums of all files outside `.git` (`sha256sum`, `shasum -a 256`, `Get-FileHash`). | List saved. |
| C2 | Open the copy (Settings > Storage > open folder). | Team appears, every page loads without an error, people, sprints, products, projects present. |
| C3 | Compare forecast, capacity and velocity of one finished and the running sprint with `sprintforecast forecast <TEAM>` of 0.8. | Identical; report any difference with the sprint id. |
| C4 | Only look around, then compare checksums and run `git status`. | Identical, `git status` clean. Any difference is a FAIL (attach file and diff). |
| C5 | Make one small change (an absence period) and save. | `git diff` shows only the expected lines; LF line endings, key order unchanged, no whole-file reformatting. |
| C6 | `foresprint check --strict <TEAM>`. | No errors (note warnings). |

## D. Git storage (P1)

Needs a test repository on a real server and two working copies (two folders or two machines).

| # | Step | Expected |
|---|---|---|
| D1 | Clone by URL (assistant or Settings > Storage). | "Test connection" says reachable (empty repository: a hint that it is empty); clone runs; team appears. |
| D2 | Sign in with a token. | The token goes to the system credential helper; searching the data folder and `~/.config/foresprint` for it finds nothing. |
| D3 | Change something, save (Ctrl/Cmd+S). | Commit with the name and e-mail from Settings, push succeeds, visible on the server, History lists it. |
| D4 | In copy 2 change and share; in copy 1 refresh. | The change arrives; the "n changes" count in the header is right. |
| D5 | Both copies change the same value; copy 2 shares first, copy 1 saves. | Conflicts page shows "mine"/"theirs" per value; choosing and saving finishes the merge and shares it. Check the server state. |
| D6 | Abort the merge. | Own work stays; the folder is usable again; an open merge survives a restart. |
| D7 | Two copies change different lines of the same file. | Merged automatically, no conflict. |
| D8 | Server unreachable / wrong URL / rejected token. | Distinct plain-language messages (unreachable, 401, 403); "save the address anyway" only after confirmation; local work is not lost. |
| D9 | Branch switch with unsaved changes; sharing as merge request where the host allows. | Switch is blocked with a hint; the branch is pushed and the message points to the request. |
| D10 | Repository without `.gitattributes`. | Settings > Storage offers to set line endings, shows the lines and files, writes only after the click and does not commit by itself. |
| D11 | Command line equals window: `foresprint storage`, `storage refresh`, `storage save -m "test"`, `storage history`. | Same state as the window shows. |
| D12 | Token sign-in on other hosts (self-hosted GitLab, Gitea, GitHub). | Each host accepts the token flow described in the sign-in page; failures name the host-specific cause. |

## E. Real Jira, read only (P1)

Jira Data Center with a personal access token. Never put the token, host or ticket data into team
data, docs or issues.

| # | Step | Expected |
|---|---|---|
| E1 | Settings > Tickets and tracker: Jira, `<JIRA-URL>`, query. Example: `project = <PROJECT> AND resolution = Unresolved AND issuetype not in subTaskIssueTypes() ORDER BY Rank`. | Saved without validation errors. |
| E2 | Store the token. | Input is masked; chip "token in the keychain". Windows: Credential Manager, macOS: Keychain, Linux: Secret Service; entry for service `foresprint-jira` and the host. |
| E3 | Test the connection. | Shows the account and the fields found. Wrong token: rejected (401); wrong address: not found (404); `http` instead of `https`: redirect hint. Messages are understandable and contain no ticket data. |
| E4 | Test the query. | Shows the hit count; invalid JQL shows Jira's text. |
| E5 | Field mapping (estimate, remaining, epic). | Choices come from the instance; custom fields such as an original estimate are selectable. |
| E6 | Backlog > Fetch. | Preview (new, changed, done, unassigned), "Apply" writes; order equals the Jira rank; ticket panel details match Jira. |
| E7 | A query with zero hits. | Fetch aborts with a hint; existing tickets stay. |
| E8 | `FORESPRINT_JIRA_TOKEN` set (start the app from that terminal). | Takes precedence over the keychain; the page shows the source. |
| E9 | Linux without Secret Service. | The page explains it and names the environment variable; no plaintext fallback anywhere. |
| E10 | Company network: internal CA, proxy. | CA error names `SSL_CERT_FILE` and works once set; a proxy 407 is understandable. |
| E11 | Label write-back (optional, one throw-away ticket): `write_labels` on, freeze a plan. | Only `planned_for_<sprint>` is added to that ticket; nothing else changes. |

## F. Jira write-back of the planned sprint (P1)

**Only against a test sprint with throw-away tickets.** This is the only place where Foresprint
changes Jira, so it gets the most care.

What the feature does (so a tester knows what a deviation is):

- It moves tickets between Jira sprints and the backlog, and **nothing else**. Rank, estimate,
  status, texts, fields and labels are never written. Jira sprints are never created, started or
  closed; closed sprints are never written to.
- It is off unless `tracker.write_sprint: true` (Settings > Tickets and tracker > write the
  planned sprint back). Source must be Jira.
- It runs only on an explicit click, after a preview, with a per-ticket opt-out. Nothing is
  automatic.
- It needs a frozen plan and a sprint that has not started.
- Two kinds of moves: committed tickets that are not yet in the Jira sprint go in; tickets in the
  Jira sprint that were taken out during planning go to `tracker.removed_target` (`backlog`, the
  `next` sprint, or a `pro_forma` sprint). Done tickets are never touched.
- The plan is rebuilt from a fresh read of Jira just before writing, and only tickets that were
  shown and left ticked are written.
- Jira calls: reads `GET /rest/api/2/search` and (with `tracker.board_id`)
  `GET /rest/agile/1.0/board/{id}/sprint`; writes
  `POST /rest/agile/1.0/sprint/{id}/issue` and `POST /rest/agile/1.0/backlog/issue`, in batches,
  one request per target. The client allows no other write on this path. The first error stops
  the run; what went through stays undoable.
- Undo puts the moved tickets back where they were, as long as the program was not restarted (the
  list is kept in memory) and the earlier sprint is known and not closed.

| # | Step | Expected |
|---|---|---|
| F1 | Switch the option on, set `board_id` and the removed-target choice, save. | The chip changes from "Read only" to "Writing back on"; `team.yaml` gains exactly these keys. |
| F2 | Prepare Jira: a future (not started) sprint `<TEST-SPRINT>` on the board, 3 to 5 throw-away tickets in the backlog. Use the same sprint id or a `tracker.sprint_names` mapping in Foresprint; fetch the tickets. | Tickets show in the Backlog. |
| F3 | Open the write-back card before freezing the plan. | Writing is not possible; the page says the plan must be frozen first. |
| F4 | Freeze the plan with some of the tickets, open the preview. | One row per move with from, to and reason; single tickets can be unticked; nothing is written yet. |
| F5 | Preview with no matching Jira sprint (wrong name/mapping) or a closed sprint. | A problem text explains it; no moves are offered. |
| F6 | Write only one or two tickets. | In Jira only the sprint of those tickets changed. Rank, estimate, status, texts, labels unchanged; no sprint created, started or closed. Unticked tickets did not move. |
| F7 | Undo. | Tickets are back in their earlier place in Jira. After an app restart Undo is no longer offered (expected). |
| F8 | Take a ticket out of the sprint in Foresprint that is still in the Jira sprint; open the preview. | A move to the configured removed target is offered; after writing, Jira shows it there. |
| F9 | Change a ticket in Jira by hand between preview and write. | The write uses the fresh state: no ticket is moved twice, no stale move is applied. |
| F10 | A sprint that has already started. | The message says the plan can no longer be written. |
| F11 | Token without the right to edit sprints. | Plain-language 403; the run stops; the card says what, if anything, was already written. |
| F12 | Work-package or CSV team. | The option is not offered or says it works with Jira only. |

## G. Work packages and spreadsheet import (P2)

Use a test file with invented data (title, status, type, priority, assignee, product, project,
estimate, labels, description).

| # | Step | Expected |
|---|---|---|
| G1 | Choose the ticket mode "work packages in Foresprint". | Explanation of what is off (no fetch, no links, no assignment rules); new items get keys `AP-1`, `AP-2` and can be created and edited by hand. |
| G2 | Import a CSV (comma, and once semicolon; UTF-8 with umlauts). | Preview shows every change before anything is written; an existing key is updated, a new one appended. |
| G3 | Import the same table as `.xlsx`. | Same result as CSV; fields outside the table are kept. |
| G4 | Broken files: missing required column, duplicate keys, empty file, wrong format. | Plain message, nothing written. |
| G5 | Mode "no tickets". | Pre-planning and planning work with amounts per product; the Backlog page is absent or explains why. |
| G6 | CSV export of a Jira team imported instead of fetching (optional). | Same preview, no network needed. |

## H. Pages walk-through (P2)

On the demo team or a copy. Per page: loads without an error, numbers plausible, usable by
keyboard, readable in light and dark.

| # | Step | Expected |
|---|---|---|
| H1 | Today. | Running sprint, "next" hints, links lead to the right page. |
| H2 | Backlog. | Views and filters, search, a long backlog scrolls smoothly, ticket panel, ordering by drag and by Alt+arrow, earmarking, presentation view (Escape ends it). |
| H3 | Sprint overview and Prepare. | Absence grid (person by sprint), period entry, announced/confirmed per cell, capacity freeze, readiness check. |
| H4 | Pre-plan. | What-if card, earmarks per sprint, table per product, plannable amount = floor((PLAN - carry-over) x plannable share). |
| H5 | Plan. | Two lanes with drag and buttons, sum bar, product against budget, project against contingent. Deviations warn and never block. |
| H6 | Review and Minutes. | Velocity, scope creep, frozen capacity, minutes file written and readable. |
| H7 | Forecast. | Chart, range, trend, products over time, report/export, "When will it be done?"; Calculations show their steps; the personal display mode (off, icon, always) works. |
| H8 | Projects. | List, timeline, milestone light, contingent in person days with consumption, closing a project, ending a product. All are recommendations; nothing blocks. |
| H9 | Team: people, products, calendar. | Member/guest/external (external needs an end date), membership periods, product rules editor, sprint naming with preview and duplicate warning, estimate unit with factor, undo of a single change. |
| H10 | Privacy of absences. | Only periods and days are stored or shown. No absence type (vacation, sick, ...) anywhere: form, file, export, minutes, tooltip. |
| H11 | Settings: Team and Personal. | Changes apply at once; `team.yaml` receives only changed keys; theme, density, language, calculation display apply. |
| H12 | Data: overview, conflicts, history and tags. | Overview counts open changes; History lists commits with author and sprint tags `TEAM/SPRINT` for closed sprints. |

## I. Spreadsheet round trip (P2)

| # | Step | Expected |
|---|---|---|
| I1 | `foresprint excel <TEAM> --output test.xlsx`. | Opens without a repair message in Excel and LibreOffice; formulas are live; values equal the window. |
| I2 | Change a yellow cell, `foresprint excel-import <TEAM> test.xlsx`, then `--apply`. | The preview names exactly that cell; apply writes it; fields the workbook does not hold (product owner, estimate unit, sprint naming, person kind, pre-plan details) stay unchanged. |
| I3 | Export and re-import without a change. | No changes reported; team file checksums unchanged. |
| I4 | Put a `.xlsx` into the data folder. | `.gitignore` applies; the app does not commit it. |

## J. Self-update (P2)

| # | Step | Expected |
|---|---|---|
| J1 | `foresprint update --check` on a pre-release install. | Runs without an error; newer pre-releases are offered, a stable install is not offered pre-releases. |
| J2 | Real update run (needs a newer published version, else `SKIPPED`): `foresprint update`, or Settings > Updates. | Checksum verified, program replaced, `--version` shows the new version; on Windows the window must be closed first. A failed check leaves the old program. |
| J3 | `foresprint update --auto notice\|on\|off`, and `FORESPRINT_AUTOUPDATE`. | The choice is remembered; the variable wins and the page says so; with `off` there is no check and no notice. |

## K. Platform and look (P3)

Once per operating system if possible.

| # | Step | Expected |
|---|---|---|
| K1 | Dark theme: system, light, dark. | Every page, dialog, chart and traffic light readable (dropdown lists included); no white flash at start in dark; switching the OS theme follows in "system". |
| K2 | Keyboard and focus. | Sensible tab order, focus always visible, every drag has a keyboard alternative, colour is never the only signal. |
| K3 | Window sizes and scaling: about 1000 px wide, maximised, 125% and 150% scaling, a second monitor. | Nothing cut off; tables scroll inside themselves. |
| K4 | Folder dialog and paths: spaces, umlauts, a long path, a network drive (Windows). | The system dialog opens and remembers the choice. |
| K5 | Speed. | Window in a few seconds, page changes feel instant, a backlog of over 1000 tickets stays smooth. |
| K6 | Windows console: `foresprint check <TEAM>` from PowerShell. | Output shows; scripts use `Start-Process -Wait` where they need to wait. |
| K7 | macOS, Apple Silicon and Intel. | Starts, Dock name "Foresprint", menu bar, Cmd instead of Ctrl. |
| K8 | Linux: Wayland and X11. | Window, clipboard, file dialog, application entry with icon. |
| K9 | No internals. | No names of real teams, companies or people in the UI, help, examples or error texts (own data excepted). |
| K10 | Browser mode (`foresprint serve`, "show in the browser" in the window). | The page works like the window on this computer only; with the window open, calls that switch the data folder or demo are refused in the browser; note whether a change made in one shows up in the other and how (report as NOTE). |

## After the run

Every `FAIL` becomes a small issue or PR with the step number, system, exact message and, where
relevant, `start.log`. Extend this plan whenever a feature gains behaviour that only a real server
or operating system can show.
