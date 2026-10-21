# Function inventory of the 0.8 web UI

Source: `src/foresprint/web/` (`ui.py`, `tickets_view.py`, `jira_setup.py`, `sprint_board.py`, `rule_editor.py`, `logic.py`, `app.py`, `page_scripts/`), `settings.py`, `docs/web-ui.md`. Input for the UI redesign (see `plan.md`, `inventory.md` in this folder).

Rows: 292. Kinds: view, edit, action, setting, navigation. Page order = sidebar order (groups Tasks, Reports, Manage team, Data & help; the code names the second group "Reports", `docs/web-ui.md` calls it "Evaluation"). Labels are the English UI texts.

In the *Notes* column, `Hidden` markers are collected in section 3. Feature flags: Product distribution (`features.products`), PO assignment (`features.po`), Production access (`features.production`), Ticket pre-planning (`features.tickets`); all set on Settings.

## 1. Function table

### 0. Sidebar and page frame (on every page)

Top part is drawn by `sidebar` (before the navigation), the Git/update part by `sidebar_footer` (after the page). Frame rows are cross-page behaviour in `run_page`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F001 | View active data folder and branch | Sidebar > top caption; `_active_repo_caption` | view | data folder, git branch | Shows parent/folder name only; full path is in the footer caption and on Data folder page |
| F002 | Switch to a recently used data folder | Sidebar > expander "Switch data folder" > Recently used + Switch; `_switch_panel`, `_use_data_dir` | action | user settings (recent folders), session state | Discards unsaved form input; pending tags and commit message kept per folder |
| F003 | Change UI language | Sidebar > selectbox "Sprache / Language"; `_language_changed` | setting | user settings (language) | Per user, not shared with team |
| F004 | Select team | Sidebar > selectbox "Team"; `sidebar` | navigation | session state | Determines which pages exist (feature flags of the team); absent when no team exists |
| F005 | Navigate between pages | Sidebar > navigation groups Tasks / Reports / Manage team / Data & help; `st.navigation`, `PAGES`, `enabled_pages` | navigation | - | Pages Pre-planning, Product distribution, Products need feature Product distribution; Tickets and Jira connection need feature Ticket pre-planning |
| F006 | Open plugin-defined pages | Sidebar > navigation (default group Data & help); `run_plugin_page` | navigation | plugin specific | Only with installed plugins; replaced by conflict page while a merge is open |
| F007 | View notice about a new version / failed update | Sidebar footer > top; `_update_panel` | view | user settings (update state) |  |
| F008 | Check for updates | Sidebar footer > button "Check for updates"; `_manual_update_check` | action | - | Not offered if not installed with uv |
| F009 | Update and restart now | Sidebar footer > button "Update and restart now"; `_update_panel` | action | app installation | Only when a new version is available |
| F010 | View data path, as-of date and version | Sidebar footer > caption; `sidebar_footer` | view | - | As-of date comes from environment FORESPRINT_AS_OF if set |
| F011 | View sync state against the server | Sidebar > Git > status line; `_status_text` | view | git (cached state) | not shared yet / new from others / offline / last checked |
| F012 | Go to "Set up server" | Sidebar > Git > link; `_git_panel` | navigation | - | Link to Data folder page; only when no server is set |
| F013 | View open changes (file list) | Sidebar > Git > expander "Git: N pending change(s)"; `_git_panel` | view | git working tree | Expander opens automatically when changes or incoming commits exist |
| F014 | View what is new from others (not taken over yet) | Sidebar > Git > same expander; `_show_incoming` | view | git (fetched commits) |  |
| F015 | View what has changed (values before/after per file) | Sidebar > Git > expander > "What has changed?"; `_changes_view` | view | git diff of yaml files | Limited number of files; skipped if too large |
| F016 | Toggle line-by-line difference | Sidebar > Git > expander > toggle "Show line-by-line difference"; `_changes_view` | view | git diff | Also covers minutes |
| F017 | Edit commit message | Sidebar > Git > text input "Commit message"; `_refresh_commit_message` | edit | git (commit message, session) | Pre-filled from changes; follows changes until user edits it |
| F018 | Toggle use of pending tags | Sidebar > Git > checkbox "Set tags: ..."; `_git_panel` | setting | git tags (pending, session) | Tags are queued by the review (see review tag checkbox) |
| F019 | Save and share (commit, merge, push) | Sidebar > Git > button "Save and share"; `_sync_clicked` | action | git (commit, merge, push, tags) | Primary button; may go via merge request branch (Data folder setting) |
| F020 | Pull from server (no upload) | Sidebar > Git > button "Pull from server"; `_sync_clicked(push=False)` | action | git |  |
| F021 | Check state against server | Sidebar > Git > button "Check state"; `_fetch_clicked` | action | git (fetch) | Also runs automatically in background |
| F022 | Commit changes locally | Sidebar > Git > button "Commit changes"; `_commit_clicked` | action | git (commit, tags) | Secondary button when a server exists |
| F023 | View result of the last sync / commit | Sidebar > Git > success/error/notes box, expander "New from others", merge request link; `_show_sync_result` | view | git | Plain-language error with next step; Technical message expander |
| F024 | Share anyway despite new validation errors | Sidebar > Git > button "Share anyway"; `_show_sync_result` | action | git | Only after a sync stopped by the full validation |
| F025 | Confirm merging unrelated histories | Sidebar > Git > checkbox "Yes, merge both histories" + buttons Merge both histories / Cancel; `_unrelated_dialog` | action | git | Also links to Data folder to change the server address |
| F026 | Abort a hanging sync | Sidebar > Git > button "Abort running sync"; `_abort_sync_clicked` | action | git lock | Shown only when sync_busy or the sync ran very long |
| F027 | Refresh while a sync is running | Sidebar > Git > button "Refresh"; `_git_panel` | action | session state |  |
| F028 | Abort an open merge | Sidebar > Git > expander "Git: conflict" > "Abort merge"; `_abort_clicked` | action | git | Same action exists on Resolve conflicts page |
| F029 | Go back to the branch (detached HEAD) | Sidebar > Git > expander "Git: no branch" > "Back to the branch"; `_reattach_clicked` | action | git (rescue branch) |  |
| F030 | Enter Git name and email | Sidebar > Git > error box > inputs Name, Email address, Save; `_show_problem`, `_identity_clicked` | setting | global git config (user.name/email) | Appears inside an error message when identity is missing; also on Data folder and History pages |
| F031 | Fetch server state in background | Sidebar > Git (automatic, no control); `_background_fetch` | action | git (fetch) | Every 30 min per connected session; off with env FORESPRINT_NO_BACKGROUND_FETCH=1 |
| F032 | View notices of the previous action | All pages > top message box; `show_flash` | view | session state | Success / warning / info after a save with rerun |
| F033 | Validate before writing, show warnings, hint to share | All save buttons; `save` | action | all yaml files | Blocking errors stop the write; message tells to use Save and share or Commit changes |
| F034 | Discard stale form input when files changed | All team pages; `_discard_stale_inputs` | action | session state | Notice that unsaved input was dropped |
| F035 | Replace team pages by conflict resolution while a merge is open | All team pages, New team, plugin pages; `run_page` | navigation | git | Editing blocked until resolved or aborted |
| F036 | First start: choose / create / clone data folder | Every page when no data folder is found; `run_page` -> `page_data_dir(setup=True)` | navigation | git, data folder | Same screen as Data folder page, without remote/branch sections |
| F037 | "No team yet" screen with link to New team | Every team page without a team; `run_page` | navigation | - |  |

### 1. Tasks > Start

Page `page_start`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F038 | View state of the three tasks (Prepare sprint, Planning, Close sprint) | Start > three tiles; `page_start`, `start_tasks` | view | sprint file (absences, pre-planning, commitment, velocity) | Done tasks get a check icon and a secondary button |
| F039 | Jump to the next sensible page of a task | Start > tile > button "Open"; `_start_clicked` | navigation | session (selected sprint) | Target page depends on state: Absences, PO pre-planning, Planning, Review or Sprint calendar when no sprint is open |
| F040 | View setup checklist (Git, folder, server, sign-in, identity) | Start > box "Setup" with Open links; `_setup_checklist` | view | git config, data folder | Disappears when all items are ok |
| F041 | Hide setup checklist | Start > Setup box > button "Hide"; `_hide_setup` | action | session state | Only for the session |
| F042 | Open Forecast | Start > link under tiles; `page_start` | navigation | - |  |

