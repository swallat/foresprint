# Foresprint: product context

Durable context for everyone (and every agent) who designs or builds the 1.0 interface. It is
the input of the redesign; the visual system is in [DESIGN.md](DESIGN.md), the screens and flows
in [docs/redesign/](docs/redesign/). Status: **draft for round 1, confirm or correct**.

## What it is

Foresprint answers one question for Scrum teams: **how much can the team plan in the next
sprint?** It turns the sprint history and the absences into a forecast with a range, shows the
calculation behind every figure, and (with the ticket pre-planning) distributes tickets over
future sprints and checks whether projects meet their target date. All data is YAML in the
team's own Git repository. There is no server and no account.

## Who uses it

| Person | Job to be done | How often |
|---|---|---|
| Scrum master / team lead (the main user, owns the data) | Prepare the sprint (absences), plan, close the sprint, keep the backlog in order, share the data with the team | several times a week, in short sessions |
| Product owner (PO) | Say per product what should go into the sprint, see whether projects reach their date | before each planning |
| Team member | Look up capacity, forecast and the calculation; record own absences | a few times per sprint |
| Whoever sets the tool up (first team: "kac") | Connect Jira and Git, create teams, products and people | rarely |

Primary context: a Windows laptop in a company, no admin rights, a company Jira (read only) and a
company Git server, German and English speakers. The tool is open source: nothing may be tied to
one tracker, Git host or company.

## Purpose of the interface

1. **Decide fast.** The common sessions (prepare, plan, close) are a short, guided path with the
   next step always visible.
2. **Keep the backlog in order.** A Jira-style backlog: filter, sort, drag between backlog and
   sprints, see capacity and project dates change immediately.
3. **Trust the numbers.** Every figure opens its calculation. Uncertainty (the range) is shown,
   not hidden.
4. **Stay in sync without thinking about it.** Jira is polled in the background (read only; the
   one write is the label `planned_for_<sprint>`), Git sharing is one clear action with plain
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

- One executable per platform for the 1.0 release, no admin rights, no required internet except
  the team's own Jira and Git servers.
- Windows 10/11 first; macOS and Linux supported.
- Jira stays read only (PAT); exception: the label `planned_for_<sprint>`.
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

## Open questions

See the decision questions in the redesign thread; product-level ones are tracked in
[docs/redesign/inventory.md](docs/redesign/inventory.md#open-questions).
