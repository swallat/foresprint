# Design: Core improvements (without a ticket system)

Status (as of 19 October 2026, after #108): Phase P (except for the stopwatch acceptance in the browser on
the owner's computer), K1 to K3 as well as A14, A15, B8 and B9 are
implemented; for details see the “Status” column of the tables and section G. Still open are
B10 (only in the web interface), the setup wizard (C) and the remainders listed in the
tables. Outside these phases, the following have been added since: sprint logs per meeting with a
lock against concurrent writes (#84, #90), Excel export and import per team (#86, #91) and
the more precise classification of Git errors (#81); the ticket system follows in a design document of its own. This document collects everything that applies **independently of a ticket system**:
calculation, operation, setup, data folder and synchronisation.
The ticket integration is described in [ticket-planning.md](ticket-planning.md); it is
optional and builds on these points (in particular A and D).

The points come from two independent critical reviews of the existing product. They were
initially **recommendations**; what has been implemented from them is shown in the “Status” column. The priority is
that of the reviewers (critical / important / nice-to-have). The status was checked in October 2026 against code,
tests and help texts; where it reads “partially”, the column names the remainder.

## Principle

The system must work completely **without** a ticket system. Everything in this document is
unaffected by that.

## A. Calculation

| # | Item | Priority | Recommendation | Status |
|---|---|---|---|---|
| A1 | The default trend (`classic`/`linear`) extrapolates noise, can fall or become negative, and lies below its own range from the third future sprint on. | critical | `flat` (or median) as default; `classic`/`linear` only when explicitly chosen, with a warning; catch negative results | implemented. Remainder: teams with a saved `classic` stay on it (warning only); in the running sprint, plan and range were calculated with different sprints – fixed (“plan within the range”, decision 18 Oct 2026): `normalized_history` and `sample_count` count the same values as the plan, i.e. also the already recorded review value (velocity) of the running sprint; `sample_count` is capped at `forecast.window` and the “little data” threshold stays fixed at 5 (`MIN_SAMPLES`); the simulation still needs at least two values. Consequence: teams with `window < 5` always see the “Little data” note; if the window actually cuts off values (`available_count > sample_count`), the sentence names both numbers (“only 3 of the 12 recorded sprints”) and adds that the forecast window is set small; if there simply are no more values, this addition is missing (if that is a nuisance, owner's decision: threshold `min(5, window)` or a separate note). The gap note uses the same sprints as the calculation. “No forecast yet” depends on `available_count` (all available values, uncapped), not on the capped sample `sample_count`; with `window` 1 or 2 the message therefore no longer appears next to an existing forecast once three values are recorded. With exactly two values it still appears although the engine already calculates (fixed threshold `MIN_THIN_HISTORY` = 3, was already so before; not part of this change). Consequence for the displayed range of the running sprint: with a recorded velocity it contains its own review value (example 10, 12, 8, 14, 11 and running sprint 30, capacity 40, window 5: range 8/12/30 instead of 8/11/14); there the commitment is shown as the plan (source IST). That is decided. Only the range, the sample count and the simulation between review and sprint end have changed; the forecast of completed sprints remains. Open: (1) the running sprint itself has, with a recorded velocity, the commitment as plan (source IST) and can lie outside the range; (2) the guarantee “plan within the range” holds up to and including the running sprint: the engine also averages in a future sprint with a recorded value (import/file), the range does not count it (example 10, 12, 8, 14, 11, running sprint without a value, following sprint with velocity 60: plan 21.0, range 8–14; decision open); (3) `classic`/`linear` remain a known remainder |
| A2 | Without confirmed absences and without `absence_history`, the **capacity** is extrapolated by trend although people, public holidays and sprint length are known. | critical | Capacity always from calendar and people; estimate only the unknown absences (`absence_history` with a sensible default); trend only for teams without a people list | implemented (calculation; the three help texts tooltip “Capacity”, note for `capacity` and “Reset absences” have named calendar and people since #67). Remainder: the table of `capacity` shows absences 0 for sprints without a file, without the estimated deduction (display, decision open) |
| A3 | The point value is shown on the main page without uncertainty; “85 % certainty” is too strong with few values; Monte Carlo already runs with two measured values. | critical | Range and sample size directly at the forecast tile; warning with little data; wording “model-dependent frequency” | largely implemented: forecast page; since #66, planning (step 2), the line “… fit into the next sprint …” on the absences page and the tiles of the pre-planning also show the range with sample size (with fewer than five sprints with the addition “little data, rough hint”), the command line (`forecast`) and the report a “Range” column for future sprints; CLI and report also warn with little data (K1); since #77 `analysis --remaining` warns with fewer than five samples. Remainder: the wording “model-dependent frequency” and the question whether the minimum of the simulation (calculates from two values on) is raised are not checked or open, respectively; the warning of `analysis --remaining` counts the sample capped at `window` (always with `window` below 5, decision open) |
| A4 | With exactly `window` sprints of history, `classic`/`linear` deliver no forecast; `rolling_average` counts positions instead of values, gaps are silently skipped. | important | Fallback to `flat` with the note “thin history”; a uniform rule for gaps, made visible | implemented. Remainder: the gap note appears only in the web interface |
| A5 | The absence history skips confirmed zero sprints and thus distorts the rate; it does not use the same definition as `absences_known`. | important | use the same definition; show the sprints actually used | implemented. Remainder: older sprint files with velocity but without recorded absences count as “nobody was absent”. Decision 18 Oct 2026: the rate is marked as uncertain (`AbsenceHistory.derived`; absences, forecast, pre-planning and planning pages, calculation, report, command line), no number changes. The note is an information (not a warning), names the sprints including their duration (until they drop out of the window of the last `absence_history` sprints or absences are entered) and explains why the “Absence status” table shows them as confirmed; outside the absences page there is only a short reference. Open (separate owner decision): an explicit “Nobody is absent” is not stored for such sprints (the derivation yields the same), the note can only be removed there by recording absences or by the sprints dropping out of the window |
| A6 | Part-time and working week: whoever enters an 80 % position with four full days as `workweek=mon,tue,wed,thu` and `fte=0.8` is deducted twice (8 × 0.8). | important | Define the meaning of FTE and explain it with examples (FTE = share of the working days of the person or of the team) | partially: meaning defined and explained in the help; the column help of the FTE and the CLI text still contradict each other |
| A7 | With FTE changes within the sprint, absences are weighted with the average FTE (approximation). | important | make the approximation visible | implemented |
| A8 | Overhead: fixed overhead days replace the percentage deduction (README describes them as additional); with expected absences the order is calculated differently. | important | one common calculation for confirmed and expected absences; align README | implemented |
| A9 | The buffer recommendation compares different reference quantities (scope creep relative to what was planned, small items relative to the total forecast). | important | use the same reference quantity | implemented |
| A10 | Product shares: two fixed shares of 60 % each are not rejected; missing done values count as 0 in the balance. | important | sum check; distinguish “missing” from “0” | implemented: web interface; since #78, command line (`products`) and report hide products without a value in the period and show the “no value” column when values are missing, since #95 with a footnote. Remainder: a hidden product (no sprint with a value) no longer carries its note, as in the web interface |
| A11 | Production access: “nobody marked” is `None`, not 0; the translation into delivery quantity is rough. | important | distinguish unknown configuration from missing authorised people; mark as a bottleneck hint | implemented |
| A12 | The statement “focus factor is comparable between teams” is wrong for story points. | important | remove the statement | implemented |
| A13 | The reference capacity cancels out in the calculation and is only a display scale; focus factor and normalized velocity are the same quantity under two names. | important | remove or explain the reference capacity; one normalized quantity | partially: the help explains the reference capacity; README does not yet say that it cancels out; two names for the same quantity remain |
| A14 | Rounding: `round_down` everywhere is a systematic bias; the capacity is rounded down and then used as a denominator. | nice-to-have | round only at output; justify the deliberate choice in the help text | implemented (#52, #54) |
| A15 | `trend()` compares with `is TrendMode.X`; a string ends up in the `linear` branch. | nice-to-have | convert the value to `TrendMode` at the start | implemented (#50) |
| A16 | Definition of “done”: partial shares of open tickets count (team practice). Without documentation the number is not comparable between teams. | important | Record the definition in help and README. A cut-off date for a change of the counting method (like `unit_since`) is only needed for teams that change their counting method, and is therefore later and optional | implemented |

### Tests (part of K1)

The existing consistency tests remain (strength: pages do not diverge), but they only check
whether the implementation agrees with itself. In addition there are **domain tests**:

- Property tests: constant velocity yields a constant forecast in every trend mode; the plan
  lies within the range; a sprint with public holidays has less capacity than a normal sprint; more
  people never yield less capacity; edge cases “exactly `window` sprints”, FTE 0, empty
  history, different sprint lengths; the forecast is never negative.
- Retrospective check (backtest): for every sprint of a history, a forecast is made with the data
  available at the time and compared with the actual value; the modes are
  compared against a simple constant forecast (mean/median of the last values). As a
  test with synthetic series (stationary, trend, jump) and the demo history. The
  hit rate of claimed probabilities is a goal for long histories, not a
  prerequisite for K1.
- Hand-calculated examples for public holidays, FTE, overhead and absences remain as a model.

## B. Operation and terms

| # | Item | Priority | Recommendation | Status |
|---|---|---|---|---|
| B1 | “Forecast PLAN” means, depending on the page, the current calculation or the frozen state. | critical | show “Current forecast”, “Forecast at planning” and the difference everywhere | partially: planning and pre-planning show “Forecast at planning” with the difference; the forecast tiles name the frozen state only in the tooltip (the table below shows state and difference); CLI and report without “Forecast at planning” |
| B2 | “Continue without an entry” in the planning silently sets absences to “nobody is absent”; unknown and 0 are too easily confused. | critical | explicit state per sprint (unknown / expected / confirmed) instead of the file heuristic; explicit confirmation “nobody is absent” | partially: state per sprint implemented; with “unknown” the review freezes the full staffing without a note |
| B3 | “Forecast IST” is the commitment at sprint start, not a result. “Roadmap” denotes a reserved share. “expected” and “anticipated” absences are two mechanisms with almost the same name. | important | e.g. “commitment”; rename the “Roadmap” share; make the two absence terms distinguishable | partially: “Forecast IST” is now called “Commitment”; “Roadmap” is now called “Plannable share” (remainder: “Small items”; decided October 2026); only the display name changes, the key `roadmap_share` remains |
| B4 | 15 to 16 pages with competing paths (product values on “Product distribution” and on all boards; sprint selection inconsistent). | important | Entry via tasks (“Prepare sprint”, “Planning”, “Close sprint”); product distribution as an evaluation; master data under “Manage team” | implemented (#43) |
| B5 | Uncertainty is shown away from the decision (“Analysis” page). | important | Range, sample size and capacity source directly at the tile | largely implemented: range with sample size at the tiles of the forecast page, since #66 also in planning step 2, absences and pre-planning; the command line (`forecast`) and the report show a “Range” column since #66, they name the sample size only in the warning with little data (K1) or in the section “Additionally: range”, respectively. The capacity source is shown at the tiles of forecast, planning step 2 (since #66) and pre-planning as well as in the command line and report (with a warning line for an uncertain source). Remainder: the `forecast` table and the forecast table of the report do not name the sample size; on the absences page (line “… fit into the next sprint …”) the source is missing, and planning step 1 (Known absences) shows neither range nor source at the tiles |
| B6 | The formula view does not show the numbers used; the formulas of the trend modes are hard to read for non-experts. | important | short explanation in everyday language, the values used and sources expandable | partially: explanation in everyday language is there; the numbers used are missing in the popover |
| B7 | Getting started requires a Git repository and 6+ reviews before a forecast appears. | important | Forecast already from 2 to 3 sprints (`flat`) with the note “thin history” | implemented |
| B8 | The what-if panel exists twice with slightly different text; the forecast history is an audit log with 8 columns. | nice-to-have | one place; the last forecast and the deviation in the review are enough | implemented (#51) |
| B9 | Sprint calendar texts claim Mon–Fri despite a configured working week; absences in “days” (half-time employee) are misleading. | nice-to-have | adjust texts; add column help | implemented (#51) |
| B10 | Actions “Change FTE” and “Record leaving” instead of manually splitting rows. | nice-to-have | later | partially: command line implemented (`people`: actions n = new person, f = change FTE, a = leaves the team); the web interface still requires splitting the rows manually |

## C. Setup

- The steps team, calendar, capacity, forecast, people and products exist as pages, and
  the start page guides through the sprint via tasks (“Prepare sprint”, “Planning”, “Close sprint”)
  (implemented, B4). A continuous setup wizard with a short explanation
  per step and a summary is a possible later goal (open), but not a
  prerequisite for the other points.
- Sensible defaults instead of many switches; show dependent settings only when needed;
  reject invalid combinations. Status: the defaults apply (flat trend, four sprints of
  absence history, rounding only at output); but the settings form still shows all
  fields flat, and the command line checks combinations only after saving.

## D. Data folder and synchronisation

- The app can switch the data folder during operation (“Data folder” page: choose, create,
  clone). It shows the active repo, branch and team permanently, offers the most recently used
  folders as a switch and discards the old form states on switching (implemented).
- Whoever uses the app for a team without shared product owners uses a data repo of their own.
- Absences per person are accessible to POs because they are part of sprint planning.
- **Synchronisation via Git** (implemented, except for item 6). Minimum scope so that it is
  suitable for everyday use by non-technical people as soon as several people work on the same data repo:
  1. A “Save and share” button (pull, commit, push) with a display of the state (ahead,
     behind, offline) and of the changes of others since the last load.
  2. Detect outdated forms before saving; secure own changes before
     synchronising.
  3. Detect conflict files **before** the YAML is loaded; the affected editing is
     locked, a guided recovery is offered.
  4. Merging at key level (different keys of the same file are
     united); only real value conflicts go to the human, in the app with “my/other
     change”, after which the data check runs.
  5. Write files in a stable format and sorted so that conflicts become rare. Since #79
     the template and the creation include `*.tmp` in the `.gitignore` (the app also creates it in
     an existing folder, but only if it is missing) and a `.gitattributes` in the
     data folder (`*.yaml`, `*.yml`, `*.md` with `text eol=lf`), which is only created when a
     repository is newly created. Remainder: an existing `.gitignore` without `*.tmp` stays unchanged,
     and existing repositories and clones without `.gitattributes` remain unprotected (the app
     deliberately does not create it there; whether it should offer to is open).
  6. Set up the Git sign-in separately (credential manager, SSH prompts, file locks,
     line endings under Windows). Partially: the app detects a missing sign-in and explains the
     next step; a sign-in of its own in the app deliberately does not exist.
- A reachable Git contact person is helpful, but does not replace the terminal-free
  acceptance test: it is carried out with two people working at the same time and deliberately created
  conflicts.
- “One sprint per file” keeps conflicts rare only if one person writes per sprint.
- After every merge the full validation runs: a key merge can technically
  succeed and be invalid in terms of content (two people change different product shares that
  add up to 120 %). This includes secured local changes, abort and resumption
  as well as handling of renewed changes on the remote at push.

### Scope: all everyday Git operations without a terminal

The goal is that a person can maintain the data repos completely from within the app. In addition to
“Save and share” and conflict resolution, this includes:

Status per operation:

- **Discard changes** (a single file or everything), with a confirmation prompt and a display of what is
  lost (implemented).
- **History** per team, sprint or file (who changed what and when) and restore an earlier
  state; the restoration is itself a change and can be undone.
  Partially: deleted files cannot be restored individually, and the history shows
  only the last 40 entries.
- **Tags**: manage, not just set (show, set retroactively, delete; implemented).
- **Data folder**: choose, create, clone and switch between most recently used folders
  (implemented). This includes the **server (remote)**: enter or change the address, validate it and
  check the connection (`git ls-remote`) instead of calling `git remote` in the terminal
  (implemented). Credentials never belong in the address and are not stored or
  displayed. The app does not generate SSH keys; it changes the global Git configuration only
  on click, and only for the name and e-mail of the commits (when Git does not know the name or e-mail).
- **Sign-in help:** detect missing authentication and explain comprehensibly what to
  do (store an access token or SSH key, credential manager). Partially: when cloning
  and creating a data folder the sign-in note is still missing.
- **Error states** with clear messages and the next step: offline, push rejected, Git
  not installed, repository not found (404, “Repository not found”), unrecognised
  certificate, non-writable folder (`not_writable`), unsafe folder (“dubious
  ownership”, `unsafe_directory`: explanation only, the app changes no Git settings) and the
  unknown SSH fingerprint have been classified individually since #81, also for sync, upload,
  cloning and tags. Locked file, incomplete merge and detached HEAD only partially (the
  note for `locked` still mentions the `index.lock` for “unable to unlink” / “Device busy”);
  a bare “Could not read from remote repository” and “unable to access … 503” still count
  as “offline”. “Back to the branch” secures open changes in the data folder before the
  switch as a commit of its own on the rescue branch (`rettung-<date>`) and names it in the
  success message; the app does not touch changes outside the data folder (separate
  note, the backup remains). Write and read errors of the
  data files (no write permission, file locked) have shown a message with file,
  cause and next step since #63, as has an invalid structure of the YAML files since #64. Still open
  are creating and cloning a data folder in a non-writable folder and a
  non-readable data folder.
- The app continues to call the `git` program (no Git library of its own): this uses the
  sign-in of the computer and is more stable. If Git is missing, the app explains the installation.

Deliberately not part of the app: branches, rebase, force push, stash, submodules and the like. The
model remains “one branch, always keep in sync”. Whoever needs more uses a terminal or
a Git client.

Acceptance: all the everyday operations mentioned work in a test with two people and
deliberately created conflicts without a terminal, including the error cases (offline,
rejected push, missing sign-in). Status: the individual steps are tested separately (sync,
conflicts, history, data folder, remote) and the browser tests in `tests/e2e` operate the app
with two clones against a shared repository; a continuous acceptance scenario for all
error cases does not exist yet.

## E. Performance (phase P)

The application is primarily a GUI and feels slow. Two independent
measurements (Windows, Python 3.14, demo team with 22 sprints and 25 YAML files) show: the
calculation core takes about 0.25 to 1.3 ms, loading a team about 18 ms. The slowness arises
before and after the calculation, not in the language. Not measured: browser start,
frontend rendering and round trip.

Measures (in this order):

1. The update display no longer waits for the background thread (`result(wait=4.0)` otherwise
   potentially blocks every run for up to 4 seconds); the result appears on the next
   run.
2. The Git status is not queried on every run but briefly cached and
   invalidated after saving, commit and synchronisation (measured: median about 61 ms).
3. The team is cached by file version (including new and deleted files),
   the forecast additionally by data state and as-of date; after saving and synchronisation it is
   reloaded. Pages load only what they need.
4. YAML with the C loader, if available (measured: about 18 down to 6 ms).
5. `pandas`, `altair` and the CLI imports are only loaded where they are needed (around
   1 to 1.5 seconds of cold start).
6. Independent areas as fragments, bundle inputs in forms.

Goals: start under 3 seconds, normal inputs under 200 ms. Before and after, measurements are taken with a
stopwatch on a normal work computer; the measurement log is part of the PR.

Status: all six measures are implemented (details and measurement logs for cloud and
Windows in [performance.md](../performance.md)). In the Python process, page construction and repeated
runs on the owner's computer take 16 to 46 ms. The only open item is the stopwatch acceptance in the
browser on the owner's computer (start under 3 s, normal inputs under 200 ms); it
will be done later on request. Deviations from the plan: the forecast is not
cached (the calculation takes 0.3 ms, a copy would be slower), and only the calculation and
the what-if panel of the forecast page run as fragments; in the other areas a form would remove
the live preview.

## F. Technology

Assessment by two independent reviews:

- **Python stays.** The core is pure, tested Python; the public holiday library `holidays`
  (around 200 countries with regions) has no equivalent counterpart in Rust or Go. A rewrite
  in Rust or Go would cost several months and would not fix the slowness, because it lies in the
  architecture (recalculation, loading, calls). A ready-made table editor is missing there too.
- **Streamlit stays for now.** For tables, forms, charts and sprint columns with
  selection fields it is sufficient. Limits: re-execution of the page on every input, state handling,
  drag and drop, window behaviour.
- **Alternative: NiceGUI** (event-driven, tables with AG Grid, charts with ECharts,
  native mode). Further candidates: PySide6/Qt; for mandatory drag and drop or roadmap
  FastAPI with Vue/React; with simultaneous collaboration as the main benefit a shared
  server web app.
- **Technology gate** (originally after phase P, before K2 and K3; settled by the decision below,
  the NiceGUI spike is dropped): the measured times would have been checked against the goals from E
  and exactly one critical workflow (absence matrix, forecast tile, a
  utilisation bar, unsaved draft, repo switch) built and measured as a NiceGUI spike.
  If Streamlit meets the goals, it stays. If it fails because of the interaction architecture,
  migration takes place step by step; the core logic remains unchanged in the process. Rust or Go only when
  representative profiles show real CPU bottlenecks.
- **Decision (owner):** Streamlit stays for the time being. A switch will only be considered when it
  becomes necessary (concrete problems from user tests or a hard requirement such as drag and drop). Until then,
  further time measurements are dispensed with.
- Additionally: define a tested release combination of the dependencies. The lower bound
  `requires-python` will be decided separately.

## G. Phases and order

The ticket pre-planning (see [ticket-planning.md](ticket-planning.md), version 6) begins
after release 0.6.0 (the PR wave of October 2026 is merged). It builds only on Forecast PLAN, the
default distribution per product and the production access, all of which exist; the core remains
fully usable without a ticket system.

| Phase | Content | Acceptance criterion | Status |
|---|---|---|---|
| **P Performance** | Section E | Measurement log before/after; goals from E achieved or remainder named | completed (#34); remainder: only the stopwatch acceptance in the browser on the owner's computer (`docs/performance.md`), done later on request; further measurements are dispensed with according to the decision in F |
| **K1 Calculation and states** | A1 to A6, A8, A10, A16, B1, B2 including domain tests (property tests, backtest) | All domain tests green; the plan lies within the range; unknown and confirmed absences are distinguishable | merged (#35); remainders see tables A and B |
| **Technology gate** | Section F | Measurement on a work computer; decision stay/migrate documented | decided: Streamlit stays, the spike is dropped (section F) |
| **K2 Terms and display** | B3 to B7, A7, A9, A11 to A13 | A person without instruction enters absences and sees how much fits into the next sprint | merged (#36); remainders see tables A and B |
| **K3 Data folder and sync** | Section D including the scope “everyday Git without a terminal” (several PRs) | Two people work in parallel, including deliberate conflicts, without a terminal and without data loss; all everyday operations and error cases work in the app; after every merge the full validation runs | merged (#38, #39, #40, #42, #44, #45, #48, #53); remainders see section D |

The remaining items (A14, A15, B8, B9) were implemented along the way; B10 is implemented in the command line, in the web interface it is still outstanding.