### 2. Tasks > Prepare the sprint: absences

Page `page_absences`. Header "Planned absences".

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F043 | Select sprint (for step bar) | Absences > selectbox "Sprint"; `sprint_select` | navigation | session (board-sprint) | Shared choice across pages; the table itself shows several sprints regardless |
| F044 | Switch step (Absences / PO pre-planning / Planning / Review) | Absences > step bar; `_board_nav` | navigation | sprint file (state for check marks) | Check mark = recorded; Pre-planning step hidden without Product distribution |
| F045 | Read help on what counts as absence | Absences > expander "More about this: what counts, where the numbers come from"; `page_intro` | view | - |  |
| F046 | Choose number of future sprints shown | Absences > number input "Number of sprints"; `page_absences` | setting | session | Default horizon + 1 |
| F047 | Choose number of past sprints shown | Absences > number input "Past sprints"; `page_absences` | setting | session | Allows retroactive absences; frozen capacity of reviews does not change |
| F048 | View working days, holidays and finished sprints summary | Absences > caption + link "Periods in the sprint calendar"; `sprints_summary` | view | team calendar, holidays | Per-sprint detail is a column header tooltip |
| F049 | Enter absence days per person and sprint | Absences > data editor (person x sprint); `absence_matrix`, `edit_absences` | edit | absences (sprint files) | Half days; empty cell = person not in team; creates sprint files on save |
| F050 | View expected absence rate from history and uncertainty remedy | Absences > caption, info box, expander "What to do about an uncertain rate?"; `absence_derived_note` | view | absences history, team setting capacity.absence_history |  |
| F051 | Confirm "Nobody is absent" per sprint | Absences > subheader "Absence status" > data editor checkbox column; `_absence_states` | edit | absence state (sprint file) | Without it absences count as unknown and are estimated |
| F052 | View live capacity and Forecast PLAN preview (unsaved) | Absences > subheader "Capacity and forecast" > sentence + table; `page_absences` | view | calculation (not saved) | Shows how many units fit into next sprint |
| F053 | Save absences | Absences > button "Save absences"; `page_absences` | action | absences (sprint files) | Creates missing sprint files |
| F054 | Reset sprints back to "no information" | Absences > subheader "Reset absences" > multiselect + button; `_reset_absences` | action | sprint files (deleted) | Deletes sprint file of confirmed-but-empty future sprints |

### 3. Tasks > PO pre-planning

Page `page_preplanning`; feature Product distribution.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F055 | Go to Products when none exist | PO pre-planning > link "Add products"; `page_preplanning` | navigation | - |  |
| F056 | Select sprint | PO pre-planning > selectbox "Sprint"; `sprint_select` | navigation | session (board-sprint) |  |
| F057 | Switch step in step bar | PO pre-planning > step bar; `_board_nav` | navigation | sprint file |  |
| F058 | Enter team forecast for open sprints (commitment, not finished, additionally done) | PO pre-planning > expander "What if: team forecast for open sprints"; `_whatif_inputs` | edit | prognosis list in sprint file (only on save) | Recalculates Forecast PLAN of this view; saved as prognosis with the save button |
| F059 | Comment on the forecast | PO pre-planning > What-if expander > text input; `page_preplanning` | edit | prognosis comment (sprint file) | Only when an assumption was entered |
| F060 | View previous forecasts of open sprints | PO pre-planning > What-if expander > table + toggle "All forecast details"; `_prognosis_history` | view | prognoses (sprint files) |  |
| F061 | Enter announced absences for the sprint | PO pre-planning > expander "Announced absences" > data editor; `page_preplanning` | edit | expected_absences (sprint file) | Affects capacity until absences are confirmed in Planning (where they are prefilled) |
| F062 | View current forecast, forecast at planning, capacity, trend, range | PO pre-planning > top metrics + captions; `page_preplanning` | view | calculation | Respects the assumption and announced absences; formula tooltips |
| F063 | Enter intended amount per product (PO pre-planning) | PO pre-planning > data editor "PO pre-planning" column; `_product_editor` | edit | products.preplanned (sprint file) | Standard column shown for comparison; PO column with feature PO assignment |
| F064 | View distributable, intended sum and still free / too much | PO pre-planning > three metrics + caption; `_available_text` | view | calculation |  |
| F065 | View standard vs pre-planning comparison per product | PO pre-planning > table; `page_preplanning` | view | calculation | Duplicates the editor columns in compact form |
| F066 | View totals per PO | PO pre-planning > "Per PO" table; `by_po` | view | calculation | Only with feature PO assignment |
| F067 | Save PO pre-planning (and assumption as forecast) | PO pre-planning > button "Save PO pre-planning"; `page_preplanning` | action | sprint file (pre-planning, announced absences, prognoses), minutes | Writes a minutes file automatically |
| F068 | View minutes of PO pre-planning | PO pre-planning > expander "Minutes: ..."; `_protocols` | view | minutes files |  |
| F069 | Continue to planning | PO pre-planning > link "Continue to planning"; `page_preplanning` | navigation | - |  |

### 4. Tasks > Planning

Page `page_planning`. Header "Sprint Planning". Three steps in one page.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F070 | Select sprint | Planning > selectbox "Sprint"; `sprint_select` | navigation | session (board-sprint) | Changing sprint resets to step 1 |
| F071 | Switch step in step bar (Absences / PO pre-planning / Planning / Review) | Planning > step bar; `_board_nav` | navigation | sprint file |  |
| F072 | Release the frozen Forecast PLAN (correct a mistake) | Planning > expander "Forecast PLAN ... is frozen" > confirm checkbox + "Release freeze"; `_unfreeze_panel` | action | forecast_plan (sprint file), minutes (marked obsolete) | Only when a plan is frozen |
| F073 | View minutes of Planning | Planning > expander "Minutes: ..."; `_protocols` | view | minutes files |  |
| F074 | Switch planning step (1 Absences, 2 Forecast PLAN & planning, 3 Commitment) | Planning > stepper buttons; `_planning_stepper` | navigation | sprint file (done marks) | Second navigation bar below the board step bar |
| F075 | View known absences caption (period, holidays) | Planning > step 1 > caption; `_planning_absences` | view | calendar |  |
| F076 | Enter absences of this sprint | Planning > step 1 > data editor; `_planning_absences` | edit | absences (sprint file) | Prefilled with announced absences from PO pre-planning (same data as Absences page, one sprint) |
| F077 | View capacity and current forecast preview | Planning > step 1 > two metrics + warnings; `_planning_absences` | view | calculation | Warns when absences unconfirmed; info when sprint file has fixed capacity |
| F078 | Save absences and continue | Planning > step 1 > button; `_planning_absences` | action | absences (sprint file), minutes | Writes planning minutes |
| F079 | Confirm "Nobody is absent" and continue | Planning > step 1 > button; `_planning_absences` | action | absence state (sprint file), minutes | Same effect as checkbox on Absences page |
| F080 | Continue without confirmation | Planning > step 1 > button; `_planning_absences` | navigation | - | Leaves absences unknown |
| F081 | Next (to step 2) | Planning > step 1 > button "Next"; `_goto` | navigation | - |  |
| F082 | View capacity, current forecast, forecast at planning, plannable share, small items, range | Planning > step 2 > metrics and captions; `_planning_plan` | view | calculation | Formula tooltips; production split note |
| F083 | View calculation path | Planning > step 2 > expander "Calculation path"; `_derivation` | view | calculation | Same content as Forecast formulas expander |
| F084 | Back to the absences | Planning > step 2 > button; `_goto` | navigation | - | Only when capacity is estimated |
| F085 | Scratch calculation "Planned so far" | Planning > step 2 > number input + gauge; `_planning_plan` | view | session (not saved) | Only for teams without products |
| F086 | View suggestion from ticket pre-planning per product | Planning > step 2 > expander "Suggestion from the ticket pre-planning" + link to Tickets; `_planning_ticket_hint` | view | tickets, earmarks, projects (calculated) | Not adopted automatically |
| F087 | Enter planned amount per product (also pre-planning and production part) | Planning > step 2 > data editor; `_product_editor` | edit | products.planned / preplanned / production_planned (sprint file) | Prefilled from last PO pre-planning; pre-planning is editable here too |
| F088 | View planned vs Forecast PLAN gauge | Planning > step 2 > progress bar + too much / still free; `_capacity_gauge` | view | calculation |  |
| F089 | View production access capacity and overload warning | Planning > step 2 > caption/warning; `_production_hint` | view | people (production access), calculation | Needs feature Production access |
| F090 | View product chart for planning | Planning > step 2 > grouped bar chart; `_product_chart` | view | calculation |  |
| F091 | Save product values and continue | Planning > step 2 > button; `_planning_plan` | action | sprint file, minutes | Only enabled when values changed |
| F092 | Enter production-access part of the plan (teams without products) | Planning > step 2 > subheader "Topics with production access" > number input + "Save and continue"; `_planning_production` | edit | production_planned (sprint file) | Needs feature Production access without Product distribution |
| F093 | Next (to step 3) | Planning > step 2 > button "Next"; `_goto` | navigation | - |  |
| F094 | View current forecast and total planned per product | Planning > step 3 > captions; `_planning_commitment` | view | calculation |  |
| F095 | Enter commitment | Planning > step 3 > form > number input; `_planning_commitment` | edit | commitment (sprint file) | Prefilled from carry-over + backlog if empty |
| F096 | Enter cross-check values (carry-over, backlog, corrections) | Planning > step 3 > expander "Cross-check (optional)"; `_planning_commitment` | edit | planning block (sprint file) | Delta to Forecast PLAN is informational |
| F097 | Re-freeze Forecast PLAN to the current value | Planning > step 3 > checkbox "Freeze Forecast PLAN again"; `refreeze_offer` | action | forecast_plan (sprint file) | Offered only when frozen and current differ |
| F098 | Save planning (freeze plan, write minutes) | Planning > step 3 > form button "Save planning"; `_planning_commitment` | action | sprint file, minutes | First save freezes Forecast PLAN |
| F099 | Write planning minutes on every step save | Planning > steps 1-3 saves; `_planning_writer`, `save_with_protocol` | action | minutes files | No explicit control |

