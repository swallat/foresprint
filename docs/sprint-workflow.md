# Sprint workflow

What to do when, on the command line. Every page of the [web UI](web-ui.md) does the same with
the same files. All assistants explain every field (what it is, where the value comes from, an
example). Look things up with `sprintforecast help terms`, `sprintforecast help fields` and
`sprintforecast help team`; `sprintforecast help commands` lists every command.

| When | Command | What happens |
|---|---|---|
| Create sprints in advance | `sprintforecast sprints team-a --create` | Show upcoming sprints (start, last day, working days) and create their files; `--end 2026.25=2027-01-12` extends a sprint, the following sprints shift. |
| A sprint ID is wrong (e.g. the team is in 2026.15, not 2026.1) | `sprintforecast rename-sprint team-a 2026.1 2026.15` | Gives the sprint a new ID; the saved sprints after it count on from there (2026.2 becomes 2026.16 and so on). Sprint files and minutes are renamed, their contents stay. Also on the *Settings* page under **Change sprint IDs**. |
| Vacation or similar becomes known | `sprintforecast absences team-a [SPRINT]` | Record absences per person (default: next sprint). Shows capacity and forecast. |
| The team changes | `sprintforecast people team-a` | Add a person, change FTE, record a departure. |
| Settings change | `sprintforecast settings team-a` | Change region, reference capacity, trend mode and so on with guidance; shows the changes before saving. |
| Products change | `sprintforecast product-list team-a` | Create a product, change its PO, end a product (with an end date). |
| PO pre-planning | `sprintforecast products team-a --preplanning` | POs enter per product what they intend to bring in; compared with the default. |
| Sprint planning | `sprintforecast planning team-a` | Guided: 1. absences, 2. Forecast PLAN and planned amount per product, 3. commitment (plus an optional cross-check). Freezes the Forecast PLAN. Default: the next sprint that has not been planned yet. |
| Sprint review | `sprintforecast review team-a --commit` | Records velocity, scope creep and done per product, freezes the available person days, commits and sets the tag `team-a/<sprint>`. |
| PO planning | `sprintforecast forecast team-a` | Forecast for the current and the next sprints. |
| Product evaluation | `sprintforecast products team-a [SPRINT]` | Distribution per product and the balance of the last sprints. |
| Report | `sprintforecast report [team-a]` | Writes `teams/team-a/FORECAST.md` (table plus Mermaid chart). |
| Excel | `sprintforecast excel team-a [-o file.xlsx]` | Writes an Excel workbook (the way back for everyone who keeps working in Excel): sprint values as inputs (yellow); normalized velocity, average, trend, Forecast PLAN, plannable amount and small items as real formulas; split by production access and per product; two trend charts. Needs the extra `[excel]` (`uv tool install "sprintforecast[web,excel] ..."`); do not store it in the data folder (`*.xlsx` is not committed). In the web UI: Forecast page, "Create Excel workbook". The workbook contains the whole team (settings, people, products, all sprints with absences, product values and forecasts). |
| Excel import | `sprintforecast excel-import team-a file.xlsx [--apply]` | Reads such a workbook back (only the yellow input cells, by fixed column position) and first shows per file and value what would change; with `--apply` only the changed files are written. Sprint files missing from the workbook stay unchanged. The import requires portable sprint ids (no path separator, colon, backslash or other special characters) and refuses ids that differ only in case. On Linux and macOS such ids can exist, so `sprintforecast excel` warns about them, about case-only duplicates and about an unsafe first sprint id, because the workbook could not be imported again. Independent of the earlier import plugin, which still reads the original Excel list. In the web UI: Settings, "Import from Excel" (upload, preview, then "Apply changes"). |
| Before commit / in CI | `sprintforecast check` | Check errors and plausibility of all teams. Also reports silent assumptions made while loading as notes with file, line and key path: duplicate keys in one file (only the last entry counts) and empty number fields that are read as 0 (for example `fte:` without a number, empty absences). Loading and calculation are unchanged. Note: with `--strict` this yields exit code 1; a data folder with an old duplicate or an empty `fte:` now fails there (without `--strict` the exit code stays 0). Limit: a missing entry (for example `planning:` without `carryover`) is not an empty field and is not reported; it still silently counts as 0. At most 50 such notes are shown per file. The **Check** page of the web UI shows the same. |

## PO pre-planning and planning

- **Announced absences:** on the *PO pre-planning* board, absences per person can be entered as a
  **forecast** before the planning. They affect capacity (source "announced absences") and the
  Forecast PLAN but do not count as confirmed. In *Planning* (step 1) they are prefilled; only
  "Save absences and continue" confirms them. Confirmed absences always take precedence.
- **Absence state per sprint** (unknown / announced / confirmed) is visible everywhere (Forecast,
  Absences, Planning). "Continue without confirmation" in Planning confirms **nothing**: whoever
  really has no absences confirms that explicitly ("Nobody absent: confirm and continue", or the
  *Nobody absent* column on the *Prepare sprint: Absences* page). Saving planning values
  (commitment, planned amounts) does not change the absence state. The date on which a sprint was
  planned is no longer taken as evidence.
- **Planned amounts from the pre-planning:** in Planning (step 2) the planned amount per product
  is prefilled with the latest PO pre-planning (please check and save).
- **Unfreezing:** the Forecast PLAN frozen at planning can be released on the Planning board only
  after confirming that this corrects a mistake. Tickets that are pulled in or taken out after
  the planning do not belong in the planning retroactively; they enter in the *Review* (not done /
  additionally done).

## Longer or shorter sprints (for example over Christmas)

Individual sprints can be extended or shortened by changing their **last day**:

- **Web UI:** *Sprint calendar* page, change the **Last day** in the sprint's row, then *Create
  or save sprints*. The *Working days* column counts the working days of the team's configured
  working week (default Mon-Fri).
- **Command line:** `sprintforecast sprints team-a --end 2026.25=2027-01-12` (form `SPRINT=last
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
