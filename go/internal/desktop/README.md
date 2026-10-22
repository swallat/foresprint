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
npm run dev          # browser, with the demo team from src/lib/mock.ts (no Go needed)
npm run check        # svelte-check (types) + every text has its German translation
npm test             # router, route table, contrast of the design tokens, ...
npm run build        # to dist/, embedded by desktop.go
```

The program with the window (Linux needs `libgtk-3-dev libwebkit2gtk-4.1-dev`):

```
cd go
go build -tags desktop,production,webkit2_41 -o foresprint ./cmd/foresprint   # Linux
go build -tags desktop,production -o foresprint ./cmd/foresprint               # Windows, macOS
```

Without the tag `desktop` nothing of this is compiled: `go build ./...` and `go test ./...` need
neither Node, cgo nor a web view. CI builds and starts the program on all three platforms (job
`desktop`).

## How a page is built

- A page is one file in `frontend/src/pages/<area>/`. `src/lib/routes.ts` maps addresses to the
  files and holds the navigation; a page package replaces the placeholder in its own files and
  does not need to touch `routes.ts` unless it adds an address.
- Data comes from Go through `api` (`src/lib/api.ts`). A method is added in three places: the
  Go struct (`internal/app/api_<area>.go`, types in `types_<area>.go`), the `Api` interface (an
  area interface in `src/lib/types.<area>.ts` and `api.ts`) and the mock (`src/lib/mock.ts`, so
  the page runs in the browser). Arguments and results are plain JSON; an error becomes a
  rejected promise with a text for users.
- Shared state (team, sprint, status, toasts, ticket panel) is `app` in `src/lib/app.svelte.ts`.
  Do not keep a second copy of it; use `toast()`, `openTicket()`, `save()`.
- **Texts**: `t('English source text', { name })`. The key is the English text. A German
  translation goes to `go/internal/i18n/data/de.ui.json`; `npm run check` fails when a text is
  missing or unused. Texts that only exist in Go (messages of `internal/app`) go to
  `de.app.json`. Never build a sentence from pieces; use placeholders.
- **Look**: tokens in `src/styles/tokens.css` (from `DESIGN.md`), shared classes in
  `src/styles/base.css` (names as in the mocks, so a mock view ports without renaming). New
  styles go in the component's `<style>`; changes to tokens or base classes are their own small
  PR. The contrast test (`tokens.test.ts`) measures both themes: text 4.5:1, control edges 3:1.
- **Icons**: `<Icon name="..." />`, flat Material Symbols; add one import line in
  `src/lib/icons.ts`. No emojis anywhere.
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
- Status, Save, Refresh and SyncTracker return fixed answers until P7 and P8 replace them.