### 5. Tasks > Close the sprint (review)

Page `page_review`. Header "Sprint Review".

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F100 | Select sprint | Review > selectbox "Sprint"; `sprint_select` | navigation | session (board-sprint) | Default is the open review |
| F101 | Switch step in step bar | Review > step bar; `_board_nav` | navigation | sprint file |  |
| F102 | View minutes of Review | Review > expander "Minutes: ..."; `_protocols` | view | minutes files |  |
| F103 | View latest forecast of the team and deviation from velocity | Review > caption; `_review_prognosis_hint` | view | prognoses (sprint file) | Comes from PO pre-planning What-if |
| F104 | Enter done amount (velocity) | Review > form > number input; `page_review` | edit | velocity (sprint file) |  |
| F105 | Enter part of commitment not finished | Review > form > number input; `page_review` | edit | not_done (sprint file) | Optional |
| F106 | Enter additionally done amount | Review > form > number input; `page_review` | edit | additional_done (sprint file) | Optional |
| F107 | Enter scope creep (%) | Review > form > number input; `page_review` | edit | scope_creep (sprint file) | Feeds Analysis buffer recommendation |
| F108 | Enter done per product (and production part) | Review > form > "Done per product" data editor; `_product_editor` | edit | products.done / production_done (sprint file) | Needs feature Product distribution |
| F109 | Enter production-access part of done (teams without products) | Review > form > "Topics with production access"; `page_review` | edit | production_done (sprint file) | Needs feature Production access without Product distribution |
| F110 | Enter / freeze available person days | Review > form > number input "Available person days (PT) - frozen"; `page_review` | edit | capacity (sprint file) | Prefilled from people and absences |
| F111 | Choose to set Git tag TEAM/SPRINT on commit | Review > form > checkbox; `page_review` | setting | pending tags (session) -> git tag | Tag is only created later by commit/share in the sidebar |
| F112 | Save review | Review > form button "Save review"; `page_review` | action | sprint file, minutes, pending tag | Writes minutes file automatically |

### 6. Reports > Forecast

Page `page_forecast`. Header "Forecast <team>".

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F113 | View upcoming events (Review, Planning) with Open links | Forecast > box "Upcoming events"; `_next_dates` | navigation | sprint files | Third route into Planning/Review besides sidebar and Start |
| F114 | View Forecast PLAN tiles with range and absence state | Forecast > metrics per upcoming sprint; `page_forecast` | view | calculation | Tooltip: formula, capacity, plannable, small items, forecast at planning |
| F115 | View reliability notes (thin history, gaps, trend mode) | Forecast > info/warning boxes; `_forecast_notes` | view | calculation |  |
| F116 | View table of upcoming sprints (capacity, trend, plan, frozen, difference, plannable, small items) | Forecast > dataframe; `page_forecast` | view | calculation |  |
| F117 | Get warned about sprints with estimated capacity (link text to Absences) | Forecast > warning; `page_forecast` | view | calculation | Text only, no link |
| F118 | What-if team forecast for open sprints (not saved) | Forecast > expander "What if: team forecast for open sprints"; `_whatif_panel` | edit | session only | Same inputs as PO pre-planning what-if, but nothing is saved |
| F119 | View planning total vs Forecast PLAN of current sprint | Forecast > info box; `page_forecast` | view | sprint file |  |
| F120 | View history table of last 10 sprints | Forecast > subheader "History" > dataframe; `page_forecast` | view | sprint files | Capacity, commitment, velocity, normalized velocity, fulfillment, scope creep |
| F121 | View calculation formulas with inputs and sources | Forecast > expander "Calculation: formulas" > inputs, calculation, values table; `_formula_expander`, `_derivation` | view | calculation |  |
| F122 | Select sprint for the formulas | Forecast > formulas expander > selectbox "Sprint"; `sprint_select` | navigation | session (formula-sprint, board-sprint) |  |
| F123 | View line chart of commitment/plan, velocity, normalized velocity | Forecast > altair chart; `_chart` | view | calculation |  |
| F124 | Write report FORECAST.md | Forecast > button "Write report FORECAST.md"; `page_forecast` | action | FORECAST.md in team folder | Also on command line; appears as open change in Git |
| F125 | Create and download Excel list | Forecast > buttons "Create Excel list" then "Download Excel list"; `_excel_download` | action | none (download only) | Counterpart import lives on Settings page |

### 7. Reports > Analysis

Page `page_analysis`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F126 | View spread (conservative / medium / optimistic Forecast PLAN) | Analysis > subheader "Spread" > table; `page_analysis` | view | calculation |  |
| F127 | Enter remaining amount, basis and project share | Analysis > "When will it be done?" > form (number, radio, number, Calculate); `page_analysis` | edit | session only | Plannable share vs entire forecast |
| F128 | View completion forecast (per sprint, 50 % / 85 %, probability chart, notes) | Analysis > "When will it be done?" > metrics + bar chart; `page_analysis`, `completion` | view | calculation (Monte Carlo) | Appears after Calculate |
| F129 | View focus factor (average and per sprint) | Analysis > subheader "Focus factor" > metric + table; `page_analysis` | view | calculation |  |
| F130 | View buffer recommendation for unplanned work | Analysis > subheader "Buffer for unplanned work"; `buffer_hint` | view | scope creep (sprint files), team setting small items share |  |

### 8. Reports > Product distribution

