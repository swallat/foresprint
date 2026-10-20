# SPDX-License-Identifier: EUPL-1.2
"""Help texts as structured data, rendered by the CLI (`help`) and the web UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    title: str
    what: str
    source: str
    example: str


FIELDS: dict[str, Field] = {
    "absences": Field(
        title="Planned absences",
        what=(
            "Working days on which a person is not available for sprint work: vacation, "
            "time off, training, conferences, other projects. Do NOT enter public "
            "holidays – they are taken into account automatically via the German state."
        ),
        source="Vacation calendar or asking the team. Half days as 0.5.",
        example="2 days of vacation + half a day of training → 2.5",
    ),
    "absence_state": Field(
        title="Absence status",
        what=(
            "Each sprint has one of three states: “unknown” (nothing recorded: the "
            "capacity comes from calendar and people list, absences are estimated from "
            "the last sprints), “expected” (forecast from the PO pre-planning, not yet "
            "confirmed) and “confirmed” (absences entered or explicitly “nobody is "
            "absent” confirmed). “Continue without confirmation” confirms nothing: the "
            "sprint stays “unknown”."
        ),
        source=(
            "“Prepare the sprint: absences” page (column “Nobody is absent”) or Planning, step 1."
        ),
        example=(
            "Sprint 2026.23: no entries, “Nobody is absent” ticked → confirmed, full staffing"
        ),
    ),
    "fte": Field(
        title="FTE and workweek",
        what=(
            "FTE is the share of a person's working days that they work in the team (1 = "
            "all their working days). The workweek (e.g. mon,tue,wed,thu) defines which "
            "weekdays are their working days. Please model part-time only once: either "
            "the full workweek with FTE 0.8 or the four-day week with FTE 1 – not both, "
            "otherwise it is deducted twice (10 days → 8 × 0.8 = 6.4 instead of 8 PT)."
        ),
        source="Employment contract or agreement with the person (People page).",
        example=(
            "10 working days in the sprint: Mon–Fri + FTE 0.8 → 8 PT · mon,tue,wed,thu "
            "+ FTE 1 → 8 PT · Mon–Fri + FTE 0.5 (half time) → 5 PT"
        ),
    ),
    "overhead": Field(
        title="Deduction for Scrum events",
        what=(
            "Time for dailies, planning, review, retro and refinement that is not "
            "available for tickets. Either in percent or as fixed PT per person and "
            "sprint (× FTE) – both are the same deduction in two units, the fields "
            "synchronize. If PT per person are set, they apply instead of the percentage. "
            "The deduction works the same for confirmed, expected and estimated absences: "
            "first holidays and absences, then the deduction. Rounding only happens when "
            "shown and when frozen."
        ),
        source="Team settings (deduction for Scrum events).",
        example=(
            "1 PT per person with 10 working days equals 10 %; full time: −1 PT, half "
            "time (FTE 0.5): −0.5 PT"
        ),
    ),
    "capacity": Field(
        title="Capacity",
        what=(
            "Available person days (PT) of the team in the sprint. Normally calculated "
            "from the people list, holidays and absences and frozen at the review."
        ),
        source="Automatic. Only enter manually if there is no people list.",
        example="5 people × 10 days − 6.5 days absent = 43.5",
    ),
    "forecast_ist": Field(
        title="Commitment",
        what=(
            "The amount committed in sprint planning for THIS sprint: the sum of the "
            "estimates of all tickets in the sprint at sprint start. Not the velocity of "
            "the previous sprint; tickets added later count as scope creep."
        ),
        source=(
            "Right after planning: sum of the estimates on the board, or in Jira the "
            'value "Commitment" in the sprint report/velocity chart. Equals '
            "carry-over + backlog; if left empty it is prefilled with this sum from the "
            "cross-check."
        ),
        example="15.5",
    ),
    "velocity": Field(
        title="Velocity",
        what=(
            "Amount actually done in the sprint: estimates of the finished tickets plus – "
            "by team practice – the parts of open tickets completed in the sprint "
            "(estimate of the ticket, not the actual effort). See “Done per product”."
        ),
        source=(
            'At the review: sprint report, or in Jira the value "Completed" in the velocity chart.'
        ),
        example="13.5",
    ),
    "scope_creep": Field(
        title="Scope creep",
        what=(
            "Share of work added to the sprint after planning, relative to the commitment "
            "(0.3 = 30 %). Leave empty if unknown – do not enter 0."
        ),
        source="Sprint report: estimates added later / commitment.",
        example="4.5 added later with 15 committed → 0.3",
    ),
    "carryover": Field(
        title="Carry-over (remaining effort)",
        what=(
            "Remaining effort of unfinished tickets taken over from the previous sprint. "
            "Part of the optional cross-check – only affects the planning delta."
        ),
        source="Sprint board at planning.",
        example="1.5",
    ),
    "backlog": Field(
        title="Backlog",
        what=(
            "Sum of the tickets newly planned in the planning. Part of the optional "
            "cross-check; carry-over + backlog equals the commitment."
        ),
        source="Sprint board at planning.",
        example="33.6",
    ),
    "corrections": Field(
        title="Correction of remaining effort",
        what=(
            "Parts of tickets already done that are still included in the planning value "
            "(subtracted). Separate several values with spaces. Part of the optional "
            "cross-check – only affects the planning delta."
        ),
        source="Tickets with partial progress.",
        example="4.25 4.5",
    ),
    "preplanned": Field(
        title="PO pre-planning per product",
        what=(
            "Amount the PO of a product intends for the sprint – before planning, as a "
            "basis for agreement between the POs. Compared with the standard (available "
            "amount / number of products handled)."
        ),
        source="PO meeting or the POs' preparation, e.g. sum of the intended tickets.",
        example="4",
    ),
    "planned": Field(
        title="Planning per product",
        what=(
            "Amount planned for the product in sprint planning (sum of the product's "
            "tickets in the sprint)."
        ),
        source="Sprint board at planning, filtered by product (component, label, epic …).",
        example="4.5",
    ),
    "done": Field(
        title="Done per product",
        what=(
            "Amount actually done for the product in the sprint: estimates of the "
            "finished tickets plus the parts of open tickets completed in the sprint "
            "(team practice). The sum over the products is at most the velocity. This way "
            "of counting should be uniform in the team – otherwise velocity and done are "
            "not comparable between teams or across a change."
        ),
        source="At the review: sprint report, filtered by product.",
        example="3.75",
    ),
}


@dataclass(frozen=True)
class Step:
    when: str
    title: str
    text: str
    # Web UI page (file name under web/page_scripts without .py)
    page: str
    cli: str


WORKFLOW: list[Step] = [
    Step(
        when="Once",
        title="Set up the team",
        text=(
            "Create a new team (or import the history with an import plugin), then add "
            "the people with their FTE share."
        ),
        page="new_team",
        cli="sprintforecast init TEAM",
    ),
    Step(
        when="Any time",
        title="Create future sprints",
        text=(
            "Following sprints are created automatically from the sprint length and the "
            "end of the previous one. In the sprint calendar they can be created in "
            "advance, and different lengths (e.g. over Christmas) set via the last day; "
            "the following sprints shift accordingly. The capacity counts the working "
            "days of the sprint, so the Forecast PLAN scales with the length. Enter "
            "bridge days as absences."
        ),
        page="sprints",
        cli="sprintforecast sprints TEAM [--create] [--end SPRINT=DATE]",
    ),
    Step(
        when="Any time",
        title="Maintain absences",
        text=(
            "As soon as vacations, training etc. are known, enter them per person and "
            "sprint – also for future sprints. If none are known, explicitly confirm "
            "“Nobody is absent”. Without confirmation the absences stay “unknown” and are "
            "estimated from the last sprints."
        ),
        page="absences",
        cli="sprintforecast absences TEAM [SPRINT]",
    ),
    Step(
        when="Before planning / PO planning",
        title="View the forecast",
        text=(
            "Shows the Forecast PLAN for the current and upcoming sprints – the "
            "recommended planning amount, split into plannable and small items. The start "
            "page leads through three tasks (prepare sprint, planning, close sprint) to "
            "the next sensible page."
        ),
        page="forecast",
        cli="sprintforecast forecast TEAM",
    ),
    Step(
        when="Before planning (POs)",
        title="PO pre-planning per product",
        text=(
            "Only with product distribution switched on (settings). If the team looks "
            "after several products, the POs enter how much they plan per product – "
            "compared to the default (available amount / number of products)."
        ),
        page="preplanning",
        cli="sprintforecast products TEAM --preplanning",
    ),
    Step(
        when="Sprint planning (sprint start)",
        title="Planning in three steps",
        text=(
            "1. Enter the known absences for the sprint. 2. Plan the tickets with the "
            "Forecast PLAN, optionally per product. 3. Before the sprint starts, enter "
            "the commitment (the amount committed); the Forecast PLAN is frozen at that "
            "point. Optionally the cross-check from carry-over, backlog and corrections "
            "(delta to the Forecast PLAN)."
        ),
        page="planning",
        cli="sprintforecast planning TEAM",
    ),
    Step(
        when="Sprint review (sprint end)",
        title="Record the review",
        text=(
            "Enter velocity, scope creep and optionally done per product. The sprint's "
            "capacity is frozen so that later changes to the people list do not change "
            "the history. Product values are entered only on the boards (pre-planning, "
            "planning, review); the product distribution only evaluates them."
        ),
        page="review",
        cli="sprintforecast review TEAM --commit",
    ),
    Step(
        when="For questions about completion",
        title="Analysis",
        text=(
            "In addition to the forecast: range (conservative/optimistic), focus factor, "
            'buffer recommendation and "When will it be done?" for a remaining amount.'
        ),
        page="analysis",
        cli="sprintforecast analysis TEAM [--remaining AMOUNT]",
    ),
    Step(
        when="When the team changes",
        title="People and settings",
        text=(
            "Record joining, leaving and FTE changes; adjust team settings such as German "
            "state or reference capacity."
        ),
        page="people",
        cli="sprintforecast people TEAM · sprintforecast settings TEAM",
    ),
    Step(
        when="When the products change",
        title="Maintain products",
        text=(
            "Only with product distribution switched on. Create new products (with PO if "
            "“PO assignment” is on) and start date; end handed-over ones with “until” "
            "instead of deleting – past reports are kept."
        ),
        page="product_list",
        cli="sprintforecast product-list TEAM",
    ),
]


TERMS: list[tuple[str, str]] = [
    ("Capacity", "Available person days in the sprint (always PT, also for SP teams)."),
    (
        "Commitment",
        (
            "The amount committed at planning – the commitment at sprint start, not a result "
            "(formerly “Forecast IST”; the file keys are still called forecast_ist)."
        ),
    ),
    ("Velocity", "Amount done in the sprint."),
    (
        "Normalized velocity",
        (
            "Velocity / capacity × reference capacity. Makes sprints with vacation and fully "
            "staffed sprints comparable. The same quantity as the focus factor, just scaled by "
            "the reference capacity; the reference capacity does not change the Forecast PLAN."
        ),
    ),
    (
        "Focus factor",
        (
            "Velocity / capacity (= normalized velocity / reference capacity). Not comparable "
            "between teams because it depends on the estimation unit; the trend within one's "
            "own team is what counts."
        ),
    ),
    (
        "Ø (moving)",
        (
            "Average of the last sprints with a value (default 5, adjustable). Sprints without "
            "a value do not count; the window then reaches further back."
        ),
    ),
    (
        "Trend",
        (
            "Extrapolation of the average into the future. Default “constant” (last average). "
            "“Linear” and “classic” also extrapolate noise and must be chosen explicitly; with "
            "thin history “constant” applies."
        ),
    ),
    (
        "Trend modes",
        (
            "Example: the average was 44 recently, 40 before. Constant (default): the next "
            "sprints stay at 44, 44, 44. Robust, but follows no development. Linear: the last "
            "step (+4) continues: 48, 52, 56. Classic: linear first (48), then proportional "
            "like the last time (+10 %: 52.8), then linear again (57.6). Linear and classic "
            "also extrapolate random fluctuations; the forecast can then rise or fall and "
            "quickly leaves the range over a longer horizon. They only fit a proven, stable "
            "trend. If the history is not enough (fewer sprints with a value than the mode "
            "needs), “constant” applies, and a note says so. The forecast is never negative. "
            "You can switch the mode at any time under Manage team → Settings; no data is "
            "lost, the forecast is only recalculated."
        ),
    ),
    (
        "Current forecast / at planning",
        (
            "Current forecast: the Forecast PLAN calculated today. Forecast at planning: the "
            "state frozen at the planning (basis of the distribution per product). The "
            "difference shows how the forecast has changed since."
        ),
    ),
    (
        "Range",
        (
            "Forecast with the lowest and highest normalized velocity of the last sprints. "
            "With fewer than 8 sprints with velocity only a rough hint."
        ),
    ),
    (
        "Done",
        (
            "Finished tickets plus the parts of open tickets completed in the sprint (team "
            "practice)."
        ),
    ),
    (
        "Forecast PLAN",
        (
            "Recommended planning amount: norm. velocity trend / reference capacity × "
            "capacity, rounded down. Never negative."
        ),
    ),
    (
        "Plannable share",
        (
            "Reserved share of the Forecast PLAN for plannable topics (default 80 %); the rest "
            'is called "small items". It is a split of the forecast, not another value: '
            "plannable + small items = Forecast PLAN."
        ),
    ),
    (
        "Feature areas",
        (
            "Three optional areas that can be switched on independently in the settings (off "
            "for new teams): product distribution (several products), PO assignment (product "
            "owner per product) and production access (only some people may work on certain "
            "tickets). Areas that are switched off hide pages, columns and hints; recorded "
            "values stay in the files."
        ),
    ),
    (
        "Announced absences",
        (
            "Absences entered by the POs in the pre-planning (forecast, not yet confirmed). "
            "Not to be confused with the expected absences."
        ),
    ),
    (
        "Expected absences",
        (
            "Estimate from the history (average of the last sprints with confirmed absences) "
            "for sprints whose absences are unknown. Calculated, not entered by anyone."
        ),
    ),
    ("Small items", "Rest of the Forecast PLAN for bugs, support and small things."),
    ("Fulfillment", "Velocity / commitment – how well was the commitment kept?"),
    (
        "Standard per product",
        (
            "Available amount / number of products handled. Available = Forecast PLAN (frozen "
            "at planning) or only its plannable share (setting)."
        ),
    ),
    ("Balance per product", "Σ done − Σ standard over several sprints."),
    (
        "Delta",
        (
            "Forecast PLAN − planning total (carry-over + backlog − corrections). Optional "
            "cross-check in planning; does not affect any other metric."
        ),
    ),
]

# Collaboration via Git: explanations for the help page (title, text).
GIT_HELP: list[tuple[str, str]] = [
    (
        "Save and share",
        (
            "The button in the sidebar first saves your changes (as a commit), then fetches "
            "the others' changes from the server, merges both and uploads the result. Your own "
            "changes are therefore always safe before anything foreign is added. The simple "
            "model applies: “one branch, always keep in sync”."
        ),
    ),
    (
        "What has changed?",
        (
            "With pending changes, the Git section shows, before “Save and share” and “Commit "
            "changes”, what changed per file: for changed and renamed YAML files every value "
            "with before and after, for new and deleted files only the kind. Nested values are "
            "written with dots, entries with an id in square brackets, e.g. people.[anna].fte. "
            "Long values are shortened. Files without readable values (Excel, reports, broken "
            "YAML, files over 1 MiB or with more than 200,000 entries) carry the note “no "
            "value view”. The first 25 files are evaluated, at most 4 MiB in total; further "
            "files carry the note “not evaluated”."
        ),
    ),
    (
        "State in the sidebar",
        (
            "“not shared yet” are your own commits the server does not know; “new from others” "
            "are commits on the server that you do not have yet. The server state is only "
            "queried when you click “Check state” and when sharing; “checked … min ago” shows "
            "how current it is."
        ),
    ),
    (
        "Changes by others",
        (
            "Before sharing, the sidebar lists what others have changed since your last sync "
            "(who, when, which files). After sharing it shows what was taken over."
        ),
    ),
    (
        "Merging and conflicts",
        (
            "If two people change different values in the same file (e.g. absences of Anna and "
            "of Ben in the same sprint), they are united automatically. Only if both changed "
            "the same value differently does the app ask, on the “Resolve conflicts” page, for "
            "each entry: “My change” or “Other change”. While a conflict is open, editing is "
            "locked. Nothing is lost; “Abort merge” discards the merge and keeps your own "
            "changes."
        ),
    ),
    (
        "Check after merging",
        (
            "After every merge the full validation runs: a merge can succeed technically and "
            "still be invalid in content (e.g. two fixed product shares of 60 % each). New "
            "errors stop the upload and the list shows them; after correcting, “Save and "
            "share” is enough, or deliberately “Share anyway”."
        ),
    ),
    (
        "Outdated input",
        (
            "If the files change while a page is open (sharing, other programs), the app "
            "discards unsaved input with a notice and reloads instead of overwriting foreign "
            "changes."
        ),
    ),
    (
        "Discard changes",
        (
            "On the “Changes and history” page, single files or all open changes can be "
            "discarded. Beforehand the app shows what is lost (file, status, lines) and asks "
            "for confirmation. For safety a copy goes to the trash under `.git`."
        ),
    ),
    (
        "History and restoring an earlier state",
        (
            "The history shows, per team, sprint or file, who changed what and when. An "
            "earlier state can be restored; that is itself a new change and can be undone with "
            "“Take back this change”. Open changes in the affected area must be saved or "
            "discarded first."
        ),
    ),
    (
        "Managing tags",
        (
            "Tags (e.g. `team/2026.21`) mark completed reviews. They can be shown, set later "
            "on any state and deleted; the app syncs them with the server and reports when "
            "that failed (the tag then stays local). With “Compare with server” (asks the "
            "server, only on click) the list shows whether a tag exists only locally, only on "
            "the server or at a different state. A local-only tag can be made up with “Upload "
            "to server”; tags that exist on one side only can be deleted as well."
        ),
    ),
    (
        "Server with a foreign history",
        (
            "If the server holds a completely different history than the data folder (usually "
            "the wrong repository is connected, e.g. a code repository), “Save and share” "
            "merges nothing and uploads nothing; your own changes stay safe locally. The "
            "sidebar names server and branch. If it is the wrong repository, the address can "
            "be changed on the “Data folder” page under “Server (remote)” (the link “Change "
            "server address” leads there). Only if the server really is the right data "
            "repository can merging be confirmed deliberately with the box “Yes, merge both "
            "histories” and the button below it; “Cancel” changes nothing."
        ),
    ),
    (
        "Switching between data folders",
        (
            "The active data folder (with its parent folder) and its branch are shown at the "
            "top of the sidebar. Under “Switch data folder” and on the “Data folder” page the "
            "recently used folders can be switched. The data folder applies per browser "
            "window: when one window switches, other open windows keep working in their "
            "folder; newly opened windows start in the last chosen one. Switching discards "
            "unsaved input in forms and all caches of the old folder; pending tags, the commit "
            "message and open changes in the old folder stay there and reappear when you "
            "switch back."
        ),
    ),
    (
        "Server not reachable (offline)",
        (
            "Your changes are still saved locally. Choose “Save and share” again later when "
            "the internet or VPN is back. If the address is wrong (typo, server moved), it can "
            "be changed on the “Data folder” page under “Server (remote)”."
        ),
    ),
    (
        "Repository not found",
        (
            "If the server answers but knows no repository at the saved address (or conceals "
            "it because you lack permission), the app reports “Repository not found” instead "
            "of “Server not reachable”: at “Check connection”, when syncing, uploading and "
            "cloning. Checking the internet or VPN does not help then. Check the address "
            "(typo, renamed or moved repository) and the permission; the address can be "
            "changed on the “Data folder” page under “Server (remote)”. If the repository is "
            "in a folder or on a network drive that is not connected right now, the app "
            "reports “Server not reachable” instead."
        ),
    ),
    (
        "Server certificate not accepted",
        (
            "If the server answers but this computer does not accept its security certificate "
            "(often a company certificate or a self-issued certificate), the app reports it as "
            "such. Checking the internet or VPN does not help. Ask IT to install the "
            "certificate on the computer. The app changes no Git settings for this and does "
            "not save an address whose certificate is not accepted."
        ),
    ),
    (
        "Set up the server (remote)",
        (
            "On the “Data folder” page, the “Server (remote)” section shows which server "
            "belongs to the data folder. The address is entered or changed there; “Check "
            "connection” tests it without changing anything, and “Save” checks again and only "
            "accepts it if the connection works. Allowed are https://…, ssh://…, "
            "git@server:path and a complete folder path; http:// only after explicit "
            "confirmation. User name, password and token do not belong in the address (see "
            "“Login”). If the server is not reachable or lacks the branch, the address can "
            "only be saved anyway with explicit confirmation. Anyone joining an existing team "
            "is better off choosing “Clone repository” on the same page."
        ),
    ),
    (
        "Login",
        (
            "The app does not sign in by itself, does not set up a login and never asks for a "
            "password; your computer's credential service handles the login. If it is missing, "
            "the app explains the next step for your operating system and, for that, looks "
            "(read-only) at the Git setting `credential.helper` without changing it. With "
            "https the server usually needs an access token (GitHub: personal access token, "
            "GitLab: access token with “write_repository”) that you store once in your "
            "computer's credential service (Windows: Git Credential Manager or Credential "
            "Manager, macOS: Keychain, Linux: `libsecret`); with the GitHub CLI, `gh auth "
            "setup-git` sets up the login. A plain-text store (`credential.helper store`) is "
            "not recommended. With SSH the key must be registered with the server and "
            "available in the ssh-agent."
        ),
    ),
    (
        "SSH server not known yet (fingerprint)",
        (
            "If the computer connects to an SSH server for the first time, or the server's key "
            "has changed, SSH requires the server's fingerprint to be confirmed. The app "
            "cannot do that and does not ask for it either (Git runs in the background without "
            "prompts); it reports this at “Check connection”, when syncing, uploading, cloning "
            "and with tags. Please connect to the server once with an SSH or Git program and "
            "confirm the fingerprint, or use the https address of the repository; then try "
            "again. If the key of a known server has changed, ask the operator of the server "
            "first."
        ),
    ),
    (
        "Name and email address",
        (
            "Git needs both for every commit. If missing, the app asks for it and, at your "
            "request, stores it in your user's global Git configuration; otherwise it changes "
            "no global Git setting."
        ),
    ),
    (
        "Locked file",
        (
            "If another program (Git client, editor, virus scanner, cloud folder) is using a "
            "file in the repository, Git cannot change it. Close other programs and try again. "
            "If that does not help, a lock file (`index.lock` in the hidden `.git` folder) may "
            "have been left over after a crash. The app does not remove it itself: please ask "
            "whoever looks after the computer or the repository before it is deleted (if a Git "
            "program is still running, deleting it disturbs its work). If a data file cannot "
            "be written during the automatic merge, something similar helps: close programs, "
            "check the write protection and choose “Save and share” again; the merge stays "
            "open and is then continued."
        ),
    ),
    (
        "File or folder not writable",
        (
            "If Git may not write in the data folder (or in the hidden `.git` folder inside "
            "it), the app reports “File or folder not writable”. Usually the user account has "
            "no write permission there, the folder is write-protected, or a network drive or "
            "cloud folder is not connected or read-only. Check permissions, write protection "
            "and connection; if that does not help, ask whoever looks after the computer. A "
            "“Permission denied” when connecting to the server, on the other hand, concerns "
            "the login or the permissions on the server (see “Login”)."
        ),
    ),
    (
        "Git considers the folder unsafe",
        (
            "If Git rejects a folder because it belongs to a different user account than the "
            "one the app runs under (“detected dubious ownership”; common with network drives, "
            "copied folders or after an account change), the app reports this reason instead "
            "of “is not in a Git repository”: in the sidebar, in the history, on the “Data "
            "folder” page and in the command `sprintforecast data-dir`. In such a folder the "
            "app creates no repository and writes nothing; when adopting the folder, “Use "
            "without Git” remains. The app changes no Git settings and does not advise doing "
            "so. Please ask whoever looks after the computer: they can assign the folder to "
            "your own account or deliberately mark it as safe."
        ),
    ),
    (
        "Incomplete merge, detached HEAD",
        (
            "If an earlier merge was interrupted, the sidebar offers “Abort merge”. If the "
            "repository is on no branch (detached HEAD), “Back to the branch” returns; commits "
            "without a branch are saved on a rescue branch first, whose name the message "
            "gives. Open changes in the data folder are saved there as well before the switch "
            "(as a commit of their own, “Open changes saved before the switch”); the "
            "main branch does not contain them, they are only on the rescue branch (a separate "
            "branch just for saved work). If the switch would overwrite changes outside the "
            "data folder, everything stays as it is: the app only touches the data folder. "
            "Save or discard those changes there in Git (the “Technical message” names the "
            "files). Then choose “Back to the branch” again; the rescue branch remains and is "
            "named then."
        ),
    ),
]

CAPACITY_SOURCES: list[tuple[str, str]] = [
    ("recorded", "Value is in the sprint file (frozen at the review or entered manually)."),
    ("people list", "Calculated from people, holidays and absences."),
    (
        "Calendar, absences unknown",
        (
            "Absences still unknown and no history yet: capacity from the people list and "
            "calendar (holidays, sprint length), without deduction for absences."
        ),
    ),
    (
        "Trend",
        (
            "Only for teams without a people list: capacity extrapolated like the normalized "
            "velocity."
        ),
    ),
    (
        "announced absences",
        (
            "Absences not yet confirmed: capacity from the people list with the announced "
            "absences entered in the PO pre-planning."
        ),
    ),
    (
        "expected absences",
        (
            "Absences unknown: capacity from the people list and calendar, reduced by the "
            "average absences of the last sprints with confirmed absences (setting “Absence "
            "history”)."
        ),
    ),
]

COMMANDS: list[tuple[str, str]] = [
    ("sprintforecast web", "Start the web interface as an app in its own window"),
    ("sprintforecast web --no-app", "Web interface in a browser tab instead of as an app"),
    ("sprintforecast web --no-browser", "Start the server without opening a window"),
    ("sprintforecast shortcut", "Create a double-click launcher (desktop/start menu)"),
    (
        "sprintforecast completion SHELL",
        "Tab completion script (bash, zsh, fish, powershell); set up with --install-completion",
    ),
    (
        "sprintforecast forecast TEAM [--explain SPRINT]",
        "Forecast for the current and upcoming sprints",
    ),
    ("sprintforecast absences TEAM [SPRINT]", "Record absences per person"),
    (
        "sprintforecast sprints TEAM [--create] [--end SPRINT=DATE]",
        "Sprint calendar: upcoming sprints, end dates",
    ),
    (
        "sprintforecast rename-sprint TEAM SPRINT NEW",
        "Change a sprint ID; the sprints after it count on",
    ),
    ("sprintforecast planning TEAM [SPRINT]", "Record commitment and planning values"),
    (
        "sprintforecast review TEAM [SPRINT] [--commit]",
        "Record velocity and scope creep, freeze capacity",
    ),
    ("sprintforecast people TEAM [--former]", "Maintain people"),
    ("sprintforecast product-list TEAM", "Maintain products (PO, period)"),
    (
        "sprintforecast products TEAM [SPRINT] [--preplanning]",
        "Show distribution per product, record PO pre-planning, balance",
    ),
    ("sprintforecast settings TEAM", "Change team settings"),
    ("sprintforecast capacity TEAM [SPRINT]", "Capacity calculation in detail"),
    (
        "sprintforecast analysis TEAM [--remaining AMOUNT] [--total] [--share PERCENT]",
        "Range, focus factor, buffer, completion",
    ),
    ("sprintforecast report [TEAM] [--output PATH]", "Generate FORECAST.md"),
    ("sprintforecast excel TEAM [--output PATH]", "Excel list with formulas and trend chart"),
    (
        "sprintforecast excel-import TEAM FILE [--apply]",
        "Read Excel list (preview, then write)",
    ),
    (
        "sprintforecast tickets TEAM [--fetch | --import FILE | --handover [--overwrite]] "
        "[--apply] [--commit] [--sprints N] [--variant median|conservative|optimistic]"
        " | --test-connection | --set-token",
        (
            "Read tickets from Jira or a CSV file, distribute them over future sprints (ticket "
            "pre-planning, with range); --handover proposes the sums per sprint and product as "
            "the PO pre-planning"
        ),
    ),
    ("sprintforecast init TEAM", "Create new team"),
    (
        "sprintforecast check [--strict]",
        (
            "Check all data (for CI and before committing); also reports duplicate keys and "
            "empty number fields"
        ),
    ),
    ("sprintforecast data-dir [PATH]", "Show or set the saved data folder"),
    ("sprintforecast language [de|en]", "Show or set the interface language"),
    (
        "sprintforecast update",
        "Update to the latest version (--auto on|notice|off)",
    ),
    ("sprintforecast help [TOPIC]", "This help"),
    (
        "sprintforecast --data PATH …",
        (
            "Before the command: set the data directory (otherwise FORESPRINT_DATA, the "
            "current or the saved directory)"
        ),
    ),
    (
        "sprintforecast --as-of DATE …",
        ("Before the command: set the date (YYYY-MM-DD) that counts as “today” – for looking back"),
    ),
]

TOPICS: dict[str, str] = {
    "workflow": "What to do when?",
    "terms": "Terms and capacity sources",
    "fields": "Input fields: meaning, source, example",
    "team": "Team settings",
    "commands": "All commands",
}
