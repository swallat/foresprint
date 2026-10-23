# Foresprint: product context

Durable context for everyone (and every agent) who designs or builds the 1.0 interface. It is
the input of the redesign; the visual system is in [DESIGN.md](DESIGN.md), the screens and flows
in [docs/redesign/](docs/redesign/). Status: **approved**; the 1.0 line is built on it (Go core, Wails window, Svelte frontend).

## What it is

Foresprint answers one question for Scrum teams: **how much can the team plan in the next
sprint?** It turns the sprint history and the absences into a forecast with a range, shows the
calculation behind every figure, and (with the ticket pre-planning) distributes tickets over
future sprints and checks whether projects meet their target date. All data is YAML in the
team's own Git repository. There is no server and no account.

## Who uses it

Foresprint is a desktop application with exactly one kind of user: the person who plans for the
team, a scrum master or a product owner (often one person wears both hats). Everything else in
this document assumes that one user.

| Typical work | How often |
|---|---|
| Prepare the sprint (absences), plan, close the sprint, share the data with the team | several times a week, in short sessions |
| Say per product what should go into the sprint, keep the backlog in order, check whether projects reach their milestones and end date, report contingent use back to project leads | before each planning |
| Set up Jira and Git, create teams, products and people | rarely |

Primary context: a Windows laptop in a company, no admin rights, a Jira (read only) and a Git
server, German and English speakers. The tool is open source: nothing may be tied to
one tracker, Git host or company.

## Purpose of the interface

1. **Decide fast.** The common sessions (prepare, plan, close) are a short, guided path with the
   next step always visible.
2. **Keep the backlog in order.** A Jira-style backlog: filter, sort, drag between backlog and
   sprints, see capacity and project dates change immediately.
3. **Trust the numbers.** Every figure opens its calculation. Uncertainty (the range) is shown,
   not hidden.
4. **Stay in sync without thinking about it.** Jira is polled in the background (read only by default; optional
   writes are the label `planned_for_<sprint>` and, if the team switches it on, the sprint assignment), Git sharing is one clear action with plain
   language when something goes wrong.

## Tone

Calm, precise and a little dry. A good colleague who knows the numbers: short sentences,
real units (person days, sprints, dates), no sales language, no exclamation marks, no
jokes in error messages. Errors say what happened, what was skipped and what to do next.
German and English are equal; German is never an afterthought (longer words, formal-neutral
address).

## Principles

- **The data is the source of truth, the screen is a view.** Changes are visible as a diff before
  they are saved; saving never surprises.
- **Show the next step.** Every page says where you are in the sprint and what comes next.
- **Density over decoration.** This is a working tool used on laptops: tables and boards are
  compact, readable and keyboard friendly. Whitespace is for grouping, not for filling.
- **Direct manipulation where the task is spatial.** Ordering and assigning tickets is dragging;
  everything else is a form or a table.
- **Nothing blocks.** Sync, fetch and calculation run in the background; the interface stays
  usable and reports what changed.
- **Dark and light are equals.** Both are designed, neither is derived.

## Constraints

- One executable per platform for the 1.0 release (Go, with a Wails window; the command line is the
  same file), no admin rights, no required internet except
  the team's own Jira and Git servers.
- Windows 10/11 first; macOS and Linux supported.
- Jira stays read only by default (PAT); optional writes: the label `planned_for_<sprint>` and the sprint
  assignment of a planned sprint (team setting, preview and undo). Order is never written back.
- Accessibility: keyboard reachable everywhere, visible focus, contrast AA in both themes,
  state never conveyed by color alone.
- Project rules for the interface: flat icons (Material Symbols), **no emojis** anywhere in
  the UI, no walls of text (one lead sentence plus an expander for details), steps are real
  navigation.

## Anti-references

- A generic SaaS dashboard (gradient hero, big-number tile row, rounded cards everywhere).
- The AI-default look: purple-blue gradients, cream and terracotta, Inter on everything,
  emoji as icons, identical cards in a grid.
- Jira's own clutter: dozens of fields per row, modal on modal.

## Audience

Any Scrum team; Foresprint is open source. Examples and screenshots use an invented demo team, never a real team or company. Decisions: [docs/redesign/plan.md](docs/redesign/plan.md) section 6.