Page `page_products`. Evaluation only; feature Product distribution.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F131 | Go to Products when none exist | Product distribution > link "Add products"; `page_products` | navigation | - |  |
| F132 | Select sprint | Product distribution > selectbox "Sprint"; `sprint_select` | navigation | session (board-sprint) |  |
| F133 | Jump to the board that changes the values (pre-planning, planning, review) | Product distribution > three links "Change: ..."; `page_products` | navigation | - | Values cannot be edited here by design |
| F134 | View product x standard / pre-planning / planning / done table | Product distribution > dataframe; `_product_table` | view | calculation | Same figures as editors on the three boards |
| F135 | View production access capacity and overload warning | Product distribution > caption/warning; `_production_hint` | view | people, calculation | Same hint as on Planning |
| F136 | View grouped bar chart per product | Product distribution > chart; `_product_chart` | view | calculation |  |
| F137 | View totals per PO | Product distribution > "Per PO" table; `by_po` | view | calculation | Same as on PO pre-planning (plus planning and done) |
| F138 | Choose number of sprints for history | Product distribution > number input "Number of sprints"; `page_products` | setting | session |  |
| F139 | Choose metric for history (done / planned / pre-planned) | Product distribution > radio "Metric"; `page_products` | setting | session |  |
| F140 | View stacked history chart per product | Product distribution > chart; `_history_chart` | view | sprint files |  |
| F141 | View balance against standard distribution (chart + table) | Product distribution > subheader "Balance against the standard distribution"; `_balance_section` | view | sprint files (done per product) |  |

### 9. Reports > Tickets

Module `tickets_view.py`; feature Ticket pre-planning. Filter on top applies to all tabs; tabs Overview, Sprints, Refinement, Open points, Assignment, Import, Settings.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F142 | Filter by products | Tickets > multiselect "Products"; `_filter` | setting | session | Only with feature Product distribution; hides, does not change the distribution |
| F143 | Filter by projects | Tickets > multiselect "Projects"; `_filter` | setting | session | Options depend on product filter |
| F144 | Show / hide tickets without a project | Tickets > checkbox; `_filter` | setting | session |  |
| F145 | View projects with target, traffic light, last sprint (range) and open counts | Tickets > Overview > table; `project_rows` | view | tickets, projects, forecast (calculated) | Includes pseudo-rows "<product> without project" |
| F146 | View warnings (no budget, circular dependencies, no range) | Tickets > Overview > messages; `_overview` | view | calculation |  |
| F147 | View timeline (traffic light bars, optimistic/conservative range, target diamond) | Tickets > Overview > altair chart; `_timeline_chart` | view | calculation |  |
| F148 | Choose number of sprint columns | Tickets > Sprints > number input; `_sprint_columns` | setting | session |  |
| F149 | Switch board view (cards with buttons / drag and drop) | Tickets > Sprints > radio "View"; `_sprint_columns` | setting | session | Drag and drop only reachable by this radio |
| F150 | View sprint columns with budget / used / free and ticket cards | Tickets > Sprints > columns; `_sprint_column` | view | calculation | Limited to 30 cards per sprint; legend R/U/M, bold = fixed by tracker, pencil = earmark |
| F151 | Earmark ticket for previous / next sprint, pin, or release | Tickets > Sprints > card buttons; `_card_buttons`, `set_earmark` | action | preplan.yaml (earmarks) | Not available for tickets in a tracker sprint (fixed) |
| F152 | Drag a ticket card to another sprint (earmark) or onto release bar | Tickets > Sprints > drag and drop board; `_drag_board`, `sprint_board` | action | preplan.yaml (earmarks) |  |
| F153 | Earmark or release a ticket by form (ticket, sprint, note) | Tickets > Sprints > subheader "Earmark and release"; `_earmark_form` | edit | preplan.yaml (earmarks incl. note) | Only place where the earmark note can be edited |
| F154 | Choose sprints to hand over and whether to replace PO values | Tickets > Sprints > Handover > number input + checkbox; `_handover` | setting | session | Needs feature Product distribution |
| F155 | View handover preview (sprint, product, so far, proposal, notice) | Tickets > Sprints > Handover > table; `_handover`, `handover_rows` | view | calculation | Median variant |
| F156 | Adopt ticket sums into PO pre-planning | Tickets > Sprints > Handover > button "Adopt into the PO pre-planning"; `_handover` | action | products.preplanned (sprint files) | Writes the same values as the PO pre-planning editor; also CLI `tickets --handover` |
| F157 | View refinement list (tickets with rough or own estimate per sprint) | Tickets > Refinement > table + unclear warning; `_refinement` | view | tickets, preplan (calculated) |  |
| F158 | View open points (tickets that cannot be distributed) | Tickets > Open points > table; `_open_points` | view | tickets (calculated) | Remedy text points to Settings tab or the ticket system |
| F159 | Choose whether to edit project or product rules | Tickets > Assignment > radio "Rule for"; `rule_editor` | setting | session | Product rules apply to tickets without a project |
| F160 | Select the project / product whose rule is edited | Tickets > Assignment > selectbox; `rule_editor` | navigation | session |  |
| F161 | Edit assignment rule expression | Tickets > Assignment > text area "Rule"; `rule_editor` | edit | projects.yaml / products.yaml (match) | Syntax errors with position; field set from Jira connection page (rule fields) |
| F162 | Insert condition by field / operator / values | Tickets > Assignment > expander "Insert condition"; `_insert_helper` | edit | session (rule text) |  |
| F163 | Show rule syntax example | Tickets > Assignment > expander "Example" | view | - |  |
| F164 | View tickets hit by the rule and conflicts with other rules | Tickets > Assignment > count + table; `rule_hits` | view | tickets, rules | Live preview before saving |
| F165 | Save rule | Tickets > Assignment > button "Save rule"; `rule_editor` | action | projects.yaml or products.yaml |  |
| F166 | View which project/product each open ticket belongs to and why | Tickets > Assignment > Result (summary per product + table); `assignment_rows` | view | tickets (calculated) | Flags contradictions and unmatched tickets |
| F167 | View active ticket source and go to Jira connection | Tickets > Import > caption + link; `_import` | navigation | team.yaml tracker | Source itself is chosen on the Jira connection page |
| F168 | Read tickets from Jira | Tickets > Import > button "Read tickets from Jira"; `_fetch_jira` | action | session (fetched tickets) | Only if source is Jira; needs token (keychain or env) |
| F169 | Upload ticket CSV | Tickets > Import > file uploader "CSV file"; `_import` | action | session (parsed tickets) | Without network access |
| F170 | View import preview by kind (new, changed, done, missing, unassigned, epics, unclear, earmarks, sprints) | Tickets > Import > expanders; `_import_preview` | view | calculation | Limited rows per kind |
| F171 | Apply import | Tickets > Import > button "Apply changes"; `_import_preview` | action | tickets.yaml, preplan.yaml, projects.yaml | Nothing written before confirmation |
| F172 | Check label changes (planned_for_<sprint>) | Tickets > Import > "Write earmarks to Jira as labels" > button "Check label changes"; `_label_section` | action | Jira (read) | Section only if tracker.kind is jira and tracker.write_labels is true in team.yaml |
| F173 | View label changes preview | Tickets > Import > label section > table; `_label_section` | view | Jira labels |  |
| F174 | Write labels to Jira | Tickets > Import > label section > button "Write to Jira"; `_label_section` | action | Jira (write) | Only write-back to Jira in the app; re-checks before writing |
| F175 | Edit projects (name, product, target, priority, budget basis) | Tickets > Settings > data editor; `_projects_editor` | edit | projects.yaml | Id and rule not editable here; save button "Save projects" |
| F176 | Create project (id, name, product, target, rule) | Tickets > Settings > expander "Create project"; `_add_project_form` | action | projects.yaml | Rule can also be entered here and on Assignment tab |
| F177 | Remove project | Tickets > Settings > expander "Remove project"; `_remove_project_form` | action | projects.yaml, tickets.yaml | Tickets become "without project" |
| F178 | Edit own estimates per ticket | Tickets > Settings > data editor + "Save estimates"; `_estimates_editor` | edit | preplan.yaml (estimates) | Not overwritten by import |

### 10. Manage team > Sprint calendar

Page `page_calendar`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F179 | Read help on sprint sequence and differing sprints | Sprint calendar > expander; `page_intro` | view | - |  |
| F180 | Choose number of sprints shown | Sprint calendar > number input; `page_calendar` | setting | session |  |
| F181 | Edit last day of a sprint (following sprints shift) | Sprint calendar > data editor; `apply_calendar` | edit | sprint files (end date) | Start and working days are read-only; status column |
| F182 | Create or save sprints (create sprint files in advance) | Sprint calendar > button "Create or save sprints"; `page_calendar` | action | sprint files | Absences and boards also create sprint files implicitly |

