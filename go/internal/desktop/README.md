# The window of Foresprint

A Wails (v2) shell around a Svelte 5 + TypeScript frontend, built on the Go core. The command
line and the window are one program: `foresprint` without arguments (a double click) or
`foresprint gui` opens the window; every other command works as before.

```
desktop.go            Wails shell (build tag "desktop"): window, embedded frontend, bindings
frontend/             the web frontend (Vite, Svelte 5, TypeScript, Vitest)
../app/               the bindings: Go methods the frontend calls (no window code, tested without cgo)
../cli/gui.go         hook: cli.GUI opens the window (set by cmd/foresprint/gui_desktop.go)
```

## Why this stack

- **Svelte 5 + Vite + TypeScript.** The mocks are plain HTML with small view functions; Svelte
  components are the same shape with real reactivity, compile to little code (about 35 kB gzip
  for the whole shell) and need no virtual DOM, which matters for the long ticket lists and the
  100 ms budget of `docs/redesign/plan.md`. A router and state are ~150 lines of our own, so the
  dependency list stays at Svelte and nothing else at run time.
- **Wails v2.12.** The stable line that builds with the Go version of the core (v2.13+ needs Go
  1.25, v3 is still beta). Moving to a newer Wails is a change in `go.mod` and `desktop.go`
  only; the frontend does not know Wails except in `src/lib/api.ts`.
- **Fonts and icons are bundled** (Iosevka, Iosevka Aile, Material Symbols as SVG): no web
  request at run time.

## Work on the frontend

```
cd go/internal/desktop/frontend
npm ci
npm run dev          # browser, with the demo team from src/lib/mock/ (no Go needed)
npm run check        # svelte-check (types) + every text has its German translation
npm test             # router, route table, contrast of the design tokens, ...
npm run build        # to dist/, embedded by desktop.go
```

The program with the window (Linux needs `libgtk-3-dev libwebkit2gtk-4.1-dev`):

```
cd go
go build -tags desktop,production,webkit2_41 -o foresprint ./cmd/foresprint   # Linux
go build -tags desktop,production -o foresprint ./cmd/foresprint               # Windows
CGO_LDFLAGS="-framework UniformTypeIdentifiers" go build -tags desktop,production -o foresprint ./cmd/foresprint   # macOS
```

Without the tag `desktop` nothing of this is compiled: `go build ./...` and `go test ./...` need
neither Node, cgo nor a web view. CI builds and starts the program on all three platforms (job
`desktop`).

## How a page is built

- A page is one file in `frontend/src/pages/<area>/`. `src/lib/routes.ts` maps addresses to the
  files and holds the navigation; a page package replaces the placeholder in its own files and
  does not need to touch `routes.ts` unless it adds an address.
- Data comes from Go through `api` (`src/lib/api.ts`). Every area has its own files, so that
  packages do not meet in the same file; the shared files only collect them. A method is added
  in these places, all of them in files of your area (`<area>` is one of `backlog`, `data`,
  `forecast`, `help`, `plan`, `projects`, `settings`, `sprints`, `team`, `today`):
  - Go: `internal/app/api_<area>.go` (methods of `API`), types in `types_<area>.go`. The files of
    one package share a namespace: every unexported name in these files starts with the area
    (`planRound`, not `round`); `names_test.go` enforces it. Exported names stay unique too.
  - Types of the call: `src/lib/types.<area>.ts` (the interface `<Area>Api`; `api.ts` already
    includes every area).
  - Browser answer: `src/lib/mock/<area>.ts` (`export default` an object with the methods; the
    demo state shared by areas is in `mock/shared.ts`). `mock/mock.test.ts` fails when a Go
    method has no answer.
  Arguments and results are plain JSON; an error becomes a rejected promise with a text for
  users. Touch `api.ts`, `mock/index.ts` and `icons/index.ts` only for a new area or a method of
  the shell itself.
