# Sprint workflow

What to do when, on the command line. Every page of the [window](window.md) does the same with
the same files. All assistants explain every field (what it is, where the value comes from, an
example). Look things up with `foresprint help terms`, `foresprint help fields` and
`foresprint help team`; `foresprint help commands` lists every command.

| When | Command | What happens |
|---|---|---|
| Create sprints in advance | `foresprint sprints team-a --create` | Show upcoming sprints (start, last day, working days) and create their files; `--end 2026.25=2027-01-12` extends a sprint, the following sprints shift. |
| A sprint ID is wrong (e.g. the team is in 2026.15, not 2026.1) | `foresprint rename-sprint team-a 2026.1 2026.15` | Gives the sprint a new ID; the saved sprints after it count on from there (2026.2 becomes 2026.16 and so on). Sprint files and minutes are renamed, their contents stay. Also in the window under *Team > Sprint calendar*. |
| Vacation or similar becomes known | `foresprint absences team-a [SPRINT]` | Record absences per person (default: next sprint). Shows capacity and forecast. |
| The team changes | `foresprint people team-a` | Add a person, change FTE, record a departure. |
| Settings change | `foresprint settings team-a` | Change region, reference capacity, trend mode and so on with guidance; shows the changes before saving. |
| Products change | `foresprint product-list team-a` | Create a product, change its PO, end a product (with an end date). |
| PO pre-planning | `foresprint products team-a --preplanning` | POs enter per product what they intend to bring in; compared with the default. |
| Sprint planning | `foresprint planning team-a` | Guided: 1. absences, 2. Forecast PLAN and planned amount per product, 3. commitment (plus an optional cross-check). Freezes the Forecast PLAN. Default: the next sprint that has not been planned yet. |
| Sprint review | `foresprint review team-a --commit` | Records velocity, scope creep and done per product, freezes the available person days, commits and sets the tag `team-a/<sprint>`. |
| PO planning | `foresprint forecast team-a` | Forecast for the current and the next sprints. |
| Product evaluation | `foresprint products team-a [SPRINT]` | Distribution per product and the balance of the last sprints. |
| Report | `foresprint report [team-a]` | Writes `teams/team-a/FORECAST.md` (table plus Mermaid chart). |
| Excel | `foresprint excel team-a [-o file.xlsx]` | Writes an Excel workbook (the way back for everyone who keeps working in Excel): sprint values as inputs (yellow); normalized velocity, average, trend, Forecast PLAN, plannable amount and small items as real formulas; split by production access and per product; two trend charts. Do not store it in the data folder (`*.xlsx` is not committed). In the window: Forecast page, "Excel workbook". The workbook contains the whole team (settings, people, products, all sprints with absences, product values and forecasts). |
| Excel import | `foresprint excel-import team-a file.xlsx [--apply]` | Reads such a workbook back (only the yellow input cells, by fixed column position) and first shows per file and value what would change; with `--apply` only the changed files are written. Sprint files missing from the workbook stay unchanged. The import requires portable sprint ids (no path separator, colon, backslash or other special characters) and refuses ids that differ only in case. On Linux and macOS such ids can exist, so `foresprint excel` warns about them, about case-only duplicates and about an unsafe first sprint id, because the workbook could not be imported again.  In the window: Forecast page, "Import from a file" (preview, then "Write changes"). |
| Before commit / in CI | `foresprint check` | Check errors and plausibility of all teams. Also reports silent assumptions made while loading as notes with file, line and key path: duplicate keys in one file (only the last entry counts) and empty number fields that are read as 0 (for example `fte:` without a number, empty absences). Loading and calculation are unchanged. Note: with `--strict` this yields exit code 1; a data folder with an old duplicate or an empty `fte:` now fails there (without `--strict` the exit code stays 0). Limit: a missing entry (for example `planning:` without `carryover`) is not an empty field and is not reported; it still silently counts as 0. At most 50 such notes are shown per file. The **Today** page of the window shows the findings. |

## PO pre-planning and planning

- **Announced absences:** on the *Prepare* page, absences per person and sprint are entered as
  **announced** or **confirmed**. Announced absences affect capacity (source "announced
  absences") and the Forecast PLAN but do not count as confirmed. Confirmed absences always take
  precedence.
- **Absence state per sprint** (unknown / announced / confirmed) is visible everywhere (Forecast,
  Prepare, Plan). The Plan page points to *Prepare* until the absences are confirmed; whoever
  really has no absences confirms that explicitly (*Nobody absent* on the *Prepare* page).
  Saving planning values (commitment, planned amounts) does not change the absence state. The
  date on which a sprint was planned is no longer taken as evidence.
- **Planned amounts from the pre-planning:** on the Plan page the planned amount per product is
  prefilled with the latest PO pre-planning (please check and save).
- **Starting and closing a sprint:** a sprint does not run because its first day has come. The
  team starts it (*Start sprint* on the Pre-plan and Plan pages and on *Today*), so Review of the
  old sprint and Planning of the new one can happen on the changeover day. The sprint counts as
  started from the day entered (from its planned first day up to today), so a late start or a
  mistake can be put right; the start can be moved or taken back while the sprint runs. A
  running sprint stays running after its last day until its Review is closed (or the next sprint
  is started). The window writes `started_on` (and `start_pending` while a sprint waits for its
  start) into the sprint file. Files of earlier versions count as started once their plan is
  frozen and their first day is over; a sprint that was never started is closed by its last day.
- **Starting agrees the plan:** *Start sprint* on the Plan page freezes the agreement (the
  Forecast PLAN stays as planned) and starts the sprint in one step, because the Planning on the
  first day is where the commitment is made. Before the first day the Plan page only keeps
  earmarks. *Take start back* also reopens the plan. Only a sprint frozen by an earlier version
  or by the CLI can still be reopened with "Open the plan again". Tickets that are pulled in or taken out after the
  planning do not belong in the planning retroactively; they enter on the *Review* page (not done /
  additionally done).

## Longer or shorter sprints (for example over Christmas)

Individual sprints can be extended or shortened by changing their **last day**:

- **Window:** *Team > Sprint calendar*, change the **Last day** in the sprint's row, then save. The *Working days* column counts the working days of the team's configured
  working week (default Mon-Fri).
- **Command line:** `foresprint sprints team-a --end 2026.25=2027-01-12` (form `SPRINT=last
  day`, can be repeated).
- **Following sprints:** every following sprint starts on the day after the previous sprint's
  last day and keeps its previous length; sprints not yet created get new IDs. The default sprint
  length (setting *Sprint length*) applies only to newly generated sprints.
- **Forecast:** capacity counts the sprint's actual working days (minus public holidays and
  absences), and the velocity is normalized to capacity. A sprint with twice the working days
  therefore gets roughly twice the Forecast PLAN, and the normalization stays comparable with the
  shorter sprints.
- **Bridge days:** official public holidays of the configured region are deducted automatically;
  bridge days as well as 24 and 31 December are entered as **absences** per person.
- **Review:** enter the velocity as for every sprint; the capacity is frozen. For a sprint that
  has already been recorded, change the end afterwards the same way; the sprint file keeps its
  data.