### 11. Manage team > People

Page `page_people`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F183 | Read help on leaving, FTE change, part-time | People > expander; `page_intro` | view | - |  |
| F184 | Show / hide former members | People > toggle "Show former"; `page_people` | setting | session |  |
| F185 | Add a person / membership period | People > data editor (add row); `people_from_table` | edit | people.yaml | IDs assigned automatically |
| F186 | End membership (until date) | People > data editor column "until" | edit | people.yaml | Never delete; deleting needs confirmation checkbox |
| F187 | Set FTE share / change FTE over time | People > data editor column "FTE" (new row with same name) | edit | people.yaml |  |
| F188 | Set per-person country, region and work week | People > data editor columns Country, Region, Work week | edit | people.yaml | (Team) = team setting; team default lives on Settings page |
| F189 | Mark person as authorized for production access | People > data editor column "Production access" | edit | people.yaml | Only with feature Production access |
| F190 | Confirm deletion of wrongly entered rows | People > warning + checkbox "Yes, the rows were wrong entries" | action | people.yaml |  |
| F191 | Save people | People > button "Save people"; `page_people` | action | people.yaml |  |

### 12. Manage team > Products

Page `page_product_list`; feature Product distribution.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F192 | Read help on handing over / adding a product | Products > expander; `page_intro` | view | - |  |
| F193 | Show / hide former products | Products > toggle "Show former"; `page_product_list` | setting | session |  |
| F194 | Add a product | Products > data editor (add row); `products_from_table` | edit | products.yaml |  |
| F195 | Set responsible PO | Products > data editor column "PO" | edit | products.yaml | Only with feature PO assignment |
| F196 | Set agreed fixed share (%) | Products > data editor column "Share (%)" | edit | products.yaml | Empty = split evenly (standard distribution) |
| F197 | Set period from / until (hand over a product) | Products > data editor columns from / until | edit | products.yaml |  |
| F198 | Confirm deletion of wrongly entered rows | Products > warning + checkbox | action | products.yaml |  |
| F199 | Save products | Products > button "Save products"; `page_product_list` | action | products.yaml |  |

### 13. Manage team > Settings

Page `page_settings`; form built from `settings.py` (`_settings_form`). One row per team setting.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F200 | Set display name | Settings > text input "Display name" | setting | team.yaml |  |
| F201 | Set estimation unit | Settings > select "Estimation unit" | setting | team.yaml |  |
| F202 | Switch feature Product distribution | Settings > select "Product distribution" | setting | team.yaml (features.products) | Shows/hides pages PO pre-planning, Product distribution, Products |
| F203 | Switch feature PO assignment | Settings > "PO assignment" | setting | team.yaml (features.po) | Shows PO column and per-PO tables |
| F204 | Switch feature Production access | Settings > "Production access" | setting | team.yaml (features.production) | Shows People column and production fields |
| F205 | Switch feature Ticket pre-planning | Settings > "Ticket pre-planning" | setting | team.yaml (features.tickets) | Shows pages Tickets and Jira connection |
| F206 | Set country (holidays) | Settings > "Country" | setting | team.yaml | Overridden per person on People |
| F207 | Set region (state, province) | Settings > "Region" | setting | team.yaml | Overridden per person on People |
| F208 | Set work week | Settings > "Work week" | setting | team.yaml | Overridden per person on People |
| F209 | Set Scrum events deduction in % | Settings > number input (synced with PT field); `_overhead_widgets` | setting | team.yaml (capacity.overhead_share) | Same value as the PT field, converted live |
| F210 | Set Scrum events deduction in PT per person | Settings > number input (synced with % field) | setting | team.yaml (capacity.overhead_days) |  |
| F211 | Set absence history length | Settings > "Absence history (number of sprints)" | setting | team.yaml | Drives expected absences shown on Absences page |
| F212 | Set sprint length in calendar days | Settings > "Sprint length" | setting | team.yaml | Single sprints adjustable on Sprint calendar |
| F213 | Set sprint numbering | Settings > "Sprint numbering" (only while no sprint file exists) | setting | team.yaml | Afterwards fixed; see Change sprint IDs |
| F214 | Set start of first sprint | Settings > "Start of the first sprint" (only while no sprint file exists) | setting | team.yaml | Asked first when creating a team |
| F215 | Set ID of the first sprint | Settings > "ID of the first sprint" (only while no sprint file exists) | setting | team.yaml | After sprint files exist replaced by Change sprint IDs |
| F216 | Set reference capacity | Settings > "Reference capacity (PT)" | setting | team.yaml |  |
| F217 | Set averaging window | Settings > "Ø over sprints" | setting | team.yaml |  |
| F218 | Set trend mode | Settings > "Trend mode" | setting | team.yaml | Forecast page warns when not constant, pointing here |
| F219 | Set plannable share (%) | Settings > "Plannable share (%)" | setting | team.yaml |  |
| F220 | Set forecast horizon (sprints) | Settings > "Forecast horizon (sprints)" | setting | team.yaml | Also drives default count on Absences page |
| F221 | Set decimal places of Forecast PLAN | Settings > "Decimal places Forecast PLAN" | setting | team.yaml |  |
| F222 | Set basis of standard distribution per product | Settings > "Standard distribution per product based on" | setting | team.yaml (forecast.product_basis) | Another budget basis exists per project (Tickets) and in team.yaml tracker |
| F223 | Review changes before saving and save | Settings > form button "Save" then diff table + retroactive warning; `page_settings` | action | team.yaml | Two-stage: submit shows diff, save happens in same run |
| F224 | Change sprint IDs (rename sprint, renumber following) | Settings > subheader "Change sprint IDs" > select, text, preview, button; `_rename_sprints_section` | action | sprint files, minutes (renamed) | Only when sprint files exist |
| F225 | Import from Excel (upload, preview, apply) | Settings > subheader "Import from Excel"; `_excel_import_section` | action | team files (values from workbook) | Counterpart of Forecast > Create Excel list |

### 14. Manage team > Jira connection

Module `jira_setup.py`; feature Ticket pre-planning. Edits the `tracker` section of `team.yaml`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F226 | Read intro and install hint | Jira connection > expander; `page_intro` | view | - |  |
| F227 | Choose ticket source (Jira / CSV export) | Jira connection > form > select "Ticket source" | setting | team.yaml (tracker.kind) | Import tab on Tickets page only shows it |
| F228 | Set Jira address | Jira connection > form > "Jira address" | setting | team.yaml (tracker.base_url) |  |
| F229 | Set query (JQL) | Jira connection > form > "Query (JQL)" | setting | team.yaml (tracker.query) |  |
| F230 | Set field names for estimate, remaining work, epic | Jira connection > form > three inputs (text or select with suggestions after test) | setting | team.yaml (tracker.fields) | Suggestions only after a successful test |
| F231 | Set label of refined tickets | Jira connection > form > text input | setting | team.yaml (tracker.refined_label) |  |
| F232 | Set order of assignment criteria (epic / component / label) | Jira connection > form > select "Project assignment: order of the criteria" | setting | team.yaml (tracker.project_match_order) | Rules themselves are edited on Tickets > Assignment |
| F233 | Define additional fields for assignment rules | Jira connection > form > data editor | edit | team.yaml (tracker.rule_fields) | Blocked while a rule uses a removed field |
| F234 | Test connection (account, field suggestions, ticket count) | Jira connection > form button "Test connection"; `run_probe` | action | Jira (read), session | Needs token |
| F235 | View test result | Jira connection > success/info/warnings; `_show_probe` | view | session |  |
| F236 | Save connection settings | Jira connection > form button "Save"; `_save` | action | team.yaml (tracker) |  |
| F237 | View token source (environment or keychain) | Jira connection > subheader "Token"; `_token_status` | view | OS keychain / environment |  |
| F238 | Store, replace or remove token in keychain | Jira connection > Token form; `_token_form` | action | OS keychain | Needs valid saved address first; hidden input |
| F239 | Read how to set the token as environment variable | Jira connection > expander "Set the token as environment variable"; `_token_howto` | view | - | Only when no token or no usable keychain |