- Shared state (team, sprint, status, toasts, ticket panel) is `app` in `src/lib/app.svelte.ts`.
  Do not keep a second copy of it; use `toast()`, `openTicket()`, `save()`.
- **Texts**: `t('English source text', { name })`. The key is the English text. The German
  translation goes to the file of your area, `go/internal/i18n/data/de.ui.<area>.json` (same
  format as `de.ui.json`); a text used in several areas lives in `de.ui.json`. `npm run check`
  fails when a text is missing, unused or in two files. Texts that only exist in Go (messages of
  `internal/app`) go to `de.<area>.json` (for example `de.plan.json`), not to a shared file.
  Never build a sentence from pieces; use placeholders.
- **Look**: tokens in `src/styles/tokens.css` (from `DESIGN.md`), shared classes in
  `src/styles/base.css` (names as in the mocks, so a mock view ports without renaming). New
  styles go in the component's `<style>`; changes to tokens or base classes are their own small
  PR. The contrast test (`tokens.test.ts`) measures both themes: text 4.5:1, control edges 3:1.
- **Icons**: `<Icon name="..." />`, flat Material Symbols. An icon that is not yet in
  `src/lib/icons/core.ts` or another area file goes to `src/lib/icons/<area>.ts` (one import
  line and one entry, see the comment there). No emojis anywhere.
- **Rules that hold everywhere**: dark and light, keyboard use and visible focus, colour never
  the only signal, drag and drop always with a keyboard or menu alternative, no leftover
  internal names or real people in code, mocks and examples (use the demo team), absences are
  stored and shown as periods only, never with a type.

## Work packages (independent pages)

Each package owns its page files and its `internal/app/api_<area>.go`. Shared components that
another package needs are named below; the owner builds them first and merges them early.

| Package | Pages (files in `src/pages/`) | Needs from Go | Notes |
| --- | --- | --- | --- |
| P1 Backlog | `backlog/Backlog`, `backlog/Present`, `backlog/TicketPanel` | ticket list and order, earmark, ticket details (`sources`, `ticketimport`) | virtual list, drag and drop with keyboard alternative, filters; presentation view |
| P2 Sprint workspace | `sprints/Sprints`, `Prepare`, `Review`, `Minutes` | sprint data, absences, review figures, minutes files | owns `lib/absences/AbsenceGrid` (used by P5) |
| P3 Pre-plan and plan | `plan/Preplan`, `plan/Plan` | pre-plan, planning, product table, plannable amount, write back | owns `lib/ui/CapacityBar` |
| P4 Forecast and calculations | `forecast/Forecast`, `help/Calculations` | forecast, trend, history, export | owns `lib/calc/Calc` (calculation shown next to numbers per the personal setting); chart components |
| P5 Team | `team/People`, `Products`, `Calendar` | people, membership periods, products, rules, sprint calendar | owns `lib/rules/RuleEditor` (used by P6 and P8); absence periods per person |
| P6 Projects | `projects/Projects`, `ProjectDetail` | projects, milestones, contingents | uses `RuleEditor` |
| P7 Data and storage | `data/Overview`, `Conflicts`, `History`, `settings/Storage`; wires `Status`, `Save`, `Refresh` of the top bar | `internal/datasvc` (gitsync, githistory, signin) | owns `internal/app/status.go` bodies; replace the polling by events if needed |
| P8 Settings and tracker | `settings/TeamSettings`, `Tickets`, `Personal` (extend) | team settings, field mapping, sync (`sources`) | wires `SyncTracker` and the tracker chip |
| P9 Start and help | `today/Today`, `today/FirstRun`, `help/Guided`; command palette entries | readiness, findings, demo team | tutorial engine on the demo team only; first-run wizard is a bare page (no rail) |

## Not done in the scaffold

- Release build details (archive names, installers, self-update) belong to the release workflow
  of the command line. On Windows the program is built as a console program for now, so the
  command line keeps its output; hiding the console window of a double click is open.
