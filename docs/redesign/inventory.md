# Inventory of the 0.8 UI and fate in 1.0

Superseded: the navigation and the home of every function are defined in [flows.md](flows.md). This table is kept as the first rough pass.

Source: [docs/web-ui.md](../web-ui.md), [docs/sprint-workflow.md](../sprint-workflow.md). Fate: keep, merge, rework, drop (proposal, to be confirmed in review).

| 0.8 page | Fate in 1.0 | Notes |
| --- | --- | --- |
| Start (task tiles) | rework | Becomes a state-aware "Today" view: next step for the current sprint |
| Prepare sprint: Absences | keep | Table person x sprint, live capacity |
| PO pre-planning | merge | Becomes a view of the sprint planning board |
| Planning (3 steps) | rework | Stepper stays, as real navigation; sprint board with drag and drop |
| Close sprint (Review) | keep | Frozen person days |
| Forecast | keep | Range chart, history, report |
| Analysis | merge | Into Forecast as a second tab |
| Product distribution | merge | Into Planning (evaluation tab) |
| Tickets | rework, core | Becomes the Jira-style Backlog: drag, filter, order, earmark, refinement; rules and assignment as side panels |
| Sprint calendar | keep | |
| People | keep | |
| Products | keep | |
| Settings | rework | Split into sections, search |
| Jira connection | rework | Background sync status, setup wizard |
| New team | keep | Wizard |
| Data folder | keep | Git state in the top bar, details here |
| App settings | keep | Theme, density, language |
| Changes and history | rework | Per-object history, Undo |
| Check | merge | Findings appear inline and in a list |
| Help | rework | Searchable, context links |

## New in 1.0

- Automatic background sync with Jira (read-only) and Git, with status in the top bar.
- Backlog with drag and drop, multi-select, saved filters, keyboard operation, command palette.
- Projects as their own area: several products per project, milestones, end date, booked contingents, report for project leads (recommendations, the PO decides).
- Order and earmarks stay local; only the label `planned_for_<sprint>` is written to Jira.
- Single executable, no admin rights, window shell, offline start.

## Flows to specify (each: steps, states, errors, mock, acceptance criteria)

1. First start and team setup.
2. Connect Jira, first sync, sync error.
3. Order and refine the backlog.
4. Prepare sprint: absences, capacity.
5. Plan sprint: earmark tickets into the sprint, products budget, commit.
6. Close sprint.
7. Read the forecast, change assumptions.
8. Share changes via Git (push, merge request).

## Open questions

All decided, see [plan.md](plan.md) section 6.