### 15. Manage team > New team

Page `page_new_team`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F240 | Read help on first sprint and optional areas | New team > expander; `page_intro` | view | - |  |
| F241 | Enter team key (folder name) | New team > text input; `page_new_team` | edit | team folder name | Checks clash incl. case-insensitive file systems |
| F242 | Enter first sprint (numbering, start, ID) | New team > section "First sprint" > three inputs; `_settings_form(first_sprint=True)` | setting | team.yaml | Same settings as set.num / set.first / set.firstid |
| F243 | Enter all other team settings | New team > section "Further settings"; `_settings_form` | setting | team.yaml | Same form as Settings page |
| F244 | Create team | New team > button "Create team"; `page_new_team` | action | team.yaml, people.yaml | Selects the new team |
| F245 | Go to People after creating | New team > link "Next: add people" | navigation | - |  |

### 16. Data & help > Data folder

Page `page_data_dir`; also used as first-start screen.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F246 | View current data folder and Git repository | Data folder > top captions; `page_data_dir` | view | data folder, git |  |
| F247 | View Git problems of the folder | Data folder > error box; `_show_problem` | view | git |  |
| F248 | View configured server and reasons blocking changes | Data folder > Server (remote); `_remote_status` | view | git remote |  |
| F249 | Enter server address | Data folder > Server (remote) > text input (+ checkbox for unencrypted http); `_remote_section` | edit | session | Credentials in the address are rejected |
| F250 | Test connection to server | Data folder > button "Check connection"; `_remote_check` | action | git (ls-remote) | Changes nothing |
| F251 | Save server address | Data folder > button "Save"; `_remote_save` | action | git remote config |  |
| F252 | Save anyway (offline) / confirm right data repository | Data folder > warning + button; `_remote_offer` | action | git remote config |  |
| F253 | Share via merge request (toggle) | Data folder > checkbox "Share via merge request"; `_share_mode_setting` | setting | git config foresprint.share | Changes what sidebar Save and share does |
| F254 | Choose kind of server (GitLab, GitHub, Forgejo, other) | Data folder > select; `_host_changed` | setting | git config foresprint.host | Only when merge request sharing is on |
| F255 | Merge automatically when pipeline is green | Data folder > toggle; `_auto_merge_changed` | setting | git config | Only for GitLab / other |
| F256 | Switch on credential helper | Data folder > Set up sign-in > button; `_signin_section` | action | global git config | Https servers only |
| F257 | Store access token with Git credential helper and verify | Data folder > Set up sign-in > form "Save and check token"; `_signin_section` | action | OS credential store | Separate from Jira token on Jira connection page |
| F258 | Delete stored sign-in for the server | Data folder > Set up sign-in > checkbox + button | action | OS credential store |  |
| F259 | Switch branch | Data folder > Branch > select + "Switch branch"; `_branch_section` | action | git | Only with 2+ branches and no open changes |
| F260 | Create .gitattributes (line endings) | Data folder > Set line endings > button; `_attributes_section` | action | git (.gitattributes) | Only when missing |
| F261 | Switch to / remove a recently used folder | Data folder > Recently used list > Switch / Remove; `_switch_clicked`, `_forget_clicked` | action | user settings (recent folders) | Same switch exists in sidebar expander |
| F262 | Choose an existing folder | Data folder > tab "Choose existing folder" > path + Browse + Apply; `_path_input` | action | user settings, session | Browse opens system folder dialog |
| F263 | Use folder without Git | Data folder > tab Choose > button "Use without Git" | action | user settings (without-Git list) |  |
| F264 | Create Git repository in the chosen folder | Data folder > tab Choose > button | action | git init |  |
| F265 | Create new data repository | Data folder > tab "Create new data repository" | action | git init, folders |  |
| F266 | Clone repository | Data folder > tab "Clone repository" > address, target, Clone | action | git clone | Ordinary way for colleagues joining a team |

### 17. Data & help > App settings

Page `page_app_settings`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F267 | Choose theme (as system, light, dark) | App settings > radio "Theme"; `_theme_changed` | setting | user settings (theme) | Reloads the page; language is set in the sidebar instead |
| F268 | Read intro on where user settings live | App settings > expander; `page_intro` | view | - |  |

### 18. Data & help > Changes and history

Page `page_history`; tabs Open changes, History, Tags. Disabled while a merge is open.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F269 | View merge-open lock warning | Changes and history > warning; `page_history` | view | git |  |
| F270 | View open changes with line counts | Changes and history > Open changes; `_tab_changes` | view | git working tree | Sidebar shows the same list in a smaller form |
| F271 | Discard selected or all changes | Changes and history > Open changes > buttons + confirmation; `_discard_go` | action | git working tree (backup in .git trash) | Only place to discard changes |
| F272 | Choose history scope (team, sprint, file, data folder) | Changes and history > History > radio + selectboxes; `_tab_history` | navigation | session |  |
| F273 | View history entries and their files | Changes and history > History > select + file list | view | git log |  |
| F274 | Restore an earlier state | Changes and history > History > button "Restore this state" | action | git (new commit) |  |
| F275 | Take back a single change | Changes and history > History > button "Take back this change" | action | git (new commit) | Not for merges |
| F276 | View tags (and compare with server) | Changes and history > Tags > table + button "Compare with server"; `_tab_tags` | view | git tags | Network only on click |
| F277 | Upload local-only tag | Changes and history > Tags > select + button | action | git tags |  |
| F278 | Set tag at an earlier state | Changes and history > Tags > form "New tag" | action | git tags | Review checkbox queues the tag automatically instead |
| F279 | Delete tag locally and on server | Changes and history > Tags > select + checkbox + button | action | git tags |  |
| F280 | Enter Git name and email on demand | Changes and history > error box | setting | global git config | See sidebar identity |

### 19. Data & help > Check

Page `page_check`.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F281 | View data findings (errors and warnings) of all teams | Check > messages per team; `check_all` | view | all teams' files | Findings are otherwise only shown at save time for the saved files |

### 20. Data & help > Help

Page `page_help`; tabs Workflow, Terms, Input fields, Team settings, Collaboration (Git), Command line.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F282 | Read workflow steps with links to the pages | Help > Workflow | navigation | - |  |
| F283 | Read terms and capacity sources | Help > Terms | view | - |  |
| F284 | Read input field help | Help > Input fields | view | - | Same text as field tooltips on the pages |
| F285 | Read team settings table and go to Settings | Help > Team settings | view | - | Same text as Settings tooltips |
| F286 | Read Git collaboration help | Help > Collaboration (Git) | view | - |  |
| F287 | Read command-line reference | Help > Command line | view | - |  |

### 21. Not in navigation > Resolve conflicts

Page `page_conflicts`; replaces all team pages while a merge or conflict markers exist.

| ID | Function | Where today | Kind | Data touched | Notes |
|---|---|---|---|---|---|
| F288 | Toggle line-by-line difference | Resolve conflicts > toggle | view | git |  |
| F289 | Choose My change / Other change per entry or file | Resolve conflicts > radios per key / per file | edit | conflicted yaml files |  |
| F290 | Apply decisions and share | Resolve conflicts > button; `_resolve_clicked` | action | git, yaml files | Continues the sync that stopped |
| F291 | Abort merge | Resolve conflicts > button; `_abort_clicked` | action | git | Same as sidebar Abort merge |
| F292 | Restore last saved state of file with conflict markers | Resolve conflicts > button per file; `_restore_clicked` | action | git, yaml file | Only when markers remain without running merge |

## 2. Duplicates and scattering

Each block lists the IDs involved and what differs.