- Code signing.
- Status, Save and Refresh are bound to `internal/datasvc` (P7); the tracker part of `Status` comes from
  `TrackerInfo` and `SyncTracker(team)` fetches from the tracker (P8).

## Guided flows: marks on pages

Help > Guided flows (`src/lib/tour/flows.ts`) walks through the flows on the demo team. A step shows a
page and marks one element with the outline `.hl`. The element is found by the attribute
`data-tour="name"`; a page adds it to the element a step talks about. A missing element is not an
error: the step is shown without a mark. A step may also carry `query` (for example `{ tab: 'when' }`), which is added to the address of its page, so that a step can open a tab. Keep the names stable; they are listed here.

The demo team is "Team Atlas" from `go/internal/tutorial` (embedded templates, dates relative to
today, every 1.0 feature on, projects including `self-service`). In the program `enterDemo()` calls
`API.EnterDemo`: the core writes the team into a throwaway folder, makes it the data folder without
remembering it, and `LeaveDemo` removes it again. Top bar answers (Save, Refresh) are canned in the
demo. Only the first-start wizard (`Setup*` calls) stays pretended by the mock, so that nothing is
cloned. In a browser (`npm run dev`) the mock answers everything. `examples/teams/demo` is a
different team and stays as it is (golden tests).

| `data-tour` | Page | Package |
| --- | --- | --- |
| `firstrun-step` | `/setup` | |
| `today-running` | `/today` | |
| `backlog-sync` | `/backlog` | |
| `backlog-views` | `/backlog` | |
| `backlog-list` | `/backlog` | |
| `backlog-ticket` | `/backlog` | |
| `ticket-panel` | `/backlog` | |
| `backlog-ruleflag` | `/backlog` | |
| `sprint-stepper` | `/sprint/prepare` | |
| `prepare-grid` | `/sprint/prepare` | |
| `prepare-freeze` | `/sprint/prepare` | |
| `prepare-ready` | `/sprint/prepare` | |
| `preplan-whatif` | `/sprint/preplan` | |
| `preplan-earmarks` | `/sprint/preplan` | |
| `preplan-table` | `/sprint/preplan` | |
| `plan-absences` | `/sprint/plan` | |
| `plan-sumbar` | `/sprint/plan` | |
| `plan-lanes` | `/sprint/plan` | |
| `plan-live` | `/sprint/plan` | |
| `plan-freeze` | `/sprint/plan` | |
| `review-velocity` | `/sprint/review` | |
| `review-scope` | `/sprint/review` | |
| `review-done` | `/sprint/review` | |
| `review-capacity` | `/sprint/review` | |
| `review-tag` | `/sprint/review` | |
| `review-close` | `/sprint/review` | |
| `forecast-chart` | `/forecast` | |
| `forecast-table` | `/forecast` | |
| `forecast-whatif` | `/forecast` | |
| `forecast-analysis` | `/forecast` | |
| `forecast-history` | `/forecast` | |
| `forecast-reports` | `/forecast` | |
| `projects-new` | `/projects` | |
| `projects-timeline` | `/projects` | |
| `projects-table` | `/projects` | |
| `projects-conflict` | `/projects` | |
| `project-tickets` | `/projects/atlas-portal` | |
| `project-report` | `/projects/atlas-portal` | |
| `calc` | `/sprint/plan` | |
| `help-calculations` | `/help/calculations` | |
| `personal-calc` | `/settings/personal` | |
| `plan-present` | `/sprint/plan` | |
| `settings-writeback` | `/settings/tickets` | |
| `settings-storage` | `/settings/storage` | |
| `topbar-status` | top bar | |
| `topbar-refresh` | top bar | |
| `topbar-save` | top bar | |
| `data-conflicts` | `/data` (tab Conflicts) | |
| `data-history` | `/data` (tab History and tags) | |
| `plan-jira` | `/sprint/plan` | |
| `plan-jira-write` | `/sprint/plan` | |

An element that appears only after a click (a panel, a dialog) cannot be marked by a step that comes before the click.