| # | Function / data | IDs | What differs |
|---|---|---|---|
| D01 | Per-product planned amount (preplanned / planned / done) | F063, F087, F156, F134, F065, F086, F108 | Pre-planning is editable on F063 AND F087 (prefilled from it) AND written by F156 from tickets; planned only in F087; done only in F108; F134 is read-only; F086 shows ticket sums without adopting them. |
| D02 | Absences of one sprint | F049, F076, F061, F051, F079, F054 | F049 edits many sprints; F076 edits one sprint (prefilled with F061, the announced/expected absences, a separate field); confirm-nobody exists as checkbox (F051) and as button (F079); only F054 deletes the state again. |
| D03 | Capacity / Forecast PLAN preview numbers | F052, F077, F082, F062, F114, F116 | Same calculation shown six times with different inputs (unsaved absences, current, with assumption, frozen) and slightly different metric sets. |
| D04 | What-if team forecast | F118, F058, F060, F103 | Identical input form (commitment, not finished, additionally done); on Forecast nothing is saved, on PO pre-planning it is saved as a prognosis and later compared on Review. |
| D05 | Calculation path / formulas | F121, F083, F122 | Same derivation component; Forecast has its own sprint selector (formula-sprint), Planning uses the board sprint. |
| D06 | Choosing the sprint | F043, F056, F070, F100, F132, F122 | Six selectboxes all bound to one session value (board-sprint) but each placed on its own page; Forecast, Analysis, Tickets have none. |
| D07 | Reaching a sprint task (Planning / Review / Absences / Pre-planning) | F005, F039, F044, F057, F071, F101, F113, F133, F074 | Eight different routes: sidebar, Start tiles, step bar on four pages, Forecast events box, links on Product distribution; Planning additionally has its own 3-step stepper. |
| D08 | Git: committing and sharing | F022, F019, F020, F021, F253, F254, F255, F251, F259 | Actions live in the sidebar, but what they do (merge request, host kind, auto-merge, branch, server) is configured only on Data folder; the sidebar only links there (F012). |
| D09 | Git: seeing and undoing changes | F013, F015, F016, F270, F271, F274, F275, F028, F291 | Open changes list and value diff appear in the sidebar and again on Changes and history; discard/restore/revert exist only on the page; abort merge exists in sidebar and on Resolve conflicts. |
| D10 | Git: tags | F111, F018, F278, F277, F279, F276 | Tag is queued on Review, toggled in the sidebar and created at commit; setting/uploading/deleting tags is only on Changes and history. |
| D11 | Git identity (name / email) | F030, F280 | Same inline form inside any Git error message (sidebar, Data folder, History); no fixed place to set it. |
| D12 | Switching the data folder | F002, F261, F262, F036, F040 | Recent-folder switcher in sidebar and on Data folder; choose/create/clone only on Data folder; first-start screen reuses the Data folder page; Start checklist links there. |
| D13 | Server / sign-in | F249, F257, F238, F012, F040, F258 | Git sign-in token (credential helper, Data folder) and Jira token (OS keychain, Jira connection) are two separate stores with two separate forms; Start checklist and sidebar only link to Data folder. |
| D14 | Team settings in several places | F202, F205, F242, F243, F225, F227, F236, F222, F206, F188, F208 | The same settings form appears on Settings and on New team; Excel import also writes team values; the tracker part of team.yaml is edited on Jira connection (not on Settings); calendar defaults (country, region, work week) are on Settings but overridden per person on People. |
| D15 | User settings (per user, not in team) | F003, F267, F002 | Language is in the sidebar, theme on App settings, recent folders in the sidebar: three places for per-user settings. |
| D16 | Sprint ID / sprint calendar settings | F213, F214, F215, F212, F224, F181, F182, F242 | First sprint is chosen on New team / Settings (only until sprint files exist), then renamed under Settings > Change sprint IDs; length per sprint is on Sprint calendar; creating sprint files is possible on Sprint calendar, Absences, and every board save. |
| D17 | Projects and products master data | F194, F196, F175, F176, F161, F159, F222, F232 | Products are edited on Products, but their assignment rule is edited on Tickets > Assignment; projects are edited on Tickets > Settings; the criteria order for matching is on Jira connection; budget basis exists per team (Settings), per project (Tickets > Settings) and in yaml only. |
| D18 | Project rule entry | F176, F161, F162, F165 | A rule can be typed when creating a project (Settings tab) and edited later on the Assignment tab; fields usable in rules are defined on Jira connection (F233). |
| D19 | Earmarking a ticket | F151, F152, F153, F174 | Three UI ways to set the same earmark (buttons, drag, form); only the form edits the note; label write-back to Jira exports the same earmarks and is hidden behind a YAML flag. |
| D20 | Ticket data entry | F168, F169, F234, F227, F178, F230, F167 | Source choice is on Jira connection, import on Tickets > Import (which only displays the source); connection test (count only) is separate from the import preview; own estimates (Tickets > Settings) override Jira fields set on Jira connection. |
| D21 | Per-PO totals | F066, F137 | Same table twice; PO pre-planning shows standard + pre-planning, Product distribution adds planning and done. |
| D22 | Production access | F204, F189, F087, F092, F108, F109, F089, F135 | Feature flag in Settings, person flag on People, planned part in Planning (two different widgets depending on Product distribution), done part in Review (two widgets), overload hint repeated on Planning and Product distribution. |
| D23 | Minutes (protocols) | F068, F073, F102, F099, F067, F098, F112 | Written implicitly by three save buttons and viewable only in an expander on the same board; no page lists all minutes. |
| D24 | Forecast freeze | F116, F062, F082, F072, F097 | Frozen value is shown on three views; releasing is in an expander at the top of Planning, re-freezing is a checkbox in step 3. |
| D25 | History / evolution views | F120, F140, F060, F273, F123 | Sprint history (Forecast), per-product history (Product distribution), prognosis history (PO pre-planning) and Git history (Changes and history) are four unrelated histories. |
| D26 | Export / import of numbers | F125, F225, F124, F169, F156 | Excel export is on Forecast, Excel import on Settings; FORECAST.md on Forecast; CSV import on Tickets; ticket sums handover on Tickets. |
| D27 | Findings / validation | F281, F033, F023 | Check page lists findings of all teams; the same validation runs on every save and again before sharing (validation list in sidebar, Share anyway). |
| D28 | Setup guidance | F040, F012, F036, F246, F011 | Setup checklist (Start), Set up server link (sidebar), first-start screen and Data folder page express the same state in four ways. |
| D29 | Help duplicates | F284, F285, F045, F192, F179, F183, F240, F226 | Field and setting help is repeated in tooltips, per-page expanders and the Help page. |
| D30 | Product share / default distribution | F196, F222, F064, F082, F219 | Fixed share (Products), basis plan/roadmap and plannable share (Settings) jointly determine the standard shown on boards; none of those pages show the resulting standard. |

## 3. Hidden or hard to find

### Behind an expander or popover (collapsed by default or placed in a sidebar expander) (35)

| ID | Function |
|---|---|
| F002 | Switch to a recently used data folder |
| F013 | View open changes (file list) |
| F014 | View what is new from others (not taken over yet) |
| F015 | View what has changed (values before/after per file) |
| F016 | Toggle line-by-line difference |
| F028 | Abort an open merge |
| F029 | Go back to the branch (detached HEAD) |
| F045 | Read help on what counts as absence |
| F050 | View expected absence rate from history and uncertainty remedy |
| F058 | Enter team forecast for open sprints (commitment, not finished, additionally done) |
| F059 | Comment on the forecast |
| F060 | View previous forecasts of open sprints |
| F061 | Enter announced absences for the sprint |
| F068 | View minutes of PO pre-planning |
| F072 | Release the frozen Forecast PLAN (correct a mistake) |
| F073 | View minutes of Planning |
| F083 | View calculation path |
| F086 | View suggestion from ticket pre-planning per product |
| F096 | Enter cross-check values (carry-over, backlog, corrections) |
| F102 | View minutes of Review |
| F118 | What-if team forecast for open sprints (not saved) |
| F121 | View calculation formulas with inputs and sources |
| F122 | Select sprint for the formulas |
| F162 | Insert condition by field / operator / values |
| F163 | Show rule syntax example |
| F170 | View import preview by kind (new, changed, done, missing, unassigned, epics, unclear, earmarks, sprints) |
| F176 | Create project (id, name, product, target, rule) |
| F177 | Remove project |
| F179 | Read help on sprint sequence and differing sprints |
| F183 | Read help on leaving, FTE change, part-time |
| F192 | Read help on handing over / adding a product |
| F226 | Read intro and install hint |
| F239 | Read how to set the token as environment variable |
| F240 | Read help on first sprint and optional areas |
| F268 | Read intro on where user settings live |

### Behind a toggle, radio or checkbox that switches a mode or reveals content (7)

| ID | Function |
|---|---|
| F016 | Toggle line-by-line difference |
| F060 | View previous forecasts of open sprints |
| F149 | Switch board view (cards with buttons / drag and drop) |
| F152 | Drag a ticket card to another sprint (earmark) or onto release bar |
| F184 | Show / hide former members |
| F193 | Show / hide former products |
| F288 | Toggle line-by-line difference |

### Only visible with a feature flag in Settings (or a team.yaml flag such as `tracker.write_labels`) (40)

| ID | Function |
|---|---|
| F005 | Navigate between pages |
| F066 | View totals per PO |
| F086 | View suggestion from ticket pre-planning per product |
| F089 | View production access capacity and overload warning |
| F092 | Enter production-access part of the plan (teams without products) |
| F108 | Enter done per product (and production part) |
| F109 | Enter production-access part of done (teams without products) |
| F135 | View production access capacity and overload warning |
| F137 | View totals per PO |
| F142 | Filter by products |
| F154 | Choose sprints to hand over and whether to replace PO values |
| F155 | View handover preview (sprint, product, so far, proposal, notice) |
| F156 | Adopt ticket sums into PO pre-planning |
| F159 | Choose whether to edit project or product rules |
| F172 | Check label changes (planned_for_<sprint>) |
| F173 | View label changes preview |
| F174 | Write labels to Jira |
| F189 | Mark person as authorized for production access |
| F192 | Read help on handing over / adding a product |
| F193 | Show / hide former products |
| F194 | Add a product |
| F195 | Set responsible PO |
| F196 | Set agreed fixed share (%) |
| F197 | Set period from / until (hand over a product) |
| F198 | Confirm deletion of wrongly entered rows |
| F199 | Save products |
| F226 | Read intro and install hint |
| F227 | Choose ticket source (Jira / CSV export) |
| F228 | Set Jira address |
| F229 | Set query (JQL) |
| F230 | Set field names for estimate, remaining work, epic |
| F231 | Set label of refined tickets |
| F232 | Set order of assignment criteria (epic / component / label) |
| F233 | Define additional fields for assignment rules |
| F234 | Test connection (account, field suggestions, ticket count) |
| F235 | View test result |
| F236 | Save connection settings |
| F237 | View token source (environment or keychain) |
| F238 | Store, replace or remove token in keychain |
| F239 | Read how to set the token as environment variable |

### Appears only in a certain data or Git state (e.g. frozen plan, open merge, no server, assumption entered) (82)

| ID | Function |
|---|---|
| F002 | Switch to a recently used data folder |
| F006 | Open plugin-defined pages |
| F007 | View notice about a new version / failed update |
| F008 | Check for updates |
| F012 | Go to "Set up server" |
| F014 | View what is new from others (not taken over yet) |
| F017 | Edit commit message |
| F018 | Toggle use of pending tags |
| F019 | Save and share (commit, merge, push) |
| F020 | Pull from server (no upload) |
| F022 | Commit changes locally |
| F023 | View result of the last sync / commit |
| F024 | Share anyway despite new validation errors |
| F025 | Confirm merging unrelated histories |
| F026 | Abort a hanging sync |
| F027 | Refresh while a sync is running |
| F028 | Abort an open merge |
| F029 | Go back to the branch (detached HEAD) |
| F030 | Enter Git name and email |
| F036 | First start: choose / create / clone data folder |
| F037 | "No team yet" screen with link to New team |
| F040 | View setup checklist (Git, folder, server, sign-in, identity) |
| F041 | Hide setup checklist |
| F050 | View expected absence rate from history and uncertainty remedy |
| F054 | Reset sprints back to "no information" |
| F055 | Go to Products when none exist |
| F058 | Enter team forecast for open sprints (commitment, not finished, additionally done) |
| F059 | Comment on the forecast |
| F060 | View previous forecasts of open sprints |
| F061 | Enter announced absences for the sprint |
| F072 | Release the frozen Forecast PLAN (correct a mistake) |
| F079 | Confirm "Nobody is absent" and continue |
| F080 | Continue without confirmation |
| F084 | Back to the absences |
| F085 | Scratch calculation "Planned so far" |
| F086 | View suggestion from ticket pre-planning per product |
| F089 | View production access capacity and overload warning |
| F091 | Save product values and continue |
| F092 | Enter production-access part of the plan (teams without products) |
| F097 | Re-freeze Forecast PLAN to the current value |
| F103 | View latest forecast of the team and deviation from velocity |
| F108 | Enter done per product (and production part) |
| F109 | Enter production-access part of done (teams without products) |
| F118 | What-if team forecast for open sprints (not saved) |
| F128 | View completion forecast (per sprint, 50 % / 85 %, probability chart, notes) |
| F131 | Go to Products when none exist |
| F135 | View production access capacity and overload warning |
| F137 | View totals per PO |
| F146 | View warnings (no budget, circular dependencies, no range) |
| F156 | Adopt ticket sums into PO pre-planning |
| F159 | Choose whether to edit project or product rules |
| F168 | Read tickets from Jira |
| F172 | Check label changes (planned_for_<sprint>) |
| F173 | View label changes preview |
| F174 | Write labels to Jira |
| F190 | Confirm deletion of wrongly entered rows |
| F198 | Confirm deletion of wrongly entered rows |
| F213 | Set sprint numbering |
| F214 | Set start of first sprint |
| F215 | Set ID of the first sprint |
| F224 | Change sprint IDs (rename sprint, renumber following) |
| F235 | View test result |
| F239 | Read how to set the token as environment variable |
| F245 | Go to People after creating |
| F247 | View Git problems of the folder |
| F252 | Save anyway (offline) / confirm right data repository |
| F253 | Share via merge request (toggle) |
| F254 | Choose kind of server (GitLab, GitHub, Forgejo, other) |
| F255 | Merge automatically when pipeline is green |
| F256 | Switch on credential helper |
| F257 | Store access token with Git credential helper and verify |
| F258 | Delete stored sign-in for the server |
| F259 | Switch branch |
| F260 | Create .gitattributes (line endings) |
| F261 | Switch to / remove a recently used folder |
| F263 | Use folder without Git |
| F264 | Create Git repository in the chosen folder |
| F269 | View merge-open lock warning |
| F277 | Upload local-only tag |
| F279 | Delete tag locally and on server |
| F280 | Enter Git name and email on demand |
| F292 | Restore last saved state of file with conflict markers |

### Happens automatically without a control (5)

| ID | Function |
|---|---|
| F031 | Fetch server state in background |
| F033 | Validate before writing, show warnings, hint to share |
| F034 | Discard stale form input when files changed |
| F035 | Replace team pages by conflict resolution while a merge is open |
| F099 | Write planning minutes on every step save |

### Reachable only because the app redirects there (not in the navigation) (5)

| ID | Function |
|---|---|
| F288 | Toggle line-by-line difference |
| F289 | Choose My change / Other change per entry or file |
| F290 | Apply decisions and share |
| F291 | Abort merge |
| F292 | Restore last saved state of file with conflict markers |

### Reachable only by file edit, environment variable or command line (no UI control)

| Item | Where | Notes |
|---|---|---|
| tracker.write_labels | team.yaml | Enables the label write-back section (IDs F172 to F174); no switch in the UI |
| tracker.budget_basis, tracker.refined_also_if, tracker.sprint_names, tracker.planning_uses and similar | team.yaml `tracker` section | Not on Jira connection; import preview even refers to `tracker.sprint_names` in its text |
| FORESPRINT_AS_OF | environment variable | Reference date; shown in the sidebar footer |
| FORESPRINT_NO_BACKGROUND_FETCH | environment variable | Switches off the automatic fetch of the sidebar |
| FORESPRINT_JIRA_TOKEN | environment variable | Takes precedence over the keychain token |
| FORESPRINT_BROWSER, --port, --no-app | command line of `foresprint web` | Start options, not part of the page |
| Tickets handover, label writing, `tickets` commands | command line | `tickets --handover`, `tickets --write-labels` duplicate UI actions |
| Report generation, checks, import plugins | command line / plugins | CLI equivalents of Forecast report and Check page |
