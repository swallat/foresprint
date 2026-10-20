# SPDX-License-Identifier: EUPL-1.2
"""Pages and sidebar of the web UI. Entry point: web/app.py, pages: web/seiten/*.py.

Reads and writes the same YAML files as the command line. Configuration via environment
variables: SPRINTFORECAST_DATA (data directory), SPRINTFORECAST_AS_OF (reference date).
Texts are translatable via i18n.t; internal column keys of the tables stay German, the
translated labels are displayed.
"""

from __future__ import annotations

import contextlib
import copy
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any

import streamlit as st
import yaml
from streamlit.runtime.scriptrunner import get_script_run_ctx

from sprintforecast import updater
from sprintforecast.analysis import (
    available_count,
    average_focus_factor,
    band,
    buffer_hint,
    completion,
    focus_factor,
    plan_basis,
)
from sprintforecast.calendar import (
    countries,
    day_label,
    holiday_name,
    subdivisions,
    team_weekend,
    team_workdays,
    workweek_label,
)
from sprintforecast.capacity import sprint_capacity
from sprintforecast.commit_message import suggest_message
from sprintforecast.config import SettingsError, config_dir
from sprintforecast.diff import MAX_VALUES, FileChange, cached_file_changes, text_diff
from sprintforecast.engine import (
    MIN_THIN_HISTORY,
    UNSURE_SOURCES,
    CapacitySource,
    gaps_in_window,
)
from sprintforecast.forecast import (
    Forecast,
    TimelineEntry,
    absences_known,
    apply_planning,
    build_forecast,
    find_sprint,
    freeze_plan,
    refreeze_offer,
)
from sprintforecast.formulas import fte_change_note, general, plain_explanation, steps
from sprintforecast.formulas import step as formula_step
from sprintforecast.git import (
    _BIDI_CONTROLS,
    _BLANKED_CATEGORIES,
    NO_WINDOW,
    Change,
    GitError,
    NewBranchError,
    RemoteAddress,
    UnrelatedHistoriesError,
    apply_attributes,
    attributes_offer,
    cached_pending_changes,
    classify,
    clone_repository,
    commit_directory,
    folder_problem,
    has_credentials,
    hint_for,
    init_data_repository,
    invalidate_status,
    md_code,
    md_code_lines,
    md_plain,
    new_branch_error,
    on_invalidate,
    parse_remote_url,
    remote_special_error,
    secret_in_url_error,
)
from sprintforecast.git import repo_root as git_root
from sprintforecast.git import root_problem as git_problem
from sprintforecast.git import title_for as git_title
from sprintforecast.githistory import (
    Entry as HistoryEntry,
)
from sprintforecast.githistory import (
    Lost,
    Tag,
    delete_tag,
    discard,
    discard_preview,
    history,
    list_tags,
    restore_version,
    revert_commit,
    server_reachable,
    set_tag,
    upload_tag,
)
from sprintforecast.gitsync import (
    HOST_FORGEJO,
    HOST_GENERIC,
    HOST_GITHUB,
    HOST_GITLAB,
    LOCK_WARN_SECONDS,
    SHARE_DIRECT,
    SHARE_MERGE_REQUEST,
    Commit,
    ConflictFile,
    RemoteInfo,
    SyncResult,
    SyncState,
    abort_running_sync,
    abort_unfinished,
    auto_merge,
    cached_remote_info,
    check_remote,
    conflict_text_diffs,
    detected_host,
    git_available,
    host_kind,
    host_setting,
    incoming,
    pending_conflicts,
    reattach,
    resolve_conflicts,
    restore_file,
    set_auto_merge,
    set_host,
    set_identity,
    set_remote,
    set_share_mode,
    share_mode,
    start_background_fetch,
    sync,
    sync_running_seconds,
)
from sprintforecast.gitsync import (
    cached_state as cached_sync_state,
)
from sprintforecast.gitsync import fetch as fetch_remote
from sprintforecast.guide import (
    CAPACITY_SOURCES,
    COMMANDS,
    FIELDS,
    GIT_HELP,
    TERMS,
    WORKFLOW,
)
from sprintforecast.i18n import LANGUAGES, language, save_language, set_language, t
from sprintforecast.model import (
    AbsenceState,
    Numbering,
    Planning,
    ProductBasis,
    Sprint,
    Team,
    TrendMode,
    absence_status,
)
from sprintforecast.plugins import WebPage
from sprintforecast.products import (
    MEASURES,
    PRODUCTION_MEASURES,
    Distribution,
    balance,
    by_po,
    distribution,
    measure_label,
    plan_view,
)
from sprintforecast.protocol import (
    KIND_MEASURES,
    PLANNING,
    PREPLANNING,
    REVIEW,
    PlanningSection,
    kind_title,
    latest_planning_sections,
    list_protocols,
    md_item,
    obsolete_with_save,
    planning_distribution_lines,
    render_planning_protocol,
    render_protocol,
    save_with_protocol,
)
from sprintforecast.report import (
    absence_derived_hint,
    absence_derived_note,
    absence_derived_remedy,
    absence_status_label,
    band_note,
    capacity_label,
    capacity_source_note,
    completion_note,
    few_samples_note,
    fmt,
    fmt_capacity,
    pct,
    period,
    render,
    source_label,
    status,
    window_hint,
)
from sprintforecast.settings import (
    BY_KEY,
    FIRST_SPRINT_KEYS,
    SETTINGS,
    Kind,
    Setting,
    applicable,
    changes,
)
from sprintforecast.signin import (
    enable_helper,
    forget_token,
    helper_state,
    host_guide,
    is_https,
    setup_items,
    store_token,
    suggested_helper,
    verify,
)
from sprintforecast.storage import (
    DATA_ENV,
    STICHTAG_ENV,
    ConflictError,
    DataError,
    FileAccessError,
    Repository,
    TeamData,
    clear_team_cache,
    default_data_dir,
    forget_data_dir,
    recent_data_dirs,
    save_data_dir,
    save_sprints_together,
    team_key_problem,
    team_version,
    teams_dir,
    write_text,
)
from sprintforecast.updater import status_line
from sprintforecast.validate import Level, check_all, check_team
from sprintforecast.web.lazy import LazyModule
from sprintforecast.web.logic import (
    CALENDAR_COLUMNS,
    PEOPLE_COLUMNS,
    PRODUCT_COLUMNS,
    TEAM_REGION,
    Assumption,
    CapacityUsage,
    absence_matrix,
    absence_sprints,
    apply_calendar,
    apply_product_values,
    board_steps_done,
    calendar_table,
    calendar_to_save,
    capacity_usage,
    default_forecast_ist,
    edit_absences,
    forget_without_git,
    is_without_git,
    open_velocity_sprints,
    parse_numbers,
    people_from_table,
    people_table,
    product_table,
    product_values_table,
    products_from_table,
    record_prognoses,
    remember_without_git,
    resettable_sprints,
    resolved_path,
    sprints_to_save,
    start_tasks,
    whatif_forecast,
    with_people,
    with_sprints,
)
from sprintforecast.yamlmerge import MISSING

if TYPE_CHECKING:
    import altair as alt
    import pandas as pd
else:  # load on first access (cold start)
    alt = LazyModule("altair")
    pd = LazyModule("pandas")

# Pages: file name under web/seiten → (title, Material icon). Groups for the navigation.
# Titles and groups are German source texts and are translated on display.
PAGES: dict[str, dict[str, tuple[str, str]]] = {
    # Sprint tasks in chronological order: prepare, Planning, close.
    "Tasks": {
        "start": ("Start", ":material/home:"),
        "fehltage": ("Prepare the sprint: absences", ":material/event_busy:"),
        "vorplanung": ("PO pre-planning", ":material/groups:"),
        "planning": ("Planning", ":material/edit_note:"),
        # Deliberately no check mark symbol (task_alt, check …): In the step bar a check mark means
        # "done", so the page icon must not fake it.
        "review": ("Close the sprint (review)", ":material/flag:"),
    },
    "Reports": {
        "forecast": ("Forecast", ":material/trending_up:"),
        "analyse": ("Analysis", ":material/insights:"),
        "produkte": ("Product distribution", ":material/pie_chart:"),
        "tickets": ("Tickets", ":material/view_kanban:"),
    },
    "Manage team": {
        "sprints": ("Sprint calendar", ":material/calendar_month:"),
        "personen": ("People", ":material/group:"),
        "produktliste": ("Products", ":material/category:"),
        "einstellungen": ("Settings", ":material/tune:"),
        "neues_team": ("New team", ":material/group_add:"),
    },
    "Data & help": {
        "datenordner": ("Data folder", ":material/folder_open:"),
        "verlauf": ("Changes and history", ":material/history:"),
        "pruefung": ("Check", ":material/fact_check:"),
        "hilfe": ("Help", ":material/help:"),
    },
}
PAGE_INFO = {key: info for group in PAGES.values() for key, info in group.items()}
# Pages that only appear if the team uses the feature area (Team → Settings).
PAGE_FEATURES = {
    "vorplanung": "products",
    "produkte": "products",
    "produktliste": "products",
    "tickets": "tickets",
}


def enabled_pages(repo: Repository) -> set[str]:
    """Pages for the selected team: pages of disabled feature areas are dropped."""
    team = st.session_state.get("selected_team")
    try:
        features = repo.load_cached(team).team.features if team and repo.exists(team) else None
    except DataError:
        features = None
    return {
        key
        for key in PAGE_INFO
        if features is None or getattr(features, PAGE_FEATURES.get(key, ""), True)
    }


def page_path(key: str) -> str:
    return f"seiten/{key}.py"


def page_link(key: str, label: str | None = None) -> None:
    if key not in st.session_state.get("enabled-pages", PAGE_INFO):
        return  # page belongs to a disabled feature area
    title, icon = PAGE_INFO[key]
    st.page_link(page_path(key), label=label or t(title), icon=icon)


def today() -> date:
    raw = os.environ.get(STICHTAG_ENV)
    return date.fromisoformat(raw) if raw else date.today()


def stichtag_problem() -> str | None:
    """Message if the environment has no valid reference date (otherwise ``today`` fails)."""
    raw = os.environ.get(STICHTAG_ENV)
    if raw:
        try:
            date.fromisoformat(raw)
        except ValueError:
            return t(
                (
                    "The environment variable `{name}` contains “{value}” – a date in the "
                    "format YYYY-MM-DD is expected. Please correct or remove the variable and "
                    "restart the web interface."
                ),
                name=STICHTAG_ENV,
                value=raw,
            )
    return None


# The data folder belongs to the browser session (not the process): if one session switches the
# folder, other open windows keep saving to their own.
DATA_DIR_KEY = "active-data-dir"


def data_dir() -> Path:
    """Data folder of this session; on first call the process default (environment,
    remembered folder)."""
    raw = st.session_state.get(DATA_DIR_KEY)
    if raw is None:
        raw = st.session_state[DATA_DIR_KEY] = str(default_data_dir())
    return Path(raw)


def repository() -> Repository:
    return Repository(data_dir())


def apply_language() -> None:
    """Set the language for this run (from the setting or the environment)."""
    set_language(None)
    set_language(language())


def _settings_problem(error: SettingsError, consequence: str) -> str:
    """Message about settings that could not be saved: what happened, what was skipped and what
    to do."""
    return t(
        (
            "{error}  \n{consequence} Please check that the folder `{folder}` is writable "
            "(permissions, free disk space, for network drives: connected) and try again."
        ),
        error=error,
        consequence=consequence,
        folder=config_dir(),
    )


def _language_changed() -> None:
    code = st.session_state["language"]
    try:
        save_language(code)
    except SettingsError as e:
        st.session_state["language"] = language()  # the selection shows the valid language again
        st.session_state.setdefault("flash", []).append(
            ("error", _settings_problem(e, t("The language was not changed.")))
        )
        return
    set_language(code)


def help_text(key: str) -> str:
    f = FIELDS[key]
    return f"{t(f.what)}\n\n{t('Source')}: {t(f.source)}\n\n{t('Example')}: {t(f.example)}"


# Introduction of a page: a lead sentence stays visible (two lines at most), everything else is
# collapsible. The width of the lead sentence is limited to keep it readable.
_INTRO_CSS = "<style>div.st-key-page-intro { max-width: 72ch; }</style>"


def page_intro(lead: str, details: str | None = None, title: str | None = None) -> None:
    """Lead sentence of the page; ``details`` appear in an expander "More about this"."""
    st.html(_INTRO_CSS)
    with st.container(key="page-intro"):
        st.markdown(lead)
    if details:
        with st.expander(title or t("More about this"), icon=":material/info:"):
            st.markdown(details)


def field_help(key: str) -> str:
    """Help text of a field from guide.py as three labeled lines (for the expander)."""
    f = FIELDS[key]
    return (
        f"**{t('What')}** · {t(f.what)}  \n"
        f"**{t('Source')}** · {t(f.source)}  \n"
        f"**{t('Example')}** · {t(f.example)}"
    )


def _steps_frame(fc: Forecast, entry: TimelineEntry) -> pd.DataFrame:
    return pd.DataFrame([{t("Metric"): s.name, t("Formula"): s.formula} for s in steps(fc, entry)])


# --- Saving with validation ----------------------------------------------------------


def _next_step() -> str:
    """What the sidebar offers after saving: ``"share"`` ("Save and share", the data folder has
    a server), ``"commit"`` ("Commit changes") or ``""`` (nothing: no Git, a problem or a state
    that has to be resolved first). Uses only the cache the sidebar fills anyway; query before
    writing, because writing empties it."""
    root = data_dir()
    if not git_available() or git_root(root) is None:
        return ""
    try:
        state = cached_sync_state(root)
    except GitError:
        return ""
    if state.unfinished or state.conflicts or state.detached:
        return ""
    return "share" if state.remote is not None else "commit"


def _has_open_changes() -> bool:
    """Is there anything to commit after saving? Same query (and same cache) as in the
    sidebar. On a Git error the answer is "yes"."""
    try:
        return bool(cached_pending_changes(data_dir()))
    except GitError:
        return True


def _saved_text(names: str, step: str) -> str:
    if step == "share":
        return t(
            (
                "Saved: {names}. Use **Save and share** in the sidebar to save to Git and "
                "share with the team (local only: **Commit changes**)."
            ),
            names=names,
        )
    if step == "commit":
        return t(
            "Saved: {names}. Commit to Git with **Commit changes** in the sidebar.",
            names=names,
        )
    return t("Saved: {names}.", names=names)


def save(
    data_after: TeamData,
    filenames: list[str],
    write: Callable[[], list[Path]],
    tag: str | None = None,
    block_on_all_errors: bool = False,
    flash: bool = False,
) -> bool:
    """Validate the new state and write it on success. Committing happens via the sidebar.

    With ``flash`` notices appear only in the next run (for ``st.rerun()``)."""

    def notify(kind: str, text: str) -> None:
        if flash:
            st.session_state.setdefault("flash", []).append((kind, text))
        else:
            getattr(st, kind)(text)

    issues = check_team(data_after, today())
    relevant = [i for i in issues if any(n in i.where for n in filenames)]
    blocking = issues if block_on_all_errors else relevant
    errors = [i for i in blocking if i.level is Level.ERROR]
    if errors:
        for i in errors:
            st.error(f"{i.where}: {i.message}")
        st.error(t("Not saved – please fix the errors."))
        return False
    step = _next_step()
    try:
        paths = write()
    except FileAccessError as e:
        st.error(str(e))
        return False
    if step and not _has_open_changes():  # content was already saved like this: nothing to do
        step = ""
    for i in relevant:
        if i.level is Level.WARNING:
            notify("warning", f"{i.where}: {i.message}")
    if tag:
        tags = st.session_state.setdefault("pending_tags", [])
        if tag not in tags:
            tags.append(tag)
    notify("success", _saved_text(", ".join(p.name for p in paths), step))
    return True


def show_flash() -> None:
    for kind, text in st.session_state.pop("flash", []):
        getattr(st, kind)(text)


def sprint_caption(data: TeamData, s: Sprint) -> str:
    """Period, working days and holidays of a sprint."""
    days = team_workdays(data.team, s.start, s.end)
    region, country = data.team.capacity.region, data.team.capacity.country
    holiday_names = [
        f"{d:%d.%m.} {name}" for d in days if (name := holiday_name(d, region, country))
    ]
    last = f"{days[-1]:%d.%m.%Y}" if days else f"{s.end:%d.%m.%Y}"
    text = t(
        (
            "**{id}**: {start} – {last} (last working day; the next sprint starts on {next}), "
            "{days} working days ({week})"
        ),
        id=s.id,
        start=f"{s.start:%d.%m.}",
        last=last,
        next=f"{s.end:%d.%m.}",
        days=len(days),
        week=workweek_label(data.team),
    )
    if holiday_names:
        text += t(" · including holidays: {holidays}", holidays=", ".join(holiday_names))
    if not data.sprint(s.id):
        text += t(" · no sprint file yet")
    return text


def sprints_summary(data: TeamData, sprints: list[Sprint], today: date) -> str:
    """One line for several sprints: working days (shared or per sprint), sprints with
    holidays, completed sprints and the number of sprints without a sprint file."""
    region, country = data.team.capacity.region, data.team.capacity.country
    workdays = {s.id: team_workdays(data.team, s.start, s.end) for s in sprints}
    counts = {len(days) for days in workdays.values()}
    week = workweek_label(data.team)
    if len(counts) == 1:
        parts = [t("all sprints {days} working days ({week})", days=counts.pop(), week=week)]
    else:
        parts = [
            t("{days} working days ({week}) in sprint {id}", days=len(days), week=week, id=sid)
            for sid, days in workdays.items()
        ]
    for sid, days in workdays.items():
        if holiday_names := [f"{d:%d.%m.}" for d in days if holiday_name(d, region, country)]:
            parts.append(t("{id}: public holidays {dates}", id=sid, dates=", ".join(holiday_names)))
    if done := [s.id for s in sprints if s.end <= today]:
        parts.append(t("completed: {ids}", ids=", ".join(done)))
    if missing := sum(1 for s in sprints if not data.sprint(s.id)):
        parts.append(t("{count} sprint(s) without a sprint file yet", count=missing))
    return " · ".join(parts)


# --- Pages ----------------------------------------------------------------------------


def _signed(value: float) -> str:
    return ("+" if value > 0 else "") + fmt(value)


def _whatif_inputs(fc: Forecast, unit: str, prefix: str = "whatif") -> dict[str, Assumption]:
    """Team forecast for open sprints: commitment − expected not finished + additionally done
    = expected velocity. Nothing is saved."""
    assumed: dict[str, Assumption] = {}
    for sprint in open_velocity_sprints(fc):
        st.markdown(f"**{t('Sprint {id}', id=sprint.id)}**")
        default_commitment = default_forecast_ist(fc, sprint)
        # Align at the bottom: labels that wrap would otherwise push the fields down.
        commitment_col, open_col, extra_col, result_col = st.columns(4, vertical_alignment="bottom")
        commitment = commitment_col.number_input(
            t("Commitment ({unit})", unit=unit),
            min_value=0.0,
            value=default_commitment,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-ist",
            help=t(
                "Amount planned for the sprint. Prefilled with the recorded commitment, "
                "otherwise with that of the previous sprint."
            ),
        )
        not_done = open_col.number_input(
            t("Expected not finished ({unit})", unit=unit),
            min_value=0.0,
            value=None,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-open",
            help=t("Amount of tickets the team expects not to finish."),
        )
        extra = extra_col.number_input(
            t("Additionally done ({unit})", unit=unit),
            min_value=0.0,
            value=None,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-extra",
            help=t("Amount expected to be done in addition to the commitment."),
        )
        changed = not_done is not None or extra is not None or commitment != default_commitment
        if commitment is None or not changed:
            result_col.metric(t("Expected done"), "–")
            continue
        assumed[sprint.id] = Assumption(commitment, not_done, extra)
        result_col.metric(t("Expected done"), f"{fmt(assumed[sprint.id].expected, 2)} {unit}")
    return assumed


def _whatif_title() -> str:
    return t("What if: team forecast for open sprints")


def _whatif_caption(note: str) -> None:
    """Shared intro text of both what-if panels; ``note`` says what happens to the
    assumption."""
    st.caption(
        t(
            "Enter the team's forecast for a sprint that is not yet finished: commitment, "
            "what is expected not to get done and what is done in addition. The Forecast "
            "PLAN of the next sprints is recalculated with it."
        )
        + " "
        + note
    )


@st.fragment
def _whatif_panel(fc: Forecast, upcoming: list[TimelineEntry], unit: str) -> None:
    """What if: expected done amount of open sprints → Forecast PLAN of the next ones."""
    sprints = open_velocity_sprints(fc)
    if not sprints:
        return
    with st.expander(_whatif_title(), icon=":material/science:"):
        _whatif_caption(t("Nothing is saved."))
        assumed = _whatif_inputs(fc, unit)
        if not assumed:
            return
        scenario = whatif_forecast(fc, assumed)
        plan_now, plan_new = (
            f"Forecast PLAN ({unit})",
            t("Forecast PLAN with assumption ({unit})", unit=unit),
        )
        diff = t("Difference")
        rows = []
        for e in upcoming:
            other = scenario.entry(e.sprint.id)
            now, new = e.result.plan, other.result.plan if other else None
            rows.append(
                {
                    "Sprint": e.sprint.id,
                    plan_now: fmt(now),
                    plan_new: fmt(new),
                    diff: "–" if now is None or new is None else _signed(new - now),
                    t("norm. velocity trend"): fmt(other.result.normalized_velocity.trend, 2)
                    if other
                    else "–",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True)


# The icons come from PAGES: a task has the same icon everywhere (start page, sidebar, step
# bar), and no page icon fakes a check mark ("done").
START_TASKS = {
    "prepare": ("Prepare sprint", PAGE_INFO["fehltage"][1]),
    "planning": ("Planning", PAGE_INFO["planning"][1]),
    "review": ("Close sprint", PAGE_INFO["review"][1]),
}


def _start_clicked(page: str, sprint_id: str | None) -> None:
    if sprint_id is not None:
        st.session_state[BOARD_SPRINT] = sprint_id  # the target page opens this sprint
    st.session_state["start-goto"] = page


def page_start(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Entry via the three tasks; each leads to the next sensible page."""
    st.header(t("What would you like to do?"))
    if (goto := st.session_state.pop("start-goto", None)) is not None:
        st.switch_page(page_path(goto))
    _setup_checklist(repo)
    tasks = start_tasks(
        fc, "vorplanung" in st.session_state.get("enabled-pages", PAGE_INFO) and bool(data.products)
    )
    for col, task in zip(st.columns(len(tasks)), tasks, strict=True):
        title, icon = START_TASKS[task.key]
        with col, st.container(border=True):
            st.subheader(f"{'✅' if task.done else '⬜'} {t(title)}")
            st.write(task.hint)
            st.button(
                t("Open"),
                key=f"start-{task.key}",
                icon=icon,
                type="secondary" if task.done else "primary",
                on_click=_start_clicked,
                args=(task.page, task.sprint_id),
            )
    st.caption(
        t(
            "Then: look at the **Forecast**, evaluate with **Analysis** and **Product "
            "distribution**, or maintain the sprint calendar, people and products under "
            "**Manage team**."
        )
    )
    page_link("forecast")


def _setup_checklist(repo: Repository) -> None:
    """Einrichtungs-Checkliste (Git, Datenordner, Server, Anmeldung, Identität): nur lesende
    Prüfungen ohne Netzwerk, führt nichts aus und verschwindet, wenn alles erledigt ist."""
    if st.session_state.get("setup-hidden"):
        return
    try:
        items = setup_items(repo.root)
    except GitError:
        return
    if all(item.ok for item in items):
        return
    with st.container(border=True):
        st.markdown(f"**{t('Setup')}**")
        for item in items:
            line = f"{'✅' if item.ok else '⬜'} {item.detail}"
            if item.ok or not item.page:
                st.write(line)
                continue
            left, right = st.columns([4, 1], vertical_alignment="center")
            left.write(line)
            with right:
                page_link(item.page, t("Open"))
        st.button(t("Hide"), key="setup-hide", on_click=_hide_setup)


def _hide_setup() -> None:
    st.session_state["setup-hidden"] = True


def page_forecast(repo: Repository, data: TeamData, fc: Forecast) -> None:
    team = data.team
    unit = team.unit.value
    st.header(f"Forecast {team.name}")
    _next_dates(fc)
    upcoming = fc.upcoming()
    cols = st.columns(min(len(upcoming), 4) or 1)
    for col, e in zip(cols, upcoming, strict=False):
        b = band(fc, e)
        col.metric(
            f"{e.sprint.id} ({status(fc, e).replace('*', '')})",
            f"{fmt(e.result.plan)} {unit}",
            # Keep it short: Streamlit truncates the line under the number with "…", so how many
            # sprints the range is based on is stated in the caption below.
            delta=(
                t("Range {low}–{high}", low=fmt(b.low), high=fmt(b.high))
                if b
                else t("Range not computable")
            ),
            delta_color="off",
            help=_formula_help(fc, e, "plan")
            + "\n\n"
            + t(
                "Capacity {capacity} PT · plannable {roadmap} · small items {small}",
                capacity=capacity_label(e),
                roadmap=fmt(e.result.roadmap, 2),
                small=fmt(e.result.small_stuff, 2),
            )
            + "\n\n"
            + t("Absences: {state}", state=absence_status_label(e.sprint))
            + (
                "\n\n" + t("Forecast at planning: {plan} {unit}", plan=fmt(view.frozen), unit=unit)
                if (view := plan_view(e)).frozen is not None
                else ""
            ),
        )
        col.caption(
            t(
                "Capacity {capacity} PT · absences {state}",
                capacity=capacity_label(e),
                state=absence_status_label(e.sprint),
            )
        )
        if b:
            col.caption(t("Range from the last {samples} sprints", samples=b.samples))
    _forecast_notes(fc, upcoming)

    capacity_col, trend_col, plan_col = (
        t("Capacity (PT)"),
        t("norm. velocity trend"),
        t("Current forecast ({unit})", unit=unit),
    )
    frozen_col, diff_col = t("Forecast at planning ({unit})", unit=unit), t("Difference")
    show_frozen = any(e.sprint.forecast_plan is not None for e in upcoming)
    plannable_col = t("Plannable")
    small_col = t("Small items")
    rows = []
    for e in upcoming:
        view = plan_view(e)
        row = {
            "Sprint": e.sprint.id,
            t("Period"): period(e),
            "Status": status(fc, e).replace("*", ""),
            t("Absences"): absence_status_label(e.sprint),
            capacity_col: capacity_label(e),
            trend_col: fmt(e.result.normalized_velocity.trend, 2),
            plan_col: fmt(e.result.plan),
        }
        if show_frozen:
            row[frozen_col] = fmt(view.frozen)
            row[diff_col] = "–" if view.difference is None else _signed(view.difference)
        rows.append(
            row
            | {
                plannable_col: fmt(e.result.roadmap, 2),
                small_col: fmt(e.result.small_stuff, 2),
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            capacity_col: st.column_config.TextColumn(help=general("capacity")),
            trend_col: st.column_config.TextColumn(help=general("trend")),
            plan_col: st.column_config.TextColumn(help=general("plan")),
            plannable_col: st.column_config.TextColumn(help=general("roadmap")),
            small_col: st.column_config.TextColumn(help=general("small_stuff")),
        },
    )
    _whatif_panel(fc, upcoming, unit)
    for source in UNSURE_SOURCES:
        unsure = [e.sprint.id for e in upcoming if e.result.plan_capacity_source is source]
        if unsure:
            st.warning(
                t(
                    (
                        "No absences recorded yet for {sprints} – the capacity is only "
                        "estimated ({source}). Enter them on the **Prepare the sprint: "
                        "absences** page."
                    ),
                    sprints=", ".join(unsure),
                    source=source_label(source),
                )
            )
    _quote_note(fc, upcoming)
    current = fc.current
    if current and current.result.planning_total is not None:
        st.info(
            t(
                "Planning {id}: total {total} {unit}, delta to the Forecast PLAN {delta} {unit}",
                id=current.sprint.id,
                total=fmt(current.result.planning_total, 2),
                delta=fmt(current.result.planning_delta, 2),
                unit=unit,
            )
        )

    st.subheader(t("History"))
    history = fc.history(10)
    nvel, avg = t("norm. velocity"), t("Ø norm. velocity")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Sprint": e.sprint.id,
                    capacity_col: fmt_capacity(e.result.capacity.value, e.capacity_digits),
                    t("Commitment"): fmt(e.result.forecast_ist.value, 2),
                    "Velocity": fmt(e.result.velocity.value, 2),
                    nvel: fmt(e.result.normalized_velocity.value, 2),
                    avg: fmt(e.result.normalized_velocity.average, 2),
                    "Fulfillment": pct(e.result.fulfillment.value),
                    "Scope creep": pct(e.result.scope_creep.value),
                }
                for e in history
            ]
        ),
        hide_index=True,
        column_config={
            nvel: st.column_config.TextColumn(help=general("normalized_velocity")),
            avg: st.column_config.TextColumn(help=general("average")),
            "Fulfillment": st.column_config.TextColumn(help=general("fulfillment")),
            "Scope creep": st.column_config.TextColumn(help=general("scope_creep")),
        },
    )
    _formula_expander(fc)
    chart = _chart(fc, history + [e for e in upcoming if e not in history], unit)
    if chart is None:
        st.info(
            t(
                "No values for a chart yet – record planning and review after the first "
                "sprints (or import the history with an import plugin)."
            )
        )
    else:
        st.altair_chart(chart, width="stretch")

    if st.button(t("Write report FORECAST.md")):
        path = repo.team_dir(team.key) / "FORECAST.md"
        write_text(path, render(fc))
        st.success(t("Written: {path}", path=path))
    _excel_download(fc, team.key)


def _excel_download(fc: Forecast, team_key: str) -> None:
    """Excel list to download (for everyone who keeps working with an Excel list)."""
    from sprintforecast.excel import ExcelUnavailable, build_workbook

    if not st.button(t("Create Excel list"), icon=":material/table:"):
        return
    try:
        content = build_workbook(fc)
    except ExcelUnavailable as e:
        st.warning(str(e))
        return
    st.download_button(
        t("Download Excel list"),
        content,
        file_name=f"{team_key}-forecast.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        help=t(
            "Contains sprint values as inputs and the calculation as Excel formulas (n. "
            "velocity, trend, Forecast PLAN, plannable), trend charts and the split by "
            "production access and per product. Not saved in the data folder."
        ),
    )


def _forecast_notes(fc: Forecast, upcoming: list[TimelineEntry]) -> None:
    """Notes on reliability right at the tiles: little data, thin history and a trend mode that
    extrapolates noise."""
    # Whether a forecast exists depends on all available values, not on the sample capped to the
    # window (that belongs to the calculation: range, "Little data").
    if available_count(fc) < MIN_THIN_HISTORY:
        st.info(
            t(
                (
                    "No forecast yet: so far {samples} sprint(s) with velocity. From {min} "
                    "sprints on a first forecast appears (with the note “thin history”); "
                    "record the velocity in the review or import the history with an import "
                    "plugin."
                ),
                samples=available_count(fc),
                min=MIN_THIN_HISTORY,
            )
        )
    if note := few_samples_note(fc):
        st.warning(note)
    # Same sprints as the calculation (completed and current), without future sprints.
    series = [x.result.normalized_velocity.value for x in plan_basis(fc)]
    if gaps := gaps_in_window(series, fc.data.team.forecast.window):
        st.info(
            t(
                (
                    "Gaps: {count} sprint(s) without velocity in the window of the average are "
                    "skipped; the window reaches back accordingly."
                ),
                count=gaps,
            )
        )
    if any(e.result.trend_fallback for e in upcoming):
        st.info(
            t(
                (
                    "Thin history: the history is not enough for trend mode {mode}, “constant” "
                    "(last average) applies."
                ),
                mode=fc.data.team.forecast.trend_mode.value,
            )
        )
    if fc.data.team.forecast.trend_mode is not TrendMode.FLAT:
        st.warning(
            t(
                (
                    "Trend mode {mode}: extrapolates fluctuations and can rise or fall "
                    "(caution with long horizons). “Constant” is robust – set under **Manage "
                    "team → Settings**."
                ),
                mode=fc.data.team.forecast.trend_mode.value,
            )
        )


def _quote_note(fc: Forecast, entries: list[TimelineEntry]) -> None:
    """Compact note if the capacity of these sprints is estimated from an uncertain absence rate
    (sprints that only count as "nobody was absent" by inference). Details on the absences page
    and in the calculation path."""
    if any(e.result.plan_capacity_source is CapacitySource.ESTIMATED for e in entries) and (
        note := absence_derived_hint(fc.absences)
    ):
        st.caption(f":material/info: {note}")


def _formula_help(fc: Forecast, e: TimelineEntry | None, key: str) -> str:
    """Tooltip text: symbolic formula of a metric."""
    if e is None or (s := formula_step(fc, e, key, code=True)) is None:
        return ""
    return s.formula


@st.fragment
def _formula_expander(fc: Forecast) -> None:
    """Collapsible calculation path with all metrics of a sprint."""
    if not sprint_options(fc, None):
        return
    with st.expander(t("Calculation: formulas"), icon=":material/function:"):
        sprint = sprint_select(fc.data, fc, "formula-sprint", "current", None)
        entry = fc.entry(sprint.id) if sprint else None
        if entry is not None:
            _rechenweg(fc, entry)


def _rechenweg(fc: Forecast, entry: TimelineEntry) -> None:
    """First an explanation in plain language, with the values used and their sources below
    on request."""
    st.markdown(plain_explanation(fc, entry))
    with st.popover(t("Values used and sources"), icon=":material/table:"):
        st.dataframe(_steps_frame(fc, entry), hide_index=True, width="stretch")


def _next_dates(fc: Forecast) -> None:
    """The next sprint events with what is to be done there."""
    current, planning = fc.current, fc.default_entry("planning")
    items = []
    if current is not None:
        days = team_workdays(fc.data.team, current.sprint.start, current.sprint.end)
        review_day = days[-1] if days else current.sprint.end
        done = current.sprint.velocity is not None
        items.append(
            (
                f"Review {current.sprint.id}",
                day_label(review_day),
                t("recorded ✓") if done else t("Record velocity and done per product"),
                "review",
            )
        )
    if planning is not None:
        missing = fc.data.sprint(planning.sprint.id) is None
        items.append(
            (
                f"Planning {planning.sprint.id}",
                day_label(planning.sprint.start),
                t("Absences → Forecast PLAN → commitment")
                + (t(" (absences not recorded yet)") if missing else ""),
                "planning",
            )
        )
    if not items:
        return
    with st.container(border=True):
        st.caption(t("Upcoming events"))
        for title, when, todo, page in items:
            left, middle, right = st.columns([2, 4, 2], vertical_alignment="center")
            left.markdown(f"**{title}**  \n{when}")
            middle.markdown(todo)
            with right:
                page_link(page, t("Open"))


def _chart(fc: Forecast, entries: list[TimelineEntry], unit: str) -> alt.Chart | None:
    """Line chart; None as long as there are no values (Altair fails on empty data)."""
    records = []
    metric, forecast_col = t("Metric"), t("Projection")
    for e in entries:
        r = e.result
        future = e.sprint.end > fc.today
        values = {
            t("Commitment / PLAN"): r.plan if future else r.forecast_ist.value,
            "Velocity": r.velocity.trend if future else r.velocity.value,
            t("norm. velocity"): r.normalized_velocity.trend
            if future
            else r.normalized_velocity.value,
        }
        for name, value in values.items():
            if value is not None:
                records.append(
                    {"Sprint": e.sprint.id, metric: name, unit: value, forecast_col: future}
                )
    if not records:
        return None
    order = [e.sprint.id for e in entries]
    return (
        alt.Chart(pd.DataFrame(records))
        .mark_line(point=True)
        .encode(
            x=alt.X("Sprint:N", sort=order),
            y=alt.Y(f"{unit}:Q"),
            color=f"{metric}:N",
            strokeDash=alt.StrokeDash(f"{forecast_col}:N", legend=None),
            tooltip=[
                alt.Tooltip("Sprint:N"),
                alt.Tooltip(f"{metric}:N"),
                alt.Tooltip(f"{unit}:Q", format=".2f"),
            ],
        )
    )


def page_absences(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Planned absences"))
    # Selected sprint and step bar as on the boards; the table below still shows several
    # sprints.
    if (board_sprint := sprint_select(data, fc, "absences-sprint")) is not None:
        _board_nav(data, board_sprint, "fehltage")
    page_intro(
        t(
            "Enter absences per person and sprint: vacation, time off, training, other "
            "projects. Half days as 0.5. Do not enter public holidays; the tool knows them "
            "from the country and state."
        ),
        field_help("absences")
        + "  \n"
        + t(
            "Absences in the person's working days (0.5 = half a day), not in person days: "
            "part-timers enter the days on which they would otherwise work; the FTE scales "
            "the capacity down by itself."
        ),
        t("More about this: what counts, where the numbers come from"),
    )
    if not data.people:
        st.warning(t("No people recorded yet – add them on the **People** page first."))
        return
    left, right = st.columns(2)
    count = left.number_input(
        t("Number of sprints"), min_value=1, max_value=26, value=data.team.forecast.horizon + 1
    )
    past = right.number_input(
        t("Past sprints"),
        min_value=0,
        max_value=26,
        value=0,
        key="absences-past",
        help=t(
            "Also shows the last finished sprints so absences can be added retroactively. "
            "They feed into the expected absences (setting); a capacity frozen at the "
            "review does not change."
        ),
    )
    sprints = absence_sprints(data, fc, int(count), int(past))
    if not sprints:
        st.info(t("No sprints found."))
        return
    # Period, working days and holidays per sprint are a tooltip on the column header; what stays
    # visible is one line with what all sprints have in common and what differs.
    st.caption(sprints_summary(data, sprints, fc.today))
    page_link("sprints", t("Periods in the sprint calendar"))
    rows = absence_matrix(data.people, sprints)
    column_config: dict[str, Any] = {
        "id": None,
        "Person": st.column_config.TextColumn(t("Person"), disabled=True),
    }
    for s in sprints:
        caption = sprint_caption(data, s)
        column_config[s.id] = st.column_config.NumberColumn(
            s.id,
            min_value=0.0,
            max_value=float(len(team_workdays(data.team, s.start, s.end))),
            step=0.5,
            help=caption + (f" · {t('finished')}" if s.end <= fc.today else ""),
        )
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config=column_config,
        hide_index=True,
        key=f"absences-{data.team.key}-{sprints[0].id}-{len(sprints)}",
        placeholder="",  # empty = not in the team (see note below), not "None"
    )
    st.caption(t("Empty cells: the person is not in the team during this sprint."))
    approx = {
        p.person.name
        for s in sprints
        for p in sprint_capacity(data.team, data.people, s).people
        if p.fte_changes
    }
    if approx:
        st.caption(fte_change_note(sorted(approx)))
    live = edit_absences(data.people, sprints, edited.to_dict("records"))
    confirmed = _absence_states(live, sprints)
    edited_sprints = edit_absences(
        data.people, sprints, edited.to_dict("records"), confirmed=confirmed
    )
    history = fc.absences
    if data.team.capacity.absence_history and history is not None:
        st.caption(
            t(
                (
                    "For sprints with unknown absences, absences are expected from the last "
                    "sprints with confirmed absences: Ø {rate} of the capacity (sprints "
                    "{sprints})."
                ),
                rate=pct(history.rate),
                sprints=", ".join(history.sprints),
            )
            if history.rate is not None
            else t(
                "No sprint with confirmed absences in the history yet – until then unknown "
                "absences are calculated without deduction (calendar and people list)."
            )
        )
        if short := absence_derived_note(history):
            st.info(short, icon=":material/info:")
            with st.expander(t("What to do about an uncertain rate?")):
                st.markdown(absence_derived_remedy(data.team.capacity.absence_history))
    to_save = sprints_to_save(data, sprints, edited_sprints)
    preview = with_sprints(data, to_save)
    fc_preview = build_forecast(preview, fc.today)
    if new := [s.id for s in to_save if data.sprint(s.id) is None]:
        st.caption(t("Saving creates the sprint files {sprints}.", sprints=", ".join(new)))
    st.subheader(t("Capacity and forecast") + (t(" (preview, not saved yet)") if to_save else ""))
    if next_sprint := next((s for s in edited_sprints if s.start > fc.today), None):
        next_entry = fc_preview.entry(next_sprint.id)
        if next_entry is not None and next_entry.result.plan is not None:
            st.markdown(
                t(
                    "**{plan} {unit} fit into the next sprint {id}** (capacity {capacity} PT)",
                    id=next_sprint.id,
                    plan=fmt(next_entry.result.plan),
                    unit=data.team.unit.value,
                    capacity=fmt_capacity(
                        next_entry.result.plan_capacity, next_entry.capacity_digits
                    ),
                )
            )
            if note := band_note(fc_preview, next_entry):
                st.caption(note)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Sprint": s.id,
                    t("Absences"): absence_status_label(s),
                    t("Capacity (PT)"): capacity_label(e) if e else "–",
                    f"Forecast PLAN ({data.team.unit.value})": fmt(e.result.plan) if e else "–",
                }
                for s in edited_sprints
                for e in [fc_preview.entry(s.id)]
            ]
        ),
        hide_index=True,
    )
    # Reload after saving so the step bar at the top shows the saved state (check mark); the
    # message then appears in the next run (flash).
    if st.button(t("Save absences"), type="primary", disabled=not to_save) and save(
        preview,
        [f"{s.id}.yaml" for s in to_save],
        lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        flash=True,
    ):
        st.rerun()
    _reset_absences(repo, data, fc.today)


def _absence_states(live: list[Sprint], sprints: list[Sprint]) -> set[str]:
    """Show the absence status per sprint; "nobody is absent" can be confirmed explicitly.
    Returns the sprints for which that is confirmed (without entries)."""
    st.subheader(t("Absence status"))
    st.caption(
        t(
            "Sprints with entered absences are confirmed. **Nobody is absent** explicitly "
            "confirms that there are no absences; without confirmation the absences count "
            "as unknown and are estimated."
        )
    )
    frame = pd.DataFrame(
        [
            {
                "Sprint": s.id,
                t("Current status"): absence_status_label(s),
                t("Nobody is absent"): (
                    absence_status(orig) is AbsenceState.CONFIRMED and not orig.absences
                ),
            }
            for s, orig in zip(live, sprints, strict=True)
        ]
    )
    edited = st.data_editor(
        frame,
        column_config={
            "Sprint": st.column_config.TextColumn(disabled=True),
            t("Current status"): st.column_config.TextColumn(disabled=True),
            t("Nobody is absent"): st.column_config.CheckboxColumn(
                help=t("Explicitly confirms that nobody is absent in this sprint.")
            ),
        },
        hide_index=True,
        key=f"absence-states-{sprints[0].id}-{len(sprints)}",
    )
    return {str(r["Sprint"]) for r in edited.to_dict("records") if r[t("Nobody is absent")]}


def _reset_absences(repo: Repository, data: TeamData, today: date) -> None:
    """Reset future sprints without absence information back to "unknown"."""
    resettable = resettable_sprints(data, today)
    if not resettable:
        return
    st.subheader(t("Reset absences"))
    st.caption(
        t(
            "Absences were confirmed for these sprints, nothing else is recorded. "
            "Resetting deletes the sprint file: no information is then available, the "
            "absences are estimated from the history again (without history, no "
            "deduction); the capacity still comes from the calendar and people."
        )
    )
    chosen = st.multiselect(
        t("Sprints"),
        [s.id for s in resettable],
        default=[s.id for s in resettable],
        key=f"reset-absences-{data.team.key}",
    )
    if st.button(t('Reset to "no information"'), disabled=not chosen):
        for sprint_id in chosen:
            repo.delete_sprint(data.team.key, sprint_id)
        st.session_state["flash"] = [("success", t("Reset: {sprints}", sprints=", ".join(chosen)))]
        st.rerun()


def page_calendar(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Sprint calendar"))
    page_intro(
        t(
            (
                "Sprints follow each other automatically, {days} calendar days each. Here you "
                "can create them in advance and lengthen or shorten single ones."
            ),
            days=data.team.sprint.length_days,
        ),
        t(
            (
                "**Sequence:** each sprint starts the day after the last day of the previous "
                "one and lasts {days} calendar days (setting *sprint length*).  \n**Differing "
                "sprint:** e.g. three weeks over Christmas: change its **last day**; the "
                "following sprints shift accordingly.  \n**Working days:** according to the "
                "team's workweek ({week}) from the start up to and including the last day; "
                "holidays are only deducted in the capacity.  \n**Sprint file:** created as "
                "soon as something is saved for the sprint, or here with **Create sprints**."
            ),
            days=data.team.sprint.length_days,
            week=workweek_label(data.team),
        ),
        t("Differing sprints, working days, sprint files"),
    )
    count = st.number_input(t("Number of sprints"), min_value=1, max_value=26, value=6, key="cal-n")
    sprints = absence_sprints(data, fc, int(count))
    if not sprints:
        st.info(t("No sprints found."))
        return
    rows = calendar_table(data, sprints, fc.today)
    for row in rows:
        row["Status"] = t(row["Status"])
    frame = pd.DataFrame(rows, columns=CALENDAR_COLUMNS)
    for col in ("Start", "Last day"):
        frame[col] = pd.to_datetime(frame[col])
    edited = st.data_editor(
        frame,
        column_config={
            "Sprint": st.column_config.TextColumn(disabled=True),
            "Start": st.column_config.DateColumn(t("Start"), format="DD.MM.YYYY", disabled=True),
            "Last day": st.column_config.DateColumn(
                t("Last day"),
                format="DD.MM.YYYY",
                help=t(
                    "The next sprint starts the day after. If a sprint differs (e.g. three "
                    "weeks over Christmas), change its last day here; the following "
                    "sprints shift accordingly."
                ),
            ),
            "Working days": st.column_config.NumberColumn(
                t("Working days"),
                disabled=True,
                help=t(
                    (
                        "Working days of the team's workweek ({week}) from the start up to and "
                        "including the last day, before deducting holidays."
                    ),
                    week=workweek_label(data.team),
                ),
            ),
            "Status": st.column_config.TextColumn(disabled=True),
        },
        hide_index=True,
        key=f"calendar-{data.team.key}-{len(sprints)}",
    )
    after, errors = apply_calendar(data, sprints, edited.to_dict("records"))
    for e in errors:
        st.error(e)
    to_save = calendar_to_save(data, sprints, after, create_missing=True)
    if to_save:
        st.caption(
            t("On save: ")
            + ", ".join(
                f"{s.id} ({t('new') if data.sprint(s.id) is None else t('changed')})"
                for s in to_save
            )
        )
    if st.button(t("Create or save sprints"), type="primary", disabled=bool(errors) or not to_save):
        preview = with_sprints(data, to_save)
        # The check reports overlaps on the successor, so check that one too.
        ids = [x.id for x in preview.sprints]
        saved = {x.id for x in to_save}
        checked = saved | {ids[i + 1] for i, sid in enumerate(ids[:-1]) if sid in saved}
        save(
            preview,
            [f"{sid}.yaml" for sid in checked],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )


# A sprint chosen deliberately anywhere applies on all pages that select a sprint.
BOARD_SPRINT = "board-sprint"


def sprint_options(fc: Forecast, history: int | None = 6) -> list[str]:
    """Selectable sprints in a fixed order: last completed, current, upcoming."""
    return [e.sprint.id for e in fc.history(history)] + [e.sprint.id for e in fc.upcoming()]


def sprint_select(
    data: TeamData,
    fc: Forecast,
    key: str,
    purpose: str = "planning",
    history: int | None = 6,
) -> Sprint | None:
    """Shared sprint selection of all pages: same label and order. The default is the last
    chosen sprint, otherwise the suggestion for the task (``purpose``, see
    ``Forecast.default_entry``: planning = next Planning, review = open review), otherwise
    the current sprint."""
    options = sprint_options(fc, history)
    if not options:
        return None
    wanted = st.session_state.get(BOARD_SPRINT)
    kwargs: dict[str, Any] = {}
    if wanted in options:
        st.session_state[key] = wanted
    else:
        default = fc.default_entry(purpose) or fc.current
        kwargs["index"] = (
            options.index(default.sprint.id) if default and default.sprint.id in options else 0
        )

    def remember() -> None:
        st.session_state[BOARD_SPRINT] = st.session_state[key]

    chosen = st.selectbox(t("Sprint"), options, key=key, on_change=remember, **kwargs)
    return copy.deepcopy(find_sprint(data, chosen))


# The three boards for product values; with "absences" in front they form the step bar (order as
# in the sidebar and start page: prepare, PO pre-planning, Planning, Review).
BOARDS = ("vorplanung", "planning", "review")
BOARD_STEPS = ("fehltage", *BOARDS)

# Step bar: all steps are built the same way: a link in a container with a key, in a grid of
# equally wide columns. Same height, width and alignment; only the color distinguishes the
# active step, so nothing jumps when switching. The text never wraps (overlong text would be
# truncated; at the minimum width even the longest title fits together with the done symbol,
# the tooltip only states the status). Depending on the width of the area, all steps sit side
# by side, two per row or stacked, never overlapping (container query instead of window
# width, because the sidebar changes the available space).
BOARD_NAV_STEP_REM = 16  # minimum width of a step (the longest title with symbol fits)
# "Done" state: green check mark symbol at the end of the step name (Material icon in Markdown
# color). Open steps carry no symbol; their state appears only in the tooltip.
BOARD_STEP_DONE_MARK = ":green[:material/check_circle:]"
BOARD_NAV_CSS = """
<style>
div.st-key-board-nav-box { container-type: inline-size; }
div.st-key-board-nav {
    display: grid; gap: 0.5rem; grid-template-columns: repeat(2, minmax(0, 1fr));
}
@container (max-width: 33rem) {
    div.st-key-board-nav { grid-template-columns: minmax(0, 1fr); }
}
div.st-key-board-nav > div { min-width: 0; }
div.st-key-board-nav [class*="st-key-board-step-"],
div.st-key-board-nav [class*="st-key-board-active-"] { height: 2.5rem; gap: 0; }
div.st-key-board-nav [data-testid="stElementContainer"],
div.st-key-board-nav [data-testid="stPageLink-NavLink"] { margin: 0; }
div.st-key-board-nav [data-testid="stPageLink"] { width: 100%; }
div.st-key-board-nav [data-testid="stPageLink-NavLink"] {
    box-sizing: border-box; width: 100%; height: 2.5rem; padding: 0 0.75rem;
    justify-content: center; align-items: center; border-radius: 0.5rem;
    border: 1px solid rgba(128, 128, 128, 0.4); white-space: nowrap; overflow: hidden;
}
div.st-key-board-nav [data-testid="stPageLink-NavLink"] p {
    margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
div.st-key-board-nav [class*="st-key-board-active-"] [data-testid="stPageLink-NavLink"] {
    background: #2a78d6; border-color: #2a78d6; font-weight: 600;
}
div.st-key-board-nav [class*="st-key-board-active-"] [data-testid="stPageLink-NavLink"],
div.st-key-board-nav [class*="st-key-board-active-"] [data-testid="stPageLink-NavLink"] * {
    color: #fff;
}
/* Das grüne Erledigt-Symbol hat die Farbe im style-Attribut; auf dem blauen Grund des aktiven
   Schritts ist Grün schlecht lesbar – dort wird es weiß (das Symbol bleibt dasselbe). */
div.st-key-board-nav [class*="st-key-board-active-"] .stMarkdownColoredText {
    color: #fff !important;
}
</style>
"""


def _board_nav_css(count: int) -> str:
    """CSS of the step bar; from the width at which all ``count`` steps fit side by side,
    they sit in one row."""
    wide = count * BOARD_NAV_STEP_REM + (count - 1) * 0.5
    return BOARD_NAV_CSS.replace(
        "</style>",
        f"@container (min-width: {wide:g}rem) {{\n"
        f"    div.st-key-board-nav {{ grid-template-columns: repeat({count}, minmax(0, 1fr)); }}\n"
        "}\n</style>",
    )


def _board_nav(data: TeamData, sprint: Sprint, current: str) -> None:
    """Step bar absences → PO pre-planning → Planning → Review with the status for the
    selected sprint, switch with one click. Pages of disabled feature areas (PO pre-planning
    without products) are dropped."""
    done = board_steps_done(data.sprint(sprint.id), data.products)
    enabled = st.session_state.get("enabled-pages", BOARD_STEPS)
    steps = [key for key in BOARD_STEPS if key in enabled]
    st.html(_board_nav_css(len(steps)))
    with st.container(key="board-nav-box"), st.container(key="board-nav"):
        for key in steps:
            title, icon = PAGE_INFO[key]
            active = key == current
            if done[key]:
                label = f"{t(title)} {BOARD_STEP_DONE_MARK}"
                hint = t("recorded for sprint {id}", id=sprint.id)
            else:  # open: no symbol, only the tooltip says so
                label = t(title)
                hint = t("still open for sprint {id}", id=sprint.id)
            with st.container(key=f"board-{'active' if active else 'step'}-{key}"):
                st.page_link(page_path(key), label=label, icon=icon, help=hint, width="stretch")


def _number(label: str, value: float | None, key: str, help: str | None = None) -> float | None:
    return st.number_input(
        label, min_value=0.0, value=value, step=0.25, format="%.2f", key=key, help=help
    )


# --- Products: table and chart --------------------------------------------------------

# Display for unrecorded values in tables (instead of the default "None").
NO_VALUE = "–"

# Categorical colors in a fixed order (product = catalog position); default is neutral.
SERIES_COLORS = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
]  # fmt: skip
STANDARD_COLOR = "#9a9a94"
MAX_PRODUCT_COLORS = len(SERIES_COLORS)


def _others() -> str:
    return t("Others")


def _standard_text(d: Distribution, unit: str) -> str:
    basis = (
        t("plannable share of the Forecast PLAN") if d.basis.value == "roadmap" else "Forecast PLAN"
    )
    if d.available is None or not d.active_count:
        return t(
            "Standard: {basis} / number of products handled – cannot be calculated yet.",
            basis=basis,
        )
    if any(r.product.share is not None for r in d.rows if r.active):
        return t(
            (
                "Standard = {basis}{frozen} {available} {unit}: products with a fixed share "
                "get it, the rest is split evenly across the others."
            ),
            basis=basis,
            frozen=t(" (forecast at planning, frozen)") if d.plan_frozen else "",
            available=fmt(d.available, 2),
            unit=unit,
        )
    return t(
        (
            "Standard = {basis}{frozen} {available} {unit} / {count} products handled = "
            "**{share} {unit}** per product."
        ),
        basis=basis,
        frozen=t(" (forecast at planning, frozen)") if d.plan_frozen else "",
        available=fmt(d.available, 2),
        unit=unit,
        count=d.active_count,
        share=fmt(d.available / d.active_count, 2),
    )


def _distribution_caption(d: Distribution, unit: str) -> str:
    return _standard_text(d, unit) + _frozen_note(d, unit)


def _frozen_note(d: Distribution, unit: str) -> str:
    """Note if the distributable amount was frozen at the Planning and the current forecast
    differs from it."""
    if not d.plan_frozen or d.plan is None or d.current_plan is None:
        return ""
    diff = d.current_plan - d.plan
    if abs(diff) < 0.05:
        return ""
    return " " + t(
        "Current forecast: {current} {unit} (difference {diff} {unit}).",
        current=fmt(d.current_plan, 2),
        unit=unit,
        diff=_signed(diff),
    )


def _production_hint(d: Distribution, data: TeamData, unit: str) -> None:
    """Capacity of the people with production access and a warning on overplanning: a
    bottleneck hint (rough approximation via the capacity share), not a commitment."""
    if not d.features.production:
        return
    planned = d.total("production_planned")
    entered = planned is not None or d.total("production_done") is not None
    if d.production_state == "unconfigured":
        if entered:
            st.info(
                t(
                    "Production access: nobody is marked as authorized (Manage team → "
                    "People) – whether the group can handle the planned tickets cannot be "
                    "checked."
                )
            )
        return
    if d.production_state == "unavailable":
        if planned:
            st.warning(
                t(
                    (
                        "Production access: the people marked as authorized have no capacity "
                        "in this sprint (absences, holidays or not in the team) – nobody can "
                        "work on the planned tickets with production access ({planned} {unit}) "
                        "(bottleneck)."
                    ),
                    planned=fmt(planned, 2),
                    unit=unit,
                )
            )
        return
    if d.production_share is None or d.production_available is None:
        return
    people = sum(1 for p in data.people if p.production_access)
    st.caption(
        t(
            (
                "Production access: {count} person(s) = {share} of the capacity → up to "
                "**{available} {unit}** possible (rough approximation: capacity share × "
                "Forecast PLAN), planned {planned} {unit}."
            ),
            count=people,
            share=pct(d.production_share),
            available=fmt(d.production_available, 2),
            unit=unit,
            planned=fmt(planned, 2) if planned is not None else "–",
        )
    )
    if (over := d.production_overload) is not None:
        st.warning(
            t(
                (
                    "More tickets requiring production access planned than the group can "
                    "handle ({over} {unit} too much) – other people cannot work on them."
                ),
                over=fmt(over, 2),
                unit=unit,
            )
        )


# Production columns per event (subsets of Planning or Done).
KIND_PRODUCTION_MEASURES = {
    PREPLANNING: (),
    PLANNING: ("production_planned",),
    REVIEW: ("production_done",),
}


def phase_measures(kind: str) -> list[str]:
    """Columns of the product table at an event: only what is entered or decided there (plus
    default or reference value); what only arises later is left out."""
    return [*KIND_MEASURES[kind], *KIND_PRODUCTION_MEASURES[kind]]


def _product_editor(
    d: Distribution, editable: list[str], key: str, unit: str, kind: str
) -> list[dict[str, Any]] | None:
    """Table product × columns of the event ``kind``; ``editable`` ones can be edited."""
    if not d.rows:
        st.info(
            t(
                "No products for this sprint – add products under **Manage team → "
                "Products** (optional)."
            )
        )
        return None
    column_config: dict[str, Any] = {
        "_id": None,
        "Product": st.column_config.TextColumn(t("Product"), disabled=True),
        "PO": st.column_config.TextColumn(disabled=True) if d.features.po else None,
    }
    shown = phase_measures(kind)
    for m, label in MEASURES.items():
        if m not in shown:
            continue
        column_config[label] = st.column_config.NumberColumn(
            f"{measure_label(m)} ({unit})",
            min_value=0.0,
            step=0.25,
            format="%.2f",
            disabled=m not in editable,
            help=t(FIELDS[m].what)
            if m in FIELDS
            else t("Available amount / number of products handled"),
        )
    show_production = d.features.production and (
        d.production_share is not None or any(d.has(m) for m in PRODUCTION_MEASURES)
    )
    for m, label in PRODUCTION_MEASURES.items():
        if m not in shown or not show_production:
            continue
        column_config[label] = st.column_config.NumberColumn(
            f"{measure_label(m)} ({unit})",
            min_value=0.0,
            step=0.25,
            format="%.2f",
            disabled=m not in editable,
            help=t(
                "Subset of planning or done: tickets that only people with production "
                "access can work on."
            ),
        )
    frame = pd.DataFrame(product_values_table(d))
    labels = [
        label
        for label in (*MEASURES.values(), *PRODUCTION_MEASURES.values())
        if label in column_config
    ]
    frame = frame[["_id", "Product", "PO", *labels]]
    for label in labels:
        frame[label] = frame[label].astype("float64").round(2)
    edited = st.data_editor(
        frame,
        column_config=column_config,
        hide_index=True,
        key=key,
        placeholder=NO_VALUE,  # display only: "not recorded" stays None in the data
    )
    st.caption(_distribution_caption(d, unit))
    return edited.to_dict("records")


def _product_table(d: Distribution, unit: str) -> bool:
    """Read-only table product × default/pre-planning/Planning/Done (evaluation).
    False if the sprint has no products."""
    if not d.rows:
        st.info(
            t(
                "No products for this sprint – add products under **Manage team → "
                "Products** (optional)."
            )
        )
        return False
    show_production = d.features.production and (
        d.production_share is not None or any(d.has(m) for m in PRODUCTION_MEASURES)
    )
    # Only columns with values: a sprint before the review has no "Done", before the Planning
    # no "Planning". The default always stays as a reference.
    columns = {
        m: label
        for m, label in (MEASURES | (PRODUCTION_MEASURES if show_production else {})).items()
        if m == "standard" or d.has(m)
    }
    frame = pd.DataFrame(product_values_table(d))
    frame = frame.drop(columns=["_id", *([] if d.features.po else ["PO"])])
    frame = frame[["Product", *(["PO"] if d.features.po else []), *columns.values()]]
    for label in columns.values():
        frame[label] = frame[label].astype("float64").round(2)
    st.dataframe(
        frame,
        hide_index=True,
        column_config={
            label: st.column_config.NumberColumn(f"{measure_label(m)} ({unit})", format="%.2f")
            for m, label in columns.items()
        },
        placeholder=NO_VALUE,
    )
    st.caption(_distribution_caption(d, unit))
    return True


def _product_chart(
    d: Distribution, unit: str, measures: list[str] | None = None
) -> alt.Chart | None:
    """Grouped bars per product: default (gray), pre-planning, Planning, Done; with
    ``measures`` only the metrics that matter at the respective event."""
    product, metric = t("Product"), t("Metric")
    shown = {m: label for m, label in MEASURES.items() if measures is None or m in measures}
    records = [
        {product: r.product.name, metric: measure_label(m), unit: value}
        for r in d.rows
        for m in shown
        if (value := r.value(m)) is not None
    ]
    if not records:
        return None
    labels = [measure_label(m) for m in shown]
    colors = dict(zip(MEASURES, [STANDARD_COLOR, *SERIES_COLORS[:3]], strict=True))
    return (
        alt.Chart(pd.DataFrame(records))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                f"{product}:N",
                sort=[r.product.name for r in d.rows],
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            xOffset=alt.XOffset(f"{metric}:N", sort=labels),
            y=alt.Y(f"{unit}:Q"),
            color=alt.Color(
                f"{metric}:N",
                sort=labels,
                scale=alt.Scale(domain=labels, range=[colors[m] for m in shown]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[f"{product}:N", f"{metric}:N", alt.Tooltip(f"{unit}:Q", format=".2f")],
        )
    )


def _product_colors(names: list[str]) -> alt.Scale:
    """Color follows the product (position in the product list), not its rank."""
    others = _others()
    domain = [n for n in names if n != others]
    rng = [SERIES_COLORS[i % MAX_PRODUCT_COLORS] for i in range(len(domain))]
    if others in names:
        domain.append(others)
        rng.append(STANDARD_COLOR)
    return alt.Scale(domain=domain, range=rng)


def _product_name(fc: Forecast, product_id: str, name: str) -> str:
    """With more than eight products, the later ones are grouped as "Others"."""
    products = fc.data.products
    if len(products) <= MAX_PRODUCT_COLORS:
        return name
    index = next((i for i, p in enumerate(products) if p.id == product_id), None)
    return name if index is not None and index < MAX_PRODUCT_COLORS - 1 else _others()


def _product_rank(fc: Forecast, product_id: str) -> int:
    """Position in the product list, determines the stacking order."""
    ids = [p.id for p in fc.data.products]
    return ids.index(product_id) if product_id in ids else len(ids)


def _history_chart(
    fc: Forecast, entries: list[TimelineEntry], measure: str, unit: str
) -> alt.Chart | None:
    product = t("Product")
    records = []
    for e in entries:
        for r in distribution(fc, e).rows:
            value = r.value(measure)
            if value is not None:
                records.append(
                    {
                        "Sprint": e.sprint.id,
                        product: _product_name(fc, r.product.id, r.product.name),
                        "rank": _product_rank(fc, r.product.id),
                        unit: value,
                    }
                )
    if not records:
        return None
    frame = (
        pd.DataFrame(records)
        .groupby(["Sprint", product], as_index=False)
        .agg({"rank": "min", unit: "sum"})
    )
    names = [p.name for p in fc.data.products]
    present = list(dict.fromkeys(frame[product]))
    ordered = [n for n in names if n in present] + [n for n in present if n not in names]
    return (
        alt.Chart(frame)
        .mark_bar(stroke="white", strokeWidth=2)
        .encode(
            x=alt.X(
                "Sprint:N",
                sort=[e.sprint.id for e in entries],
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(f"{unit}:Q", stack="zero"),
            color=alt.Color(
                f"{product}:N",
                sort=ordered,
                scale=_product_colors(ordered),
                legend=alt.Legend(orient="top", title=None),
            ),
            order=alt.Order("rank:Q"),
            tooltip=["Sprint:N", f"{product}:N", alt.Tooltip(f"{unit}:Q", format=".2f")],
        )
    )


def _balance_section(fc: Forecast, entries: list[TimelineEntry], unit: str) -> None:
    all_rows = balance(fc, entries)
    rows = [b for b in all_rows if b.sprints]  # only products with at least one value
    if not rows:
        st.info(t("No **done per product** recorded yet – enter it at the review."))
        return
    product, direction = t("Product"), t("Direction")
    more, less = t("more than standard"), t("less than standard")
    balance_label = f"{t('Balance')} ({unit})"
    frame = pd.DataFrame(
        [
            {
                product: b.product.name,
                "Sprints": b.sprints,
                f"Σ Standard ({unit})": round(b.standard, 2),
                f"Σ {t('Done')} ({unit})": round(b.done, 2),
                balance_label: round(b.difference, 2),
                direction: more if b.difference >= 0 else less,
                t("no value"): b.missing,
            }
            for b in rows
        ]
    )
    missing_col = t("no value")
    st.altair_chart(
        alt.Chart(frame)
        .mark_bar(cornerRadius=4)
        .encode(
            y=alt.Y(f"{product}:N", sort=[b.product.name for b in rows], title=None),
            x=alt.X(f"{balance_label}:Q"),
            color=alt.Color(
                f"{direction}:N",
                scale=alt.Scale(domain=[more, less], range=["#2a78d6", "#e34948"]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[c for c in frame.columns if c not in (direction, missing_col)],
        ),
        width="stretch",
    )
    shown = frame.drop(columns=direction)
    if not frame[missing_col].any():
        shown = shown.drop(columns=missing_col)
    st.dataframe(shown, hide_index=True)
    st.caption(
        t(
            "Balance = Σ done − Σ default over the sprints in which done is recorded for "
            "the product. Positive: the product received more than the even share. Sprints "
            "without a value (not recorded, not 0) do not count."
        )
    )


def _preview_forecast(data: TeamData, fc: Forecast, base: Sprint, after: Sprint) -> Forecast:
    """Forecast for the preview of an input. If the sprint is not saved yet and the input
    changed nothing, the existing forecast stays: an (empty) sprint file would otherwise
    switch the capacity from the estimate to "everyone present"."""
    if data.sprint(after.id) is None and after.products == base.products:
        return fc
    return build_forecast(with_sprints(data, [after]), fc.today)


def _base_sprint(data: TeamData, sprint: Sprint) -> Sprint:
    return copy.deepcopy(data.sprint(sprint.id) or sprint)


# --- Planning (guided flow for the sprint start) --------------------------------------

PLANNING_STEPS = ["1 · Absences", "2 · Forecast PLAN & planning", "3 · Commitment"]
STEP_KEY = "planning-step"


def _goto(step: int) -> None:
    st.session_state["planning-goto"] = step


def _unfreeze_panel(repo: Repository, data: TeamData, sprint: Sprint, unit: str) -> None:
    """Release a frozen Forecast PLAN again to correct a mistake."""
    with st.expander(
        t("Forecast PLAN {plan} {unit} is frozen", plan=fmt(sprint.forecast_plan), unit=unit),
        icon=":material/lock:",
    ):
        st.warning(
            t(
                "Only release the freeze to correct a **mistake**. Tickets pulled in or "
                "taken out after the planning do **not belong retroactively in the "
                "planning** but flow into the **review** (Of which not finished / "
                "Additionally done). After releasing, the Forecast PLAN is recalculated "
                "and frozen again the next time the planning is saved."
            )
        )
        # Reset the confirmation after releasing, so it is not still checked the next time the
        # same sprint is frozen.
        if st.session_state.pop("unfreeze-reset", None) == sprint.id:
            st.session_state[f"unfreeze-{sprint.id}"] = False
        confirmed = st.checkbox(
            t("Yes, this is a correction of a mistake"), key=f"unfreeze-{sprint.id}"
        )
        if st.button(t("Release freeze"), disabled=not confirmed, key=f"unfreeze-go-{sprint.id}"):
            released = copy.deepcopy(sprint)
            released.forecast_plan = None

            def release() -> list[Path]:
                # The Planning no longer applies: its protocol is marked as obsolete.
                return obsolete_with_save(
                    repo,
                    data.team.key,
                    released.id,
                    PLANNING,
                    datetime.now,
                    lambda: [repo.save_sprint(data.team.key, released)],
                )

            if save(
                with_sprints(data, [released]),
                [f"{released.id}.yaml"],
                release,
                flash=True,
            ):
                st.session_state["unfreeze-reset"] = sprint.id
                st.rerun()


def page_planning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprint Planning")
    sprint = sprint_select(data, fc, "planning-sprint")
    if sprint is None:
        return
    _board_nav(data, sprint, "planning")
    if sprint.forecast_plan is not None:
        _unfreeze_panel(repo, data, sprint, data.team.unit.value)
    _protocols(repo, data, sprint.id, PLANNING)
    # New sprint selected → start at the first step.
    if st.session_state.get("planning-last-sprint") != sprint.id:
        st.session_state["planning-last-sprint"] = sprint.id
        st.session_state["planning-goto"] = 0
    if (goto := st.session_state.pop("planning-goto", None)) is not None:
        st.session_state[STEP_KEY] = goto
    st.caption(
        t(
            (
                "Planning on **{day}** · flow: first the known absences, then plan the tickets "
                "with the Forecast PLAN, enter the commitment before the sprint starts."
            ),
            day=day_label(sprint.start),
        )
    )
    step = st.radio(
        t("Step"),
        range(len(PLANNING_STEPS)),
        format_func=lambda i: t(PLANNING_STEPS[i]),
        horizontal=True,
        key=STEP_KEY,
        label_visibility="collapsed",
    )
    recorded = data.sprint(sprint.id)
    done = [
        board_steps_done(recorded)["fehltage"],  # like the check mark of the step bar above
        recorded is not None and any(v.planned is not None for v in recorded.products.values()),
        recorded is not None and recorded.forecast_ist is not None,
    ]
    marks = [
        f"{'✅' if ok else '⬜'} {t(s)[4:]}" for s, ok in zip(PLANNING_STEPS, done, strict=True)
    ]
    st.caption(" · ".join(marks))
    if step == 0:
        _planning_absences(repo, data, fc, sprint)
    elif step == 1:
        _planning_plan(repo, data, fc, sprint)
    else:
        _planning_ist(repo, data, fc, sprint)


def _planning_writer(
    repo: Repository, data_after: TeamData, today: date, sprint: Sprint
) -> Callable[[], list[Path]]:
    """When a Planning step is saved, write a complete Planning protocol with the sections
    absences, scheduling and commitment (each with its own status), and then the sprint file.
    ``data_after`` is the state with the ``sprint`` to be saved; sections of later steps that
    are not saved yet appear in it as "not yet recorded"."""
    unit = data_after.team.unit.value
    team = data_after.team
    fc = build_forecast(data_after, today)
    entry = fc.entry(sprint.id)
    now = datetime.now().replace(microsecond=0)
    names = {p.id: p.name for p in data_after.people}
    result = entry.result if entry else None

    absences = [
        md_item(f"{names.get(pid, pid)}: {fmt(days, 1)} {t('days')}")
        for pid, days in sorted(sprint.absences.items())  # fixed order: stable state
        if days
    ]
    sections = [
        PlanningSection(
            "absences",
            t("Absences"),
            [md_item(t("State of the absences: {state}", state=absence_status_label(sprint)))]
            + (absences or [md_item(t("Nobody is absent."))]),
            recorded=absence_status(sprint) is AbsenceState.CONFIRMED,
        )
    ]

    d = distribution(fc, entry) if entry else None
    products = d is not None and team.features.products and bool(data_after.products)
    planned_lines: list[str] = []
    # The frozen value if there is one: the current one also changes through other steps and
    # would make the status of sections drift without a change of their own.
    plan = sprint.forecast_plan if sprint.forecast_plan is not None else (result and result.plan)
    if plan is not None:
        planned_lines.append(md_item(f"{t('Forecast PLAN')}: {fmt(plan, 2)} {unit}"))
    if products and d is not None and d.rows:
        planned_lines.append(md_item(f"{t('Scheduled (Σ)')}: {fmt(d.total('planned'), 2)} {unit}"))
    if sprint.production_planned is not None:
        planned_lines.append(
            md_item(
                f"{t('Of which with production access')}: "
                f"{fmt(sprint.production_planned, 2)} {unit}"
            )
        )
    if products and d is not None:
        planned_lines += planning_distribution_lines(d, team.features.po)
    sections.append(
        PlanningSection(
            "plan",
            t("Scheduling"),
            planned_lines,
            # With a saved commitment the scheduling is complete, even if only the default of
            # the distribution applies.
            recorded=any(v.planned is not None for v in sprint.products.values())
            or sprint.production_planned is not None
            or sprint.forecast_ist is not None,
        )
    )

    p = sprint.planning
    commitment_lines = [
        md_item(f"{t('Commitment ({unit})', unit=unit)}: {fmt(sprint.forecast_ist, 2)}")
    ]
    if sprint.forecast_plan is not None:
        commitment_lines.append(
            md_item(
                f"{t('Forecast at planning ({unit})', unit=unit)}: {fmt(sprint.forecast_plan, 2)}"
            )
        )
    if p is not None:
        commitment_lines += [
            md_item(f"{t('Carry-over ({unit})', unit=unit)}: {fmt(p.carryover, 2)}"),
            md_item(f"Backlog ({unit}): {fmt(p.backlog, 2)}"),
        ]
    if result is not None and result.planning_total is not None:
        commitment_lines.append(
            md_item(f"{t('Planning total')}: {fmt(result.planning_total, 2)} {unit}")
        )
        if plan is not None:
            delta = fmt(plan - result.planning_total, 2)
            commitment_lines.append(md_item(f"{t('Delta to Forecast PLAN')}: {delta} {unit}"))
    sections.append(
        PlanningSection(
            "commitment",
            t("Commitment"),
            commitment_lines,
            recorded=sprint.forecast_ist is not None,
        )
    )

    protocol = render_planning_protocol(
        team.name or team.key,
        sprint.id,
        now=now,
        facts=[
            (t("Capacity (PT)"), capacity_label(entry) if entry else "–"),
            (t("Current forecast ({unit})", unit=unit), fmt(result.plan, 2) if result else "–"),
        ],
        sections=sections,
        previous=latest_planning_sections(repo, team.key, sprint.id),
    )
    return lambda: save_with_protocol(
        repo,
        team.key,
        sprint.id,
        PLANNING,
        protocol,
        datetime.now,
        [sprint],
        lambda: [repo.save_sprint(team.key, sprint)],
    )  # minutes: not mentioned in the message


def _planning_absences(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    st.subheader(t("Known absences"))
    st.caption(sprint_caption(data, sprint))
    if not data.people:
        st.warning(
            t(
                "No people recorded yet – capacity only estimated. Add people under "
                "**Manage team → People**."
            )
        )
        st.button(t("Next"), on_click=_goto, args=(1,), type="primary")
        return
    base = _base_sprint(data, sprint)
    shown_sprint = copy.deepcopy(base)
    prefilled = not absences_known(base) and bool(base.expected_absences)
    if prefilled:
        shown_sprint.absences = dict(base.expected_absences)
        st.info(
            t(
                "Prefilled with the announced absences from the PO pre-planning – please "
                "check and confirm."
            )
        )
    days = len(team_workdays(data.team, base.start, base.end))
    edited = st.data_editor(
        pd.DataFrame(absence_matrix(data.people, [shown_sprint])),
        column_config={
            "id": None,
            "Person": st.column_config.TextColumn(t("Person"), disabled=True),
            base.id: st.column_config.NumberColumn(
                t("Absences"),
                min_value=0.0,
                max_value=float(days),
                step=0.5,
                help=help_text("absences"),
            ),
        },
        hide_index=True,
        key=f"planning-absences-{base.id}",
        placeholder="",  # empty = person is not on the team in this sprint, not "None"
    )
    [after] = edit_absences(data.people, [shown_sprint], edited.to_dict("records"))
    to_save = sprints_to_save(data, [base], [after])
    preview = with_sprints(data, [after])
    fc_after = build_forecast(preview, fc.today)
    entry = fc_after.entry(after.id)
    unconfirmed = absence_status(after) is not AbsenceState.CONFIRMED
    if unconfirmed:
        st.warning(
            t(
                (
                    "Absences for {id}: {state}. Calculating with {capacity} PT. Please enter "
                    "known absences – or explicitly confirm that nobody is absent. “Continue "
                    "without confirmation” leaves the absences unknown."
                ),
                id=after.id,
                state=absence_status_label(after),
                capacity=capacity_label(entry) if entry else "–",
            )
        )
    left, right = st.columns(2)
    left.metric(
        t("Capacity (PT)"),
        fmt_capacity(entry.result.plan_capacity, entry.capacity_digits) if entry else "–",
        help=_formula_help(fc_after, entry, "capacity"),
    )
    right.metric(
        t("Current forecast ({unit})", unit=data.team.unit.value),
        fmt(entry.result.plan) if entry else "–",
        help=_formula_help(fc_after, entry, "plan"),
    )
    if entry is not None:
        _quote_note(fc_after, [entry])
    if after.capacity is not None:
        st.info(
            t(
                (
                    "The sprint file contains a fixed capacity ({capacity} PT) – it applies "
                    "instead of the calculation from the absences."
                ),
                capacity=fmt_capacity(after.capacity, data.team.capacity.rounding),
            )
        )
    if to_save:
        if st.button(t("Save absences and continue"), type="primary"):
            ok = save(
                preview,
                [f"{after.id}.yaml"],
                _planning_writer(repo, preview, fc.today, after),
                flash=True,
            )
            if ok:
                _goto(1)
                st.rerun()
    elif unconfirmed:
        nobody, skip = st.columns(2)
        if nobody.button(t("Nobody is absent – confirm and continue"), type="primary"):
            confirmed = copy.deepcopy(after)
            confirmed.absence_state = AbsenceState.CONFIRMED
            confirmed_data = with_sprints(data, [confirmed])
            ok = save(
                confirmed_data,
                [f"{after.id}.yaml"],
                _planning_writer(repo, confirmed_data, fc.today, confirmed),
                flash=True,
            )
            if ok:
                _goto(1)
                st.rerun()
        skip.button(t("Continue without confirmation"), on_click=_goto, args=(1,))
    else:
        st.button(t("Next"), on_click=_goto, args=(1,), type="primary")


def _production_split_note(fc: Forecast, entry: Any, data: TeamData, unit: str) -> str | None:
    """Split of capacity and Forecast PLAN into people with and without production access
    (approximated via the capacity share). None if the team does not use this or nobody
    is marked as authorized."""
    if not data.team.features.production:
        return None
    d = distribution(fc, entry)
    share = d.production_share
    capacity = entry.result.plan_capacity
    if d.production_state != "ok" or share is None or capacity is None or d.available is None:
        return None
    # Both amounts come from the current Forecast PLAN: ``d.production_available`` uses the value
    # frozen at Planning and, combined with the current one, would not give a clean split.
    plan = entry.result.plan
    prod_plan = None if plan is None else plan * share
    return t(
        (
            "Capacity: {prod_cap} PD with production access ({share}), {rest_cap} PD without · "
            "Forecast PLAN: up to {prod_plan} {unit} for tickets with production access, "
            "{rest_plan} {unit} for all others."
        ),
        prod_cap=fmt(capacity * share, 1),
        share=pct(share),
        rest_cap=fmt(capacity * (1 - share), 1),
        prod_plan=fmt(prod_plan, 1) if prod_plan is not None else "–",
        rest_plan=fmt(plan - prod_plan, 1) if plan is not None and prod_plan is not None else "–",
        unit=unit,
    )


def _capacity_gauge(usage: CapacityUsage | None, unit: str) -> None:
    """Planned amount compared to the Forecast PLAN, updated with every input."""
    if usage is None:
        return
    st.progress(
        min(usage.ratio, 1.0),
        text=t(
            "Planned: **{planned} {unit}** of {plan} {unit} ({share})",
            planned=fmt(usage.planned, 2),
            plan=fmt(usage.plan),
            unit=unit,
            share=pct(usage.ratio) if usage.plan > 0 else "–",
        ),
    )
    if usage.over:
        st.warning(t("{rest} {unit} too much.", rest=fmt(-usage.rest, 2), unit=unit))
    else:
        st.success(t("{rest} {unit} still free.", rest=fmt(usage.rest, 2), unit=unit))


def _planning_plan(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    entry = fc.entry(sprint.id)
    st.subheader(t("Forecast PLAN – plan this much"))
    if entry is None:
        st.info(t("There is no forecast for this sprint."))
        return
    page_intro(
        t(
            "The Forecast PLAN is the amount the team can plan. While you enter values, "
            'the "Planned" display shows how much of it is already planned and how much '
            "is still free."
        ),
        t(
            (
                "The display recalculates with every value you enter, before anything is "
                "saved. It is compared with the current forecast in {unit}. For teams with "
                "products it is the sum of the planning values per product; otherwise it is "
                'the amount entered under "Planned so far" (scratch calculation only, not '
                "saved – the commitment comes in the next step)."
            ),
            unit=unit,
        ),
        t('More: how to read "Planned"'),
    )
    r = entry.result
    view = plan_view(entry)
    cols = st.columns(5 if view.frozen is not None else 4)
    cols[0].metric(
        t("Capacity (PT)"),
        fmt_capacity(r.plan_capacity, entry.capacity_digits),
        # The source goes below the value (not inside it): otherwise the number is truncated.
        delta=capacity_source_note(entry) or None,
        delta_color="off",
        delta_arrow="off",
        help=t("Source: {source}", source=source_label(r.plan_capacity_source) or "–")
        + "\n\n"
        + _formula_help(fc, entry, "capacity"),
    )
    cols[1].metric(
        t("Current forecast ({unit})", unit=unit),
        fmt(r.plan),
        help=_formula_help(fc, entry, "plan"),
    )
    rest = cols[2:]
    if view.frozen is not None:
        rest[0].metric(
            t("Forecast at planning ({unit})", unit=unit),
            fmt(view.frozen),
            delta=None if view.difference is None else _signed(view.difference),
            delta_color="off",
            help=t(
                "Frozen at planning (basis of the default distribution per product). The "
                "number below is the difference of the current forecast to this value."
            ),
        )
        rest = rest[1:]
    rest[0].metric(
        t("Plannable ({share})", share=pct(data.team.forecast.roadmap_share)),
        fmt(r.roadmap, 2),
        help=_formula_help(fc, entry, "roadmap"),
    )
    rest[1].metric(
        t("Small items"), fmt(r.small_stuff, 2), help=_formula_help(fc, entry, "small_stuff")
    )
    if note := band_note(fc, entry):
        st.caption(note)
    if split := _production_split_note(fc, entry, data, unit):
        st.caption(split)
    _quote_note(fc, [entry])
    with st.expander(t("Calculation path"), icon=":material/function:"):
        _rechenweg(fc, entry)
    if r.plan_capacity_source in UNSURE_SOURCES:
        st.warning(t("No absences recorded yet – the capacity is only estimated."))
        st.button(t("Back to the absences"), on_click=_goto, args=(0,))
    features = data.team.features
    # Without a product editor (no product area or no products in the sprint) there is no
    # total to compare against: then a helper calculation, before all save steps.
    if not (features.products and data.products and distribution(fc, entry).rows):
        scratch = _number(
            t("Planned so far ({unit})", unit=unit),
            None,
            f"planning-scratch-{sprint.id}",
            t("Scratch calculation for the planning: not saved."),
        )
        _capacity_gauge(capacity_usage(r.plan, scratch), unit)
    if features.tickets and data.tickets:
        _planning_ticket_hint(data, fc, sprint)
    if features.products and data.products:
        st.subheader(t("Scheduling per product"))
        d = distribution(fc, entry)
        carried = False
        for row in d.rows:
            if row.planned is None and row.preplanned is not None:
                row.planned = row.preplanned
                carried = True
        if carried:
            st.caption(
                t(
                    "The planning is prefilled with the last PO pre-planning – please "
                    "check, adjust and save."
                )
            )
        rows = _product_editor(
            d,
            ["preplanned", "planned", "production_planned"],
            f"planning-products-{sprint.id}",
            unit,
            PLANNING,
        )
        if rows is not None:
            base = _base_sprint(data, sprint)
            after = apply_product_values(
                base, rows, ["preplanned", "planned", "production_planned"]
            )
            preview = with_sprints(data, [after])
            fc_preview = _preview_forecast(data, fc, base, after)
            d_preview = distribution(fc_preview, fc_preview.entry(after.id) or entry)
            _production_hint(d_preview, data, unit)
            _capacity_gauge(capacity_usage(r.plan, d_preview.total("planned")), unit)
            if chart := _product_chart(d_preview, unit, phase_measures(PLANNING)):
                st.altair_chart(chart, width="stretch")
            if after.products != base.products or data.sprint(after.id) is None:
                if st.button(t("Save product values and continue"), type="primary"):
                    ok = save(
                        preview,
                        [f"{after.id}.yaml"],
                        _planning_writer(repo, preview, fc.today, after),
                        flash=True,
                    )
                    if ok:
                        _goto(2)
                        st.rerun()
                return
    elif features.products:
        st.caption(
            t(
                "Optional: with products under **Manage team → Products** you can plan and "
                "evaluate the distribution across products here."
            )
        )
    elif features.production and _planning_production(repo, data, fc, sprint, entry):
        return
    st.button(t("Next"), on_click=_goto, args=(2,), type="primary")


def _planning_ticket_hint(data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    """Suggestion from the ticket pre-planning: what the tickets take up in the sprint, per
    product. Only shown; the values are not adopted automatically."""
    from sprintforecast.preplan import distribute, sprint_sums

    dist = distribute(data, fc.today)
    sums = {k: v for k, v in sprint_sums(dist, sprint.id, data).items() if v > 0}
    if not sums:
        return
    unit = data.team.unit.value
    names = {p.id: p.name for p in data.products}
    total = sum(sums.values())
    with st.expander(
        t("Suggestion from the ticket pre-planning: {total} {unit}", total=fmt(total), unit=unit),
        icon=":material/view_kanban:",
    ):
        st.caption(
            t(
                "The tickets that the ticket pre-planning puts into this sprint (sprint "
                "according to the ticket system, earmarks and distribution), summed per "
                "product. Only a guide for the planning; nothing is adopted."
            )
        )
        if data.team.features.products:
            st.dataframe(
                pd.DataFrame(
                    [
                        {t("Product"): names.get(k, k) or "–", f"{t('Tickets')} ({unit})": fmt(v)}
                        for k, v in sums.items()
                    ]
                ),
                hide_index=True,
            )
        page_link("tickets")


def _planning_production(
    repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint, entry: TimelineEntry
) -> bool:
    """Teams without product distribution: amount with production access per sprint. True if a
    change can be saved (the caller then shows no "Next")."""
    unit = data.team.unit.value
    st.subheader(t("Topics with production access"))
    base = _base_sprint(data, sprint)
    planned = _number(
        t("Of which with production access ({unit})", unit=unit),
        base.production_planned,
        f"production-planned-{base.id}",
        t("Part of the planning: tickets that only people with production access can work on."),
    )
    after = copy.deepcopy(base)
    after.production_planned = planned
    preview = with_sprints(data, [after])
    fc_preview = _preview_forecast(data, fc, base, after)
    _production_hint(distribution(fc_preview, fc_preview.entry(after.id) or entry), data, unit)
    if after.production_planned == base.production_planned:
        return False
    if st.button(t("Save and continue"), type="primary", key="production-planned-save"):
        ok = save(
            preview,
            [f"{after.id}.yaml"],
            _planning_writer(repo, preview, fc.today, after),
            flash=True,
        )
        if ok:
            _goto(2)
            st.rerun()
    return True


def _planning_ist(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    sprint = _base_sprint(data, sprint)
    entry = fc.entry(sprint.id)
    st.subheader(t("Commitment – before the sprint starts"))
    if entry:
        st.caption(
            t(
                "Current forecast {plan} {unit}{frozen} · capacity {capacity} PT",
                plan=fmt(entry.result.plan),
                frozen=(
                    t(
                        ", at planning {frozen} {unit}",
                        frozen=fmt(sprint.forecast_plan),
                        unit=unit,
                    )
                    if sprint.forecast_plan is not None
                    else ""
                ),
                unit=unit,
                capacity=capacity_label(entry),
            )
        )
    planned = [v.planned for v in sprint.products.values() if v.planned is not None]
    if planned:
        st.caption(
            t("Total planned per product: {total} {unit}", total=fmt(sum(planned), 2), unit=unit)
        )
    with st.form(f"planning-{sprint.id}"):
        forecast_ist = _number(
            t("Commitment ({unit})", unit=unit),
            sprint.forecast_ist,
            f"fist-{sprint.id}",
            help_text("forecast_ist"),
        )
        p = sprint.planning or Planning()
        with st.expander(t("Cross-check (optional)"), expanded=sprint.planning is not None):
            st.caption(
                t(
                    "Checks whether the planning fits the Forecast PLAN: delta = Forecast "
                    "PLAN − (carry-over + backlog − corrections). Does not affect any "
                    "other metric. If the commitment is empty, it is prefilled with "
                    "carry-over + backlog; if it differs, a note appears."
                )
            )
            carryover = _number(
                t("Carry-over ({unit})", unit=unit),
                p.carryover or None,
                f"carry-{sprint.id}",
                help_text("carryover"),
            )
            backlog = _number(
                f"Backlog ({unit})", p.backlog or None, f"backlog-{sprint.id}", help_text("backlog")
            )
            corrections_raw = st.text_input(
                t("Corrections of remaining effort ({unit})", unit=unit),
                " ".join(f"{c:g}" for c in p.corrections),
                help=help_text("corrections"),
            )
        refreeze = False
        if offer := refreeze_offer(sprint, entry):
            refreeze = st.checkbox(
                t(
                    "Freeze Forecast PLAN again ({frozen} → {current} {unit})",
                    frozen=fmt(offer[0]),
                    current=fmt(offer[1]),
                    unit=unit,
                ),
                value=False,
                key=f"refreeze-{sprint.id}",
                help=t(
                    "The value frozen at the first planning is the basis of the standard "
                    "distribution per product and otherwise stays unchanged."
                ),
            )
        submitted = st.form_submit_button(t("Save planning"), type="primary")
    if not submitted:
        return
    try:
        corrections = parse_numbers(corrections_raw)
    except ValueError:
        st.error(t("Corrections: please enter finite numbers separated by spaces."))
        return
    prefilled = apply_planning(
        sprint,
        forecast_ist,
        Planning(carryover=carryover or 0.0, backlog=backlog or 0.0, corrections=corrections),
    )
    freeze_plan(sprint, entry, fc.today, refreeze=refreeze)
    prefill_note = (
        t(
            "Commitment taken from carry-over + backlog: {value} {unit}",
            value=fmt(sprint.forecast_ist, 2),
            unit=unit,
        )
        if prefilled
        else None
    )
    if prefill_note:
        st.info(prefill_note)
    after = with_sprints(data, [sprint])
    if save(
        after, [f"{sprint.id}.yaml"], _planning_writer(repo, after, fc.today, sprint), flash=True
    ):
        # The hints appear in the next run; it also redraws the step bar.
        flash = st.session_state.setdefault("flash", [])
        if prefill_note:  # in the next run the Commitment is saved, so no suggestion any more
            flash.append(("info", prefill_note))
        e = build_forecast(after, fc.today).entry(sprint.id)
        if e and e.result.planning_total is not None:
            flash.append(
                (
                    "info",
                    t(
                        (
                            "Planning total {total} {unit} · Forecast PLAN {plan} {unit} · "
                            "delta {delta} {unit}"
                        ),
                        total=fmt(e.result.planning_total, 2),
                        plan=fmt(e.result.plan),
                        delta=fmt(e.result.planning_delta, 2),
                        unit=unit,
                    ),
                )
            )
        if sprint.forecast_ist is not None:
            flash.append(
                (
                    "success",
                    t("Planning {id} complete – the sprint can start.", id=sprint.id),
                )
            )
        st.rerun()


def _review_prognosis_hint(sprint: Sprint, unit: str) -> None:
    """Latest forecast of the team from the PO pre-planning, for comparison with the result."""
    if not sprint.prognoses:
        return
    last = sprint.prognoses[-1]
    text = t(
        "Last forecast ({at}): expected done **{expected} {unit}**",
        at=f"{last.at:%d.%m.%Y %H:%M}",
        expected=fmt(last.expected_done, 2),
        unit=unit,
    )
    if last.comment:
        text += f" – {last.comment}"
    if sprint.velocity is not None and last.expected_done is not None:
        text += " · " + t(
            "Deviation from velocity: {diff} {unit}",
            diff=_signed(sprint.velocity - last.expected_done),
            unit=unit,
        )
    st.caption(text)


def page_review(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprint Review")
    sprint = sprint_select(data, fc, "review-sprint", "review")
    if sprint is None:
        return
    _board_nav(data, sprint, "review")
    _protocols(repo, data, sprint.id, REVIEW)
    unit = data.team.unit.value
    computed = sprint_capacity(data.team, data.people, sprint).rounded if data.people else None
    st.caption(
        t(
            "The review records what the sprint achieved: the amount done, what was not "
            "finished and what was done in addition. Tickets pulled in or taken out after "
            "the planning are recorded here – not retroactively in the planning."
        )
    )
    _review_prognosis_hint(sprint, unit)
    with st.form(f"review-{sprint.id}"):
        velocity = _number(
            t("Done – velocity ({unit})", unit=unit),
            sprint.velocity,
            f"velocity-{sprint.id}",
            help_text("velocity"),
        )
        not_done_col, extra_col = st.columns(2)
        not_done = not_done_col.number_input(
            t("Of which not finished ({unit})", unit=unit),
            key=f"not-done-{sprint.id}",
            min_value=0.0,
            value=sprint.not_done,
            step=0.25,
            format="%.2f",
            help=t(
                "Amount of the commitment that was not finished in the sprint. Optional – "
                "velocity = commitment − not finished + additionally done."
            ),
        )
        additional = extra_col.number_input(
            t("Additionally done ({unit})", unit=unit),
            key=f"additional-done-{sprint.id}",
            min_value=0.0,
            value=sprint.additional_done,
            step=0.25,
            format="%.2f",
            help=t("Amount done in addition to the commitment. Optional."),
        )
        scope = st.number_input(
            "Scope Creep (%)",
            key=f"scope-{sprint.id}",
            min_value=0.0,
            max_value=500.0,
            value=None if sprint.scope_creep is None else round(sprint.scope_creep * 100, 4),
            step=5.0,
            help=help_text("scope_creep"),
        )
        product_rows = None
        entry = fc.entry(sprint.id)
        production_done = sprint.production_done
        review_measures = ["done", *(["production_done"] if data.team.features.production else [])]
        if data.team.features.products and data.products and entry is not None:
            st.markdown(f"**{t('Done per product')}**")
            product_rows = _product_editor(
                distribution(fc, entry),
                review_measures,
                f"review-products-{sprint.id}",
                unit,
                REVIEW,
            )
        elif data.team.features.production and not data.team.features.products:
            st.markdown(f"**{t('Topics with production access')}**")
            production_done = _number(
                t("Of which done with production access ({unit})", unit=unit),
                sprint.production_done,
                f"production-done-{sprint.id}",
                t(
                    "Part of the velocity: tickets that only people with production access "
                    "can work on."
                ),
            )
        st.markdown(f"**{t('Person days of the sprint')}**")
        capacity = _number(
            t("Available person days (PT) – frozen"),
            sprint.capacity if sprint.capacity is not None else computed,
            f"capacity-{sprint.id}",
            t(
                "Only the reference to make the amount done comparable between sprints "
                "(velocity / person days). Prefilled from the people list and absences; "
                "frozen here."
            )
            + (
                "\n\n"
                + t(
                    "According to people list and absences: {capacity} PT",
                    capacity=fmt_capacity(computed, data.team.capacity.rounding),
                )
                if computed
                else ""
            ),
        )
        tag = st.checkbox(
            t("Set tag {tag} when committing", tag=f"{data.team.key}/{sprint.id}"),
            value=True,
            key=f"review-tag-{sprint.id}",
        )
        submitted = st.form_submit_button(t("Save review"), type="primary")
    if not submitted:
        return
    if capacity is None:
        st.error(t("Please enter the available person days."))
        return
    sprint.capacity = capacity
    sprint.velocity = velocity
    sprint.not_done = not_done
    sprint.additional_done = additional
    sprint.scope_creep = None if scope is None else scope / 100
    if data.team.features.production and not data.team.features.products:
        sprint.production_done = production_done
    if product_rows is not None:
        sprint = apply_product_values(sprint, product_rows, review_measures)
    after = with_sprints(data, [sprint])
    fc_after = build_forecast(after, fc.today)
    e_after = fc_after.entry(sprint.id)
    now = datetime.now().replace(microsecond=0)
    protocol = render_protocol(
        REVIEW,
        data.team.name or data.team.key,
        sprint.id,
        now=now,
        facts=[
            (t("Done – velocity ({unit})", unit=unit), fmt(sprint.velocity, 2)),
            (t("Commitment ({unit})", unit=unit), fmt(sprint.forecast_ist, 2)),
            (t("Of which not finished ({unit})", unit=unit), fmt(sprint.not_done, 2)),
            (t("Additionally done ({unit})", unit=unit), fmt(sprint.additional_done, 2)),
            (t("Available person days (PD)"), fmt(sprint.capacity, 1)),
        ],
        d=distribution(fc_after, e_after)
        if e_after and data.products and product_rows is not None
        else None,
        show_po=data.team.features.po,
    )

    def write() -> list[Path]:
        return save_with_protocol(
            repo,
            data.team.key,
            sprint.id,
            REVIEW,
            protocol,
            datetime.now,
            [sprint],
            lambda: [repo.save_sprint(data.team.key, sprint)],
        )  # minutes: not mentioned in the message

    if save(
        after,
        [f"{sprint.id}.yaml"],
        write,
        tag=f"{data.team.key}/{sprint.id}" if tag else None,
        flash=True,
    ):
        st.rerun()  # the step bar above shows the saved state


def page_analysis(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Analysis"))
    st.caption(
        t(
            "Complements the forecast. The values on the **Forecast** page (Forecast PLAN, "
            "plannable, small items) stay unchanged."
        )
    )
    unit = data.team.unit.value
    window = data.team.forecast.window

    st.subheader(t("Spread"))
    rows = []
    for e in fc.upcoming():
        b = band(fc, e)
        rows.append(
            {
                "Sprint": e.sprint.id,
                f"Forecast PLAN ({unit})": fmt(e.result.plan),
                t("conservative"): fmt(b.low if b else None),
                t("medium"): fmt(b.mid if b else None),
                t("optimistic"): fmt(b.high if b else None),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(
        t(
            (
                "Forecast with the lowest, median and highest normalized velocity of the last "
                "{window} sprints instead of the trend – shows how much planning can vary."
            ),
            window=window,
        )
    )

    st.subheader(t("When will it be done?"))
    share = data.team.forecast.roadmap_share
    with st.form("completion"):
        rest = st.number_input(
            t("Remaining amount ({unit})", unit=unit),
            min_value=0.0,
            value=None,
            step=1.0,
            key="rest",
            help=t("Work still open, e.g. the total of a topic."),
        )  # fmt: skip
        basis = st.radio(
            t("Available per sprint"),
            ["roadmap", "total"],
            format_func=lambda k: (
                t("Plannable share ({share})", share=pct(share))
                if k == "roadmap"
                else t("entire forecast")
            ),
            horizontal=True,
            key="basis",
        )
        project = st.number_input(
            t("Project share (%)"),
            min_value=1.0,
            max_value=100.0,
            value=100.0,
            step=5.0,
            key="project_share",
            help=t(
                "Which part of the capacity chosen above goes into this project – e.g. 50 "
                "if a second topic is worked on equally in parallel."
            ),
        )
        submitted = st.form_submit_button(t("Calculate"), type="primary")
    if submitted and rest:
        basis_share = share if basis == "roadmap" else 1.0
        used_share = basis_share * project / 100
        result = completion(data, fc.today, rest, used_share)
        if result is None:
            st.warning(t("Not enough history for a completion forecast."))
        else:
            # The value stays short ("later than 2027.21") so that it is not truncated; the
            # length of the simulation is shown below.
            later = t("later than {last}", last=result.sprints[-1] if result.sprints else "–")
            horizon = t("Simulation over {count} sprints", count=len(result.sprints))
            left, middle, right = st.columns(3)
            left.metric(
                t("per sprint for the project ({share} of the forecast)", share=pct(used_share)),
                f"≈ {fmt(result.per_sprint, 1)} {unit}",
                help=t("Median of the normalized velocity × typical capacity × share."),
            )
            frequency = t(
                (
                    "Model-dependent frequency in the simulation from {count} sprints of "
                    "history – not a commitment."
                ),
                count=result.samples,
            )
            for column, label, reached in (
                (middle, t("in 50 % of the simulations"), result.p50),
                (right, t("in 85 % of the simulations"), result.p85),
            ):
                column.metric(
                    label,
                    reached or later,
                    delta=None if reached else horizon,
                    delta_color="off",
                    delta_arrow="off",
                    help=frequency,
                )
            done_col = t("done by then")
            chart = pd.DataFrame({"Sprint": result.sprints, done_col: result.cumulative})
            # from the first sprint with a chance to the first with (almost) 100 %
            done = chart.index[chart[done_col] >= 0.999]
            chart = chart[chart[done_col] > 0]
            if len(done):
                chart = chart.loc[: done[0]]
            st.altair_chart(
                alt.Chart(chart)
                .mark_bar()
                .encode(
                    x=alt.X("Sprint:N", sort=list(chart["Sprint"])),
                    y=alt.Y(
                        f"{done_col}:Q",
                        axis=alt.Axis(format="%"),
                        title=t("Probability"),
                    ),
                    tooltip=["Sprint:N", alt.Tooltip(f"{done_col}:Q", format=".0%")],
                ),
                width="stretch",
            )
            caption = t(
                (
                    "Monte Carlo simulation ({runs} runs, sample: {samples} sprints) from the "
                    "next sprint: for each sprint a random normalized velocity of the last "
                    "sprints × capacity. The percentages are model-dependent frequencies, not "
                    "commitments."
                ),
                runs=f"{result.runs:,}",
                samples=result.samples,
            )
            if note := completion_note(result.samples):
                hint = window_hint(
                    data.team.forecast.window,
                    result.samples,
                    available_count(fc),
                    simulation=True,
                )
                st.warning(f"{note} {hint}".strip())
            if result.trend_capacity_sprints:
                listed = ", ".join(result.trend_capacity_sprints[:4])
                if len(result.trend_capacity_sprints) > 4:
                    listed += " …"
                caption += t(
                    " Calculated with Ø capacity because there is no people list: {sprints}.",
                    sprints=listed,
                )
            if not result.p85:
                caption += t(
                    (
                        " The simulation covers at most {count} sprints; the remaining amount "
                        "is too large for that or the share per sprint too small."
                    ),
                    count=len(result.sprints),
                )
            st.caption(caption)

    st.subheader(t("Focus factor"))
    st.metric(
        t("Ø focus factor (last {window} sprints)", window=window),
        fmt(average_focus_factor(fc), 2),
        help=t(
            "Velocity / capacity. The same quantity as the normalized velocity, just "
            "without the reference capacity (norm. velocity = focus factor × reference "
            "capacity). It depends on the estimation unit (with story points e.g. on the "
            "team's estimation scale) and is therefore not comparable between teams – the "
            "trend within one's own team is what counts. Literature values (0.6–0.8) "
            "usually refer to pure working time; if the capacity counts all attendance "
            "days, the values are lower."
        ),
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"Sprint": e.sprint.id, t("Focus factor"): fmt(focus_factor(e), 2)}
                for e in fc.history(window)
            ]
        ),
        hide_index=True,
    )

    st.subheader(t("Buffer for unplanned work"))
    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        st.info(t("Scope creep was not recorded recently – no recommendation possible."))
    else:
        text = t(
            (
                "Ø scope creep of the last {count} sprints: **{scope}** of the commitment = "
                "**{late}** of the Forecast PLAN · configured small-items share (relative to "
                "the Forecast PLAN): **{small}**"
            ),
            count=hint.samples,
            scope=pct(hint.average_scope_creep),
            late=pct(hint.average_late_share),
            small=pct(hint.configured_small_stuff),
        )
        if hint.buffer_too_small:
            st.warning(text + t(" – the buffer is smaller than the unplanned share."))
        elif hint.sufficient_data:
            st.success(text + t(" – fine."))
        else:
            st.info(text + t(" – too few values for a recommendation."))


def _prognosis_history(data: TeamData, sprints: list[Sprint], unit: str) -> None:
    """Previous forecasts of the open sprints from earlier pre-plannings."""
    if not any((recorded := data.sprint(sprint.id)) and recorded.prognoses for sprint in sprints):
        return
    details = st.toggle(t("All forecast details"), key="prognosis-details")
    rows = []
    for sprint in sprints:
        recorded = data.sprint(sprint.id)
        for p in recorded.prognoses if recorded else []:
            row = {
                t("Time"): f"{p.at:%d.%m.%Y %H:%M}",
                "Sprint": sprint.id,
                t("Comment"): p.comment or "",
            }
            if details:
                row |= {
                    f"Commitment ({unit})": fmt(p.forecast_ist, 2),
                    t("not finished"): fmt(p.not_done, 2),
                    t("additionally done"): fmt(p.additional_done, 2),
                }
            row |= {
                t("expected done"): fmt(p.expected_done, 2),
                t("Forecast PLAN {id}", id=p.target or "–"): fmt(p.plan),
            }
            rows.append(row)
    if rows:
        st.markdown(f"**{t('Previous forecasts')}**")
        st.dataframe(pd.DataFrame(rows[::-1]), hide_index=True)


def _available_text(d: Distribution, data: TeamData, unit: str) -> str:
    """Where the distributable amount comes from (Forecast PLAN or its plannable share)."""
    return _available_base(d, data, unit) + _frozen_note(d, unit)


def _available_base(d: Distribution, data: TeamData, unit: str) -> str:
    if d.plan is None:
        return t("No Forecast PLAN can be calculated for this sprint yet.")
    frozen = t(" (forecast at planning, frozen)") if d.plan_frozen else ""
    if d.basis is ProductBasis.ROADMAP:
        share = data.team.forecast.roadmap_share
        return t(
            (
                "Distributable = plannable share of the Forecast PLAN{frozen}: {plan} {unit} × "
                "{share} = {available} {unit}. The small-stuff share is not distributed across "
                'products (setting "Standard distribution per product from").'
            ),
            frozen=frozen,
            plan=fmt(d.plan, 2),
            unit=unit,
            share=pct(share),
            available=fmt(d.available, 2),
        )
    return t(
        "Distributable = Forecast PLAN{frozen}: {plan} {unit}.",
        frozen=frozen,
        plan=fmt(d.plan, 2),
        unit=unit,
    )


def _protocols(repo: Repository, data: TeamData, sprint_id: str, kind: str) -> None:
    """The minutes written on every save for one meeting of this sprint, including
    older ones and those renamed as obsolete."""
    found = [f for f in list_protocols(repo, data.team.key, sprint_id) if f[1] == kind]
    with st.expander(
        t("Minutes: {kind} ({count})", kind=kind_title(kind), count=len(found)),
        icon=":material/history:",
    ):
        if not found:
            st.caption(
                t("No minutes yet: they are written as soon as a planning step is saved.")
                if kind == PLANNING
                else t("No minutes yet: they are written when this meeting is saved.")
            )
            return
        labels = {
            path: f"{at:%d.%m.%Y %H:%M:%S}" + (t(" (obsolete)") if obsolete else "")
            for at, _, obsolete, path in found
        }
        chosen = st.selectbox(
            t("Current status"),
            list(labels),
            format_func=labels.__getitem__,
            key=f"protokoll-{kind}-{sprint_id}",
        )
        try:
            text = chosen.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            st.error(t("Minutes not readable: {reason}", reason=str(e)))
            return
        st.markdown(text)
        st.caption(t("File: `{path}`", path=chosen))


def page_preplanning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Board of the POs before Planning: for each product, what should go into the sprint."""
    st.header(t("PO pre-planning"))
    unit = data.team.unit.value
    if not data.products:
        st.info(
            t(
                "No products recorded yet. The PO pre-planning distributes the sprint "
                "amount across the products of the team."
            )
        )
        page_link("produktliste", t("Add products"))
        return
    sprint = sprint_select(data, fc, "vorplanung-sprint")
    entry = fc.entry(sprint.id) if sprint else None
    if sprint is None or entry is None:
        return
    _board_nav(data, sprint, "vorplanung")
    st.caption(
        t(
            "Before the planning, the POs enter how much they intend per product for the "
            "sprint. For comparison the **standard** is shown – the even distribution or "
            "the agreed share of the product."
        )
    )
    headline = st.container()
    assumed: dict[str, Assumption] = {}
    comment = ""
    if open_velocity_sprints(fc):
        with st.expander(_whatif_title(), icon=":material/science:"):
            _whatif_caption(
                t(
                    "This only applies to this view; **Save pre-planning** records the "
                    "assumption with the comment as a forecast. The velocity itself is "
                    "only recorded in the review."
                )
            )
            assumed = _whatif_inputs(fc, unit, "vorplanung-whatif")
            comment = (
                st.text_input(
                    t("Comment on the forecast"),
                    key=f"vorplanung-comment-{sprint.id}",
                    placeholder=t(
                        "Where does the assumption come from? e.g. forecast from the daily "
                        "on 16 Oct"
                    ),
                )
                if assumed
                else ""
            )
            _prognosis_history(data, list(open_velocity_sprints(fc)), unit)
    expected = dict(sprint.expected_absences)
    if data.people:
        with st.expander(t("Announced absences"), icon=":material/event_busy:"):
            st.caption(
                t(
                    "Absences already known or expected for this sprint. They are a "
                    "forecast for the POs and affect capacity and Forecast PLAN until the "
                    "absences are confirmed in the planning (where they are prefilled)."
                )
            )
            if absences_known(sprint):
                st.info(
                    t(
                        "The absences of this sprint are already confirmed – the announced "
                        "absences no longer have any effect."
                    )
                )
            probe = _base_sprint(data, sprint)
            probe.absences = dict(probe.expected_absences)
            edited_expected = st.data_editor(
                pd.DataFrame(absence_matrix(data.people, [probe])),
                column_config={
                    "id": None,
                    "Person": st.column_config.TextColumn(t("Person"), disabled=True),
                    probe.id: st.column_config.NumberColumn(
                        t("Announced absence (days)"),
                        min_value=0.0,
                        max_value=float(len(team_workdays(data.team, probe.start, probe.end))),
                        step=0.5,
                    ),
                },
                hide_index=True,
                key=f"vorplanung-expected-{sprint.id}",
                placeholder="",  # empty = person is not on the team in this sprint
            )
            [probe_after] = edit_absences(data.people, [probe], edited_expected.to_dict("records"))
            expected = dict(probe_after.absences)
    saved_expected = dict(sprint.expected_absences)
    fc_base = fc
    if expected != saved_expected:
        with_expected = _base_sprint(data, sprint)
        with_expected.expected_absences = expected
        fc_base = build_forecast(with_sprints(data, [with_expected]), fc.today)
        entry = fc_base.entry(sprint.id) or entry
    fc_view = whatif_forecast(fc_base, assumed) if assumed else fc_base
    shown = fc_view.entry(sprint.id) or entry
    shown_plan = shown.result.plan  # currently computed (with assumption, if entered)
    frozen_plan = sprint.forecast_plan  # frozen at Planning
    with headline:
        columns = st.columns(4 if frozen_plan is not None else 3)
        plan_col, capacity_col, trend_col = columns[0], columns[-2], columns[-1]
        delta = None
        if assumed and shown_plan is not None and entry.result.plan is not None:
            delta = t(
                "{diff} {unit} (without assumption {old} {unit})",
                diff=_signed(shown_plan - entry.result.plan),
                unit=unit,
                old=fmt(entry.result.plan),
            )
        plan_col.metric(
            t("Current forecast {id}", id=sprint.id),
            f"{fmt(shown_plan)} {unit}",
            delta=delta,
            delta_color="off",
            help=(_formula_help(fc_view, shown, "plan") + "\n\n" if shown_plan is not None else "")
            + t("Currently calculated."),
        )
        if frozen_plan is not None:
            columns[1].metric(
                t("Forecast at planning {id}", id=sprint.id),
                f"{fmt(frozen_plan)} {unit}",
                delta=None if shown_plan is None else _signed(shown_plan - frozen_plan),
                delta_color="off",
                help=t(
                    "Frozen at planning (basis of the distributable amount). The number "
                    "below is the difference of the current forecast to it."
                ),
            )
        # The source goes below the value (not inside it): otherwise the number is truncated.
        capacity_col.metric(
            t("Capacity (PT)"),
            fmt_capacity(shown.result.plan_capacity, shown.capacity_digits),
            delta=capacity_source_note(shown) or None,
            delta_color="off",
            delta_arrow="off",
            help=_formula_help(fc_view, shown, "capacity"),
        )
        trend_col.metric(t("norm. velocity trend"), fmt(shown.result.normalized_velocity.trend, 2))
        # The range is computed without the assumption (otherwise the assumed Velocity of the
        # current sprint would feed into it).
        base_shown = fc_base.entry(sprint.id) or shown
        if note := band_note(fc_base, base_shown, without_assumption=bool(assumed)):
            st.caption(note)
        _quote_note(fc_view, [shown])
    if assumed:
        if shown is not None and (plan_step := formula_step(fc_view, shown, "plan")):
            st.caption(
                t(
                    "Calculation: {calculation} · capacity {capacity} PT",
                    calculation=plan_step.calculation,
                    capacity=capacity_label(shown),
                )
            )
        if sprint.forecast_plan is not None:
            st.caption(
                t(
                    "The forecast at planning of this sprint is frozen – the assumption "
                    "does not change it."
                )
            )
    d = distribution(fc_view, fc_view.entry(sprint.id) or entry)
    rows = _product_editor(d, ["preplanned"], f"vorplanung-{sprint.id}", unit, PREPLANNING)
    if rows is None:
        return
    base = _base_sprint(data, sprint)
    after = apply_product_values(base, rows, ["preplanned"])
    after.expected_absences = expected
    fc_preview = _preview_forecast(data, fc_base, base, after)
    if assumed:
        fc_preview = whatif_forecast(fc_preview, assumed)
    d = distribution(fc_preview, fc_preview.entry(after.id) or entry)
    total = d.total("preplanned")
    left, middle, right = st.columns(3)
    left.metric(
        t("Distributable"), f"{fmt(d.available, 2)} {unit}", help=_available_text(d, data, unit)
    )
    middle.metric(t("Intended (Σ)"), f"{fmt(total, 2)} {unit}")
    st.caption(_available_text(d, data, unit))
    if total is not None and d.available is not None:
        rest = d.available - total
        right.metric(
            t("Still free") if rest >= 0 else t("Too much"),
            f"{fmt(abs(rest), 2)} {unit}",
            delta=None,
        )
    comparison = [
        {
            t("Product"): r.product.name,
            **({"PO": r.product.po or ""} if data.team.features.po else {}),
            t("Standard"): fmt(r.standard, 2),
            t("PO pre-planning"): fmt(r.preplanned, 2),
            t("Difference"): _signed(r.preplanned - r.standard)
            if r.preplanned is not None and r.standard is not None
            else "–",
        }
        for r in d.rows
        if r.active or r.preplanned is not None
    ]
    st.dataframe(pd.DataFrame(comparison), hide_index=True)
    if po_rows := (by_po(d) if data.team.features.po else []):
        st.markdown(f"**{t('Per PO')}**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "PO": po,
                        t("Standard"): fmt(totals["standard"], 2),
                        t("PO pre-planning"): fmt(totals["preplanned"], 2),
                    }
                    for po, totals in po_rows
                ]
            ),
            hide_index=True,
        )
    changed = after.products != base.products or bool(assumed) or expected != saved_expected
    if st.button(t("Save PO pre-planning"), type="primary", disabled=not changed):
        to_save = [after]
        if assumed:
            plan = fc_preview.entry(after.id).result.plan if fc_preview.entry(after.id) else None
            to_save = record_prognoses(data, after, assumed, plan, comment)
        now = datetime.now().replace(microsecond=0)
        absent = {pid: days for pid, days in expected.items() if days}
        names = {p.id: p.name for p in data.people}
        protocol = render_protocol(
            PREPLANNING,
            data.team.name or data.team.key,
            after.id,
            now=now,
            facts=[
                (t("Capacity (PT)"), fmt(shown.result.plan_capacity, 1)),
                (t("Current forecast ({unit})", unit=unit), fmt(shown_plan, 2)),
                (t("Distributable"), f"{fmt(d.available, 2)} {unit}"),
                (t("Intended (Σ)"), f"{fmt(total, 2)} {unit}"),
            ],
            d=d,
            comment=comment,
            notes=[
                (
                    t("Team assumptions"),
                    [
                        t(
                            (
                                "Sprint {id}: commitment {commitment} {unit}, expected not done "
                                "{not_done}, additionally done {extra} → expected done {done} "
                                "{unit}"
                            ),
                            id=sid,
                            commitment=fmt(a.forecast_ist, 2),
                            not_done=fmt(a.not_done, 2),
                            extra=fmt(a.additional_done, 2),
                            done=fmt(a.expected, 2),
                            unit=unit,
                        )
                        for sid, a in assumed.items()
                    ],
                ),
                (
                    t("Announced absences"),
                    [
                        f"{names.get(pid, pid)}: {fmt(days, 1)} {t('days')}"
                        for pid, days in absent.items()
                    ],
                ),
            ],
            show_po=data.team.features.po,
        )

        def write() -> list[Path]:
            return save_with_protocol(
                repo,
                data.team.key,
                after.id,
                PREPLANNING,
                protocol,
                datetime.now,
                to_save,
                lambda: save_sprints_together(repo, data.team.key, to_save),
            )  # minutes: not mentioned in the message

        if save(with_sprints(data, to_save), [f"{s.id}.yaml" for s in to_save], write, flash=True):
            st.rerun()  # the step bar above shows the saved state
    _protocols(repo, data, sprint.id, PREPLANNING)
    page_link("planning", t("Continue to planning"))


def page_tickets(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Ticket pre-planning (``features.tickets``); the page component is only loaded here."""
    from sprintforecast.web import tickets_view

    tickets_view.page(repo, data, fc)


def page_products(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Product distribution"))
    unit = data.team.unit.value
    if not data.products:
        st.info(
            t(
                "No products recorded yet. With products this page shows how the sprint "
                "amount is distributed across products: standard, PO pre-planning, "
                "planning and done."
            )
        )
        page_link("produktliste", t("Add products"))
        return
    sprint = sprint_select(data, fc, "products-sprint")
    if sprint is None:
        return
    entry = fc.entry(sprint.id)
    if entry is None:
        return
    st.caption(
        t(
            "Evaluation only: the values are not entered here but in the workflow – the "
            "**PO pre-planning** before the planning, **Planning** in sprint planning, "
            "**Done** in the review."
        )
    )
    links = st.columns(3)
    for col, key in zip(links, BOARDS, strict=True):
        with col:
            page_link(key, t("Change: {page}", page=t(PAGE_INFO[key][0])))
    d = distribution(fc, entry)
    if _product_table(d, unit):
        _production_hint(d, data, unit)
        if chart := _product_chart(d, unit, [m for m in MEASURES if m == "standard" or d.has(m)]):
            st.altair_chart(chart, width="stretch")
        if po_rows := (by_po(d) if data.team.features.po else []):
            st.markdown(f"**{t('Per PO')}**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "PO": po,
                            **{
                                measure_label(m): fmt(v, 2)
                                for m, v in totals.items()
                                if m == "standard" or d.has(m)
                            },
                        }
                        for po, totals in po_rows
                    ]
                ),
                hide_index=True,
            )

    st.subheader(t("History"))
    count = st.number_input(
        t("Number of sprints"), min_value=2, max_value=26, value=6, key="products-n"
    )
    entries = [e for e in fc.entries if e.sprint.start <= sprint.start][-int(count) :]
    chosen = st.radio(
        t("Metric"),
        ["done", "planned", "preplanned"],
        format_func=measure_label,
        horizontal=True,
        key="products-measure",
    )
    chart = _history_chart(fc, entries, chosen, unit)
    if chart is None:
        st.info(
            t(
                'No value "{measure}" recorded in these sprints yet.',
                measure=measure_label(chosen),
            )
        )
    else:
        st.altair_chart(chart, width="stretch")
    st.subheader(t("Balance against the standard distribution"))
    _balance_section(fc, entries, unit)


def page_product_list(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Products"))
    page_intro(
        t(
            "One row per product the team looks after, with period and optional PO. Never "
            "delete rows; end them with **until**."
        ),
        t(
            "**Product handed over:** set **until** instead of deleting, otherwise the "
            "values of past sprints are missing in the reports.  \n**New product:** add a "
            "row, **from** = first day looked after (empty = since always)."
        ),
        t("Hand over a product or add a new one"),
    )
    show_former = st.toggle(t("Show former"), value=False, key="show_former_products")
    rows, hidden = product_table(data.products, fc.today, show_former)
    if hidden:
        st.caption(t("{count} former product(s) hidden.", count=len(hidden)))
    frame = pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
    for col in ("from", "until"):
        frame[col] = pd.to_datetime(frame[col])
    frame["PO"] = frame["PO"].astype("string")
    frame["Anteil"] = frame["Anteil"].astype("float")
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,
            "Name": st.column_config.TextColumn(t("Name"), required=True),
            "PO": st.column_config.TextColumn("PO", help=t("Responsible product owner"))
            if data.team.features.po
            else None,
            "Anteil": st.column_config.NumberColumn(
                t("Share (%)"),
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                help=t(
                    "Agreed fixed share of the team capacity, e.g. 10. Empty = split "
                    "evenly across the rest."
                ),
            ),
            "from": st.column_config.DateColumn(
                t("from"), format="DD.MM.YYYY", help=t("Empty = always")
            ),
            "until": st.column_config.DateColumn(
                t("until"), format="DD.MM.YYYY", help=t("Empty = still handled")
            ),
        },
        num_rows="dynamic",
        hide_index=True,
        key=f"products-list-{data.team.key}-{show_former}",
        placeholder="",  # "Empty = always" etc.: empty cells stay empty, not "None"
    )
    result = products_from_table(edited.to_dict("records"), data.products, hidden)
    confirmed = True
    if result.deleted:
        st.warning(
            t(
                (
                    "Deleted: {names}.  \nOnly delete wrong entries. If the team hands over a "
                    "product, set **until** instead."
                ),
                names=", ".join(result.deleted),
            )
        )
        confirmed = st.checkbox(
            t("Yes, the rows were wrong entries"), key="confirm_delete_products"
        )
    if not st.button(t("Save products"), type="primary", disabled=not confirmed):
        return
    if result.errors:
        for e in result.errors:
            st.error(e)
        return
    after = copy.deepcopy(data)
    after.products = result.products
    save(
        after,
        ["products.yaml"],
        lambda: [repo.save_products(data.team.key, result.products)],
        block_on_all_errors=True,
    )


def page_people(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("People"))
    page_intro(
        t("One row per person and period in the team. Never delete rows; end them with **until**."),
        t(
            "**Leaving:** set **until** in the row. Deleting would change capacity and "
            "absences of past sprints.  \n**FTE change:** end the existing row with "
            "**until** and add a new row with the **same name** and the new FTE share.  "
            "\n**Part-time:** model it only once: full workweek with FTE 0.8 *or* "
            "four-day week with FTE 1."
        ),
        t("Record leaving or an FTE change"),
    )
    show_former = st.toggle(t("Show former"), value=False, key="show_former")
    rows, hidden = people_table(data.people, fc.today, show_former)
    if hidden:
        st.caption(t("{count} former person(s) hidden.", count=len(hidden)))
    frame = pd.DataFrame(rows, columns=PEOPLE_COLUMNS)
    for col in ("from", "until"):
        frame[col] = pd.to_datetime(frame[col])
    frame["Production access"] = frame["Production access"].astype(bool)
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,  # internal ID, assigned automatically
            "Name": st.column_config.TextColumn(t("Name"), required=True),
            "Country": st.column_config.SelectboxColumn(
                t("Country"),
                options=[TEAM_REGION, *countries()],
                default=TEAM_REGION,
                help=t("(Team) = team setting; different country for holidays and weekend"),
            ),
            "Work week": st.column_config.TextColumn(
                t("Work week"),
                help=t(
                    "Empty = as country/team. mon-fri, sun-thu, mon-sat or the working "
                    "days, e.g. mon,tue,wed,thu for a 4-day week"
                ),
            ),
            "State": st.column_config.SelectboxColumn(
                t("Region"),
                options=[
                    TEAM_REGION,
                    *sorted(
                        {
                            *subdivisions(data.team.capacity.country),
                            *(
                                c
                                for code in {p.country for p in data.people if p.country}
                                for c in subdivisions(code)
                            ),
                        }
                    ),
                ],
                default=TEAM_REGION,
                help=t("(Team) = team setting; state or province"),
            ),
            "from": st.column_config.DateColumn(
                t("from"), format="DD.MM.YYYY", required=True, default=fc.today
            ),
            "until": st.column_config.DateColumn(
                t("until"), format="DD.MM.YYYY", help=t("Empty = still in the team")
            ),
            "FTE": st.column_config.NumberColumn(
                "FTE",
                step=0.05,
                default=1.0,
                help=t("Share in the team, 1 = full time, 0 = no capacity (e.g. long absence)"),
            ),
            "Production access": st.column_config.CheckboxColumn(
                t("Production access"),
                default=False,
                help=t(
                    "May work on tickets that require production access. Applies to the "
                    "person, not to the single period."
                ),
            )
            if data.team.features.production
            else None,
        },
        num_rows="dynamic",
        hide_index=True,
        key=f"people-{data.team.key}-{show_former}",
        placeholder="",  # "Empty = still in the team" etc.: empty cells stay empty, not "None"
    )
    result = people_from_table(edited.to_dict("records"), data.people, hidden)
    confirmed = True
    if result.deleted:
        st.warning(
            t(
                (
                    "Deleted: {names}.  \nOnly delete rows that were **entered wrongly**. If "
                    "someone leaves the team, set **until** instead – otherwise "
                    "inconsistencies arise (e.g. absences for unknown people)."
                ),
                names=", ".join(result.deleted),
            )
        )
        confirmed = st.checkbox(t("Yes, the rows were wrong entries"), key="confirm_delete")
    for e in result.errors:
        st.error(e)
    if not st.button(
        t("Save people"), type="primary", disabled=not confirmed or bool(result.errors)
    ):
        return
    save(
        with_people(data, result.people),
        ["people.yaml"],
        lambda: [repo.save_people(data.team.key, result.people)],
        block_on_all_errors=True,
    )


def _setting_widget(setting: Setting, team: Team, key: str) -> str:
    """Shows the matching input field and returns the value as text for Setting.parse."""
    shown = setting.display(team)
    label, help = setting.title, setting.text
    match setting.kind:
        case Kind.TEXT:
            return st.text_input(label, shown, help=help, key=key)
        case Kind.CHOICE:
            choices = setting.options or {}
            options = ([""] if setting.optional else []) + list(choices)
            return st.selectbox(
                label,
                options,
                index=options.index(shown) if shown in options else 0,
                format_func=lambda k: f"{k} – {choices[k]}" if k else t("(not specified)"),
                help=help,
                key=key,
            )
        case Kind.DATE:
            value = st.date_input(label, setting.get(team), help=help, key=key, format="DD.MM.YYYY")
            return value.isoformat() if isinstance(value, date) else ""
        case Kind.INT:
            value = st.number_input(
                label,
                min_value=int(setting.minimum) if setting.minimum is not None else None,
                max_value=int(setting.maximum) if setting.maximum is not None else None,
                value=int(shown),
                step=1,
                help=help,
                key=key,
            )
            return str(value)
        case Kind.NUMBER | Kind.PERCENT:
            value = st.number_input(
                label,
                min_value=float(setting.minimum) if setting.minimum is not None else None,
                max_value=float(setting.maximum) if setting.maximum is not None else None,
                value=float(shown),
                step=setting.step or (0.5 if setting.kind is Kind.PERCENT else 1.0),
                help=help,
                key=key,
            )
            return str(value)
    raise AssertionError(setting.kind)


OVERHEAD_KEYS = ("capacity.overhead_share", "capacity.overhead_days")


def _sprint_workdays(team: Team, form_key: str) -> float:
    """Working days per sprint (the team's work week, from the sprint length): conversion
    between PD and %."""
    length = st.session_state.get(f"{form_key}-sprint.length_days", team.sprint.length_days)
    return max(float(length) * (7 - len(team_weekend(team))) / 7, 1.0)


def _overhead_widgets(team: Team, form_key: str) -> dict[str, str]:
    share = next(s for s in SETTINGS if s.key == OVERHEAD_KEYS[0])
    days = next(s for s in SETTINGS if s.key == OVERHEAD_KEYS[1])
    share_key, days_key = (f"{form_key}-{k}" for k in OVERHEAD_KEYS)
    if share_key not in st.session_state or days_key not in st.session_state:
        # Only one is set (e.g. from the file): derive the other from it.
        wd = _sprint_workdays(team, form_key)
        d = team.capacity.overhead_days or team.capacity.overhead_share * wd
        st.session_state[days_key] = round(d, 2)
        st.session_state[share_key] = round(d / wd * 100, 1)

    def from_days() -> None:
        wd = _sprint_workdays(team, form_key)
        st.session_state[share_key] = round(st.session_state[days_key] / wd * 100, 1)

    def from_share() -> None:
        wd = _sprint_workdays(team, form_key)
        st.session_state[days_key] = round(st.session_state[share_key] / 100 * wd, 2)

    left, right = st.columns(2)
    with left:
        share_value = st.number_input(
            share.title,
            min_value=float(share.minimum),
            max_value=float(share.maximum),
            step=0.5,
            help=share.text,
            key=share_key,
            on_change=from_share,
        )
    with right:
        days_value = st.number_input(
            days.title,
            min_value=float(days.minimum),
            max_value=float(days.maximum),
            step=days.step,
            help=days.text,
            key=days_key,
            on_change=from_days,
        )
    return {OVERHEAD_KEYS[0]: str(share_value), OVERHEAD_KEYS[1]: str(days_value)}


def _settings_form(
    team: Team, has_sprints: bool, form_key: str, submit: str, first_sprint: bool = False
) -> Team | None:
    """Form for all settings; returns the changed team after submitting. With
    ``first_sprint`` the first sprint is shown up front as its own section (new team)."""
    edited = copy.deepcopy(team)
    # The two Scrum deductions are the same value: outside the form so that they can sync
    # immediately (form fields only react on submit).
    raw = _overhead_widgets(team, form_key)
    settings = applicable(has_sprints)
    with st.form(form_key):
        if first_sprint:
            st.subheader(t("First sprint"))
            st.markdown(
                t(
                    "The sprint that is **running now or starts next**. Its ID and start "
                    "are where the count begins; the following sprints follow from it. If "
                    "the team has been working for a while, that is e.g. **2026.15** "
                    "rather than 2026.1."
                )
            )
            raw |= {
                k: _setting_widget(BY_KEY[k], team, f"{form_key}-{k}") for k in FIRST_SPRINT_KEYS
            }
            st.subheader(t("Further settings"))
            settings = [s for s in settings if s.key not in FIRST_SPRINT_KEYS]
        raw |= {
            s.key: _setting_widget(s, team, f"{form_key}-{s.key}")
            for s in settings
            if s.key not in OVERHEAD_KEYS
        }
        submitted = st.form_submit_button(submit, type="primary")
    if not submitted:
        return None
    errors = []
    for s in applicable(has_sprints):
        try:
            value = s.parse(raw[s.key])
            if value is None and s.only_without_sprints:
                raise ValueError(t("Please enter a value."))
            s.set(edited, value)
        except ValueError as e:
            errors.append(f"{s.title}: {e}")
    for e in errors:
        st.error(e)
    return None if errors else edited


def page_settings(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Settings {team}", team=data.team.name))
    edited = _settings_form(data.team, bool(data.sprints), f"settings-{data.team.key}", t("Save"))
    if data.sprints:
        _rename_sprints_section(repo, data, fc)
    _excel_import_section(repo, data)
    if edited is None:
        return
    diff = changes(data.team, edited)
    if not diff:
        st.info(t("No changes."))
        return
    st.dataframe(
        pd.DataFrame(
            [
                {t("Setting"): s.title, t("before"): old or "–", t("new"): new or "–"}
                for s, old, new in diff
            ]
        ),
        hide_index=True,
    )
    if any(s.retroactive for s, _, _ in diff):
        st.warning(t("At least one change applies retroactively to all calculated values."))
    after = copy.deepcopy(data)
    after.team = edited
    save(
        after,
        ["team.yaml"],
        lambda: [repo.save_team(edited)],
    )


MAX_IMPORT_ROWS = 200


def _excel_import_section(repo: Repository, data: TeamData) -> None:
    """Excel workbook from the Excel export: preview of what would change, written on confirm."""
    from sprintforecast.excel import ExcelUnavailable
    from sprintforecast.excel_import import apply_import, plan_import, read_workbook_keyed

    key = data.team.key
    counter = f"excel-import-{key}-n"
    st.subheader(t("Import from Excel"))
    st.markdown(
        t(
            'Reads a workbook from the Excel export (Forecast page, "Create Excel '
            'list"). It first shows what would change; nothing is written until you '
            "confirm."
        )
    )
    upload = st.file_uploader(
        t("Excel file"),
        type=["xlsx"],
        key=f"excel-import-{key}-file-{st.session_state.get(counter, 0)}",
    )
    if upload is None:
        return
    # The upload is parsed once per file, not on every rerun (each click reruns the page).
    parsed_key = f"excel-import-{key}-parsed"
    cached = st.session_state.get(parsed_key)
    try:
        if cached is None or cached[0] != upload.file_id:
            cached = (upload.file_id, *read_workbook_keyed(upload.getvalue(), key))
            st.session_state[parsed_key] = cached
        plan = plan_import(repo, cached[1], today())
    except ExcelUnavailable as e:
        st.warning(str(e))
        return
    except DataError as e:
        st.error(str(e))
        return
    if cached[2] is None:
        st.warning(
            t(
                (
                    "The workbook names no team (older Excel export); it is not checked "
                    "whether it belongs to {team}."
                ),
                team=repr(key),
            )
        )
    if not plan.changes:
        st.info(t("No changes compared to the existing files."))
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    t("File"): c.file,
                    t("Value"): c.path,
                    t("before"): "–" if c.old is None else str(c.old),
                    t("new"): "–" if c.new is None else str(c.new),
                }
                for c in plan.changes[:MAX_IMPORT_ROWS]
            ]
        ),
        hide_index=True,
    )
    if len(plan.changes) > MAX_IMPORT_ROWS:
        st.caption(t("… and {count} more changes", count=len(plan.changes) - MAX_IMPORT_ROWS))
    for name in plan.untouched:
        st.caption(t("Not in the workbook, stays unchanged: {file}", file=name))
    if not st.button(t("Apply changes"), type="primary", key=f"excel-import-{key}-apply"):
        return
    try:
        paths = apply_import(repo, plan)
    except DataError as e:
        st.error(str(e))
        return
    except OSError as e:  # Files are written one after another: some may already be in place
        st.error(t("Not completely saved: {reason}", reason=e.strerror or e))
        return
    st.session_state["flash"] = [
        ("success", _saved_text(", ".join(p.name for p in paths), _next_step()))
    ]
    # The settings form should show the imported values, not the old ones.
    for name in [n for n in st.session_state if str(n).startswith(f"settings-{key}")]:
        del st.session_state[name]
    st.session_state[counter] = st.session_state.get(counter, 0) + 1  # clears the selection
    st.rerun()


def _rename_sprints_section(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Change sprint IDs afterwards (once sprint files exist, this replaces the
    "ID of the first sprint" setting)."""
    from sprintforecast.renaming import apply_renames, plan_renames

    st.subheader(t("Change sprint IDs"))
    st.markdown(
        t(
            "A sprint gets a new ID, e.g. **2026.15** instead of 2026.1; the saved sprints "
            "after it count on from there. Sprint files and minutes are renamed, their "
            "contents stay."
        )
    )
    ids = [s.id for s in data.sprints]
    # Preselection: the current sprint, otherwise the next saved one (finally: the last one).
    current = next((s.id for s in data.sprints if s.end > fc.today), ids[-1])
    left, right = st.columns(2)
    with left:
        chosen = st.selectbox(
            t("Sprint"), ids, index=ids.index(current), key=f"rename-{data.team.key}-sprint"
        )
    with right:
        new_id = st.text_input(
            t("New ID"),
            help=t("E.g. 2026.15 with numbering per year, 15 with sequential numbering."),
            key=f"rename-{data.team.key}-new",
        ).strip()
    renames: list[Any] = []
    if new_id:
        try:
            renames = plan_renames(data, chosen, new_id)
        except DataError as e:
            st.error(str(e))
            return
        if not renames:
            st.info(t("Nothing to change: sprint {id} already has that ID.", id=chosen))
            return
        st.dataframe(
            pd.DataFrame([{t("before"): r.old, t("new"): r.new} for r in renames]),
            hide_index=True,
        )
    if st.button(t("Change sprint IDs"), type="primary", disabled=not renames):
        try:
            applied = apply_renames(repo, data, renames)
        except DataError as e:
            st.error(str(e))
            return
        except OSError as e:  # everything reset; state the reason instead of a traceback
            st.error(t("Not saved: {reason}", reason=e.strerror or e))
            return
        st.session_state["flash"] = [
            ("success", _saved_text(", ".join(p.name for p in applied.files), _next_step()))
        ]
        for suffix in ("new", "sprint"):
            st.session_state.pop(f"rename-{data.team.key}-{suffix}", None)
        st.rerun()


def page_new_team(repo: Repository) -> None:
    st.header(t("Create new team"))
    page_intro(
        t(
            "Enter a short name, then the **first sprint**: the one that is running now or "
            "starts next. Everything else can be changed at any time under **Settings**."
        ),
        t(
            "**First sprint:** start and ID of the sprint that is running now or starts "
            "next (e.g. 2026.15, not 2026.1, if the team has been working for a while). "
            "The following sprints count on from there. A wrong ID can be corrected later "
            "under **Settings** (Change sprint IDs).  \n**Optional areas:** **product "
            "distribution**, **PO assignment** and **production access** are off at first; "
            "what they do is explained at each field."
        ),
        t("First sprint, optional areas"),
    )
    key = (
        st.text_input(t("Team key (folder name)"), help=t("Lower case, e.g. team-a"))
        .strip()
        .lower()
    )
    if not key:
        return
    if clash := repo.clashing_team(key):
        if clash == key:
            st.error(t("Team {team} already exists.", team=repr(key)))
        else:
            st.error(
                t(
                    (
                        "Team {team} already exists (as {existing}; Windows and macOS do not "
                        "distinguish folders by upper and lower case)."
                    ),
                    team=repr(key),
                    existing=repr(clash),
                )
            )
        return
    if problem := team_key_problem(key):
        st.error(problem)
        return
    team = Team(key=key, name=key.upper())
    team.sprint.first_start = today()
    team.sprint.first_id = None  # no default: only the team knows the ID of the current sprint
    team.sprint.numbering = Numbering.YEARLY
    edited = _settings_form(team, False, f"new-{key}", t("Create team"), first_sprint=True)
    if edited is None:
        return
    if save(
        TeamData(team=edited),
        ["team.yaml"],
        lambda: [repo.save_team(edited), repo.save_people(key, [])],
    ):
        st.session_state["selected_team"] = key
        page_link("personen", t("Next: add people"))


def needs_setup(root: Path) -> bool:
    """No data folder found: neither teams nor a Git repository (and "Use without Git" not
    explicitly chosen)."""
    return teams_dir(root) is None and git_root(root) is None and not is_without_git(root)


# State kept when switching the data folder; everything else (form inputs, team choice,
# pending tags, Git messages) belongs to the old folder and is discarded.
_SWITCH_KEEP = {
    "language", "flash", "restarting", "update-started", "manual-check", "active-data-dir",
    "folder-state",
}  # fmt: skip
# State that belongs to a folder and is back when switching back.
_PER_FOLDER = ("pending_tags", "commit_message", "commit_message_auto", "use_tags")


def _use_data_dir(path: Path) -> str | None:
    """Switch the data folder: remember it, clear the caches (teams, Git state) and
    discard old form states so that nothing from the previous folder ends up in the new one.
    If the settings cannot be saved, the switch does not happen at all; the message
    (with next step) is returned."""
    try:
        save_data_dir(path)
    except SettingsError as e:
        return _settings_problem(e, t("The data folder was not switched."))
    folders = st.session_state.setdefault("folder-state", {})
    folders[str(data_dir().resolve())] = {
        name: copy.deepcopy(st.session_state[name])
        for name in _PER_FOLDER
        if name in st.session_state
    }
    clear_team_cache()
    # Only the default for new sessions; this session manages its own folder.
    os.environ[DATA_ENV] = str(path.resolve())
    for name in list(st.session_state.keys()):
        if name not in _SWITCH_KEEP:
            del st.session_state[name]
    st.session_state[DATA_DIR_KEY] = str(path.resolve())
    st.session_state.update(copy.deepcopy(folders.get(str(path.resolve()), {})))
    st.session_state["flash"] = [("success", t("Data folder: `{path}`", path=path.resolve()))]
    return None


def _switch_clicked(target: Path) -> None:
    if not target.is_dir():  # vanished in the meantime (the display is cached briefly)
        st.session_state.setdefault("flash", []).append(
            ("error", t("Folder not found: {path}", path=target))
        )
        _DIR_CHECKED.pop(target, None)
        return
    if problem := _use_data_dir(target):
        st.session_state.setdefault("flash", []).append(("error", problem))


def _forget_clicked(target: Path) -> None:
    try:
        forget_data_dir(target)
    except SettingsError as e:
        st.session_state.setdefault("flash", []).append(
            ("error", _settings_problem(e, t("The folder was not removed from the list.")))
        )


# Whether a recently used folder still exists is remembered briefly: the list is drawn on every
# run, and a dead network drive path would otherwise slow things down each time.
_DIR_CHECK_SECONDS = 30.0
_DIR_CHECKED: dict[Path, tuple[float, bool]] = {}


def _dir_exists(path: Path) -> bool:
    now = time.monotonic()
    known = _DIR_CHECKED.get(path)
    if known is not None and now - known[0] < _DIR_CHECK_SECONDS:
        return known[1]
    found = path.is_dir()
    _DIR_CHECKED[path] = (now, found)
    return found


def _recent_label(path: Path) -> str:
    return f"{path.name or path}  ({path})" + ("" if _dir_exists(path) else t(" – not found"))


def _open_changes(repo: Repository) -> int | None:
    """Number of open changes; ``None`` if Git cannot provide it."""
    try:
        return len(cached_pending_changes(repo.root))
    except GitError:
        return None


def _switch_hint(repo: Repository) -> str:
    count = _open_changes(repo)
    head = t(
        "Switching discards unsaved input in forms; pending tags and the commit message "
        "are kept for the folder."
    )
    tail = (
        t("Open changes in the previous folder ({count}) are kept there.", count=count)
        if count is not None
        else t("Open changes in the previous folder are kept there.")
    )
    return f"{head} {tail}"


def _recent_dirs(repo: Repository) -> list[Path]:
    """Recently used data folders without the active one (resolved paths are remembered)."""
    current = resolved_path(repo.root)
    return [p for p in recent_data_dirs() if resolved_path(p) != current]


def _switch_panel(repo: Repository) -> None:
    """Switcher between the recently used data folders (sidebar)."""
    options = _recent_dirs(repo)
    if not options:
        return
    with st.expander(t("Switch data folder"), icon=":material/folder_open:"):
        target = st.selectbox(
            t("Recently used"), options, format_func=_recent_label, key="switch-target"
        )
        st.caption(_switch_hint(repo))
        st.button(
            t("Switch"),
            key="switch-go",
            on_click=_switch_clicked,
            args=(target,),
            disabled=not _dir_exists(target),
        )


def _active_repo_caption(repo: Repository) -> None:
    """Active repository (folder and branch), permanently visible."""
    branch = ""
    if git_available() and git_root(repo.root) is not None:
        try:
            current = cached_sync_state(repo.root)
        except GitError:
            current = None
        if current is not None:
            branch = current.branch or t("no branch")
    # With the parent folder: in the recommended layout the data folder is always called "teams".
    root = repo.root.resolve()
    shown = "/".join(p for p in (root.parent.name, root.name) if p) or str(root)
    st.markdown(
        f"**{t('Data folder')}:** `{shown}`"
        + (f" · {t('Branch')} {md_code(branch)}" if branch else "")
    )


def _browse(key: str) -> None:
    """System folder picker (in its own process, since Tk needs the main thread)."""
    title = t("Choose data folder").replace("'", "")
    script = (
        "import tkinter, tkinter.filedialog as f; r = tkinter.Tk(); r.withdraw(); "
        f"r.attributes('-topmost', True); print(f.askdirectory(title='{title}'))"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=600,
            **NO_WINDOW,
        )
    except OSError, subprocess.TimeoutExpired:
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        st.session_state[key] = out.stdout.strip()
    elif out is None or out.returncode != 0:
        st.session_state["browse-error"] = True


def _path_input(label: str, key: str, default: str) -> Path | None:
    """Path field with "Browse …". ``None`` if the field is empty or a user shorthand
    (``~``, ``~name``) cannot be resolved because the user folder is unknown: the buttons
    stay disabled then."""
    st.session_state.setdefault(key, default)
    left, right = st.columns([5, 1], vertical_alignment="bottom")
    raw = left.text_input(label, key=key)
    right.button(t("Browse …"), key=f"{key}-browse", on_click=_browse, args=(key,))
    if st.session_state.pop("browse-error", False):
        st.caption(t("No folder dialog available – please type the path."))
    if not raw.strip():  # otherwise "." (the server's working directory) would be meant
        return None
    try:
        return Path(raw.strip()).expanduser()
    except RuntimeError:
        st.error(
            t(
                (
                    "Home folder unknown: {path} cannot be resolved. Please type the full path "
                    "without “~”."
                ),
                path=md_code(raw.strip()),
            )
        )
        return None


# --- Set up the server (remote) -------------------------------------------------------------
# All keys start with ``git-remote-``: they survive stale inputs (``_discard_stale_inputs``),
# and switching the data folder discards them (``_use_data_dir``).


def _remote_url_changed() -> None:
    """Callback of the address field: an address with credentials never stays. The field is
    cleared; the message follows in the next run, without repeating the input."""
    if has_credentials(st.session_state.get("git-remote-url", "")):
        st.session_state["git-remote-url"] = ""
        st.session_state["git-remote-rejected"] = True


def _remote_status(info: RemoteInfo, merge_open: bool) -> None:
    """The configured server (without credentials) and reasons that block changing it."""
    # Names and addresses come from the configuration (legacy, foreign hand): always as code.
    if info.name is None:
        st.info(
            t(
                "This data folder has no server yet. As long as none is entered, all "
                "changes stay on this computer. Anyone joining an existing team chooses "
                "“Clone repository” further down instead of entering an address here."
            )
        )
    else:
        st.markdown(t("Server {name}: {url}", name=md_code(info.name), url=md_code(info.url)))
    if info.others:
        st.caption(
            t(
                "Other servers (not changed): {names}",
                names=", ".join(md_code(name) for name in info.others),
            )
        )
    if info.has_secret:
        st.warning(
            t(
                "The saved address contains credentials. They are not shown here. Saving a "
                "new address replaces them; in future please use the login service of the "
                "computer."
            )
        )
    if info.special:
        st.warning(str(remote_special_error()))
    if merge_open:
        st.warning(t("A merge is incomplete. The server cannot be changed while it is open."))


def _remote_failed(root: Path, address: RemoteAddress, error: GitError) -> None:
    """Shows why checking or saving failed and, in two cases, offers to save anyway: server not
    reachable and branch missing. The offer (folder, address, kind) is the only state of the
    form; it never contains the input, only the checked address."""
    offer = {"root": str(root), "url": address.url}
    if isinstance(error, NewBranchError):
        st.session_state["git-remote-offer"] = offer | {
            "kind": "new_branch",
            # Branch names from the server: as code, never as Markdown
            "text": error.render(md_code),
        }
        return  # the offer shows the message
    _show_problem(error)
    if error.kind == "offline":
        st.session_state["git-remote-offer"] = offer | {"kind": "offline"}


def _remote_check(root: Path, address: RemoteAddress, insecure: bool) -> None:
    """The "Check connection" action: asks the server for its branches, changes nothing. The
    network is only touched here, on click."""
    try:
        with st.spinner(
            t("Checking the connection … If a login window appears, please log in there.")
        ):
            checked = check_remote(root, address.url, allow_insecure=insecure)
    except GitError as e:
        _remote_failed(root, address, e)
        return
    st.success(t("Connection established."))
    if checked.empty:
        st.info(
            t(
                "The server is reachable but has no branches yet (new, empty repository). "
                "The first “Save and share” uploads the data. For a web address it can "
                "also mean that it does not point to a Git repository."
            )
        )
        return
    # The names come from the server and can contain anything (e.g. a web address that Markdown
    # would turn into a link): output as code. Only the display is truncated.
    names = ", ".join(md_code(head) for head in checked.heads[:5])
    st.caption(
        t(
            "Branches on the server: {names}",
            names=names + (", …" if len(checked.heads) > 5 else ""),
        )
    )
    if checked.branch_missing:
        missing = new_branch_error(checked.branch or "", checked.heads, checked.unborn)
        st.session_state["git-remote-offer"] = {
            "root": str(root),
            "url": address.url,
            "kind": "new_branch",
            "text": missing.render(md_code),
        }


def _remote_save(root: Path, address: RemoteAddress, insecure: bool, **confirmed: bool) -> None:
    """The "Save" action: the backend checks again and saves only after the check passes (or
    with the explicit confirmation in ``confirmed``). On success the next run redraws
    everything (sidebar, empty field)."""
    try:
        with st.spinner(
            t("Checking the connection … If a login window appears, please log in there.")
        ):
            saved = set_remote(root, address.url, allow_insecure=insecure, **confirmed)
    except GitError as e:
        _remote_failed(root, address, e)
        return
    st.session_state.pop("git-remote-offer", None)
    st.session_state["git-remote-reset"] = True
    if saved.verified:
        flash = (
            "success",
            t(
                "Server saved: {url}. “Save and share” synchronises the data.",
                url=md_code(saved.url),
            ),
        )
    else:
        flash = (
            "warning",
            t(
                "Server saved but not checked: {url}. The address is checked on the next share.",
                url=md_code(saved.url),
            ),
        )
    st.session_state["flash"] = [flash]
    st.rerun()


def _remote_offer(root: Path, address: RemoteAddress | None, insecure: bool, locked: bool) -> None:
    """The offer after "Server not reachable" or "Branch missing on the server": save anyway
    only with explicit confirmation. It only applies to the same folder and the same address."""
    offer = st.session_state.get("git-remote-offer")
    if not offer:
        return
    if address is None or offer["root"] != str(root) or offer["url"] != address.url:
        st.session_state.pop("git-remote-offer", None)
        return
    if offer["kind"] == "offline":
        st.warning(
            t(
                "The server is not reachable right now. The address can still be saved "
                "(e.g. if the VPN is off); it is then checked on the next share."
            )
        )
        label, key, confirmed = t("Save anyway"), "git-remote-offline-save", "allow_offline"
    else:
        st.warning(f"**{git_title('new_branch')}**  \n{offer['text']}")
        label = t("Yes, this is the right data repository")
        key, confirmed = "git-remote-branch-save", "accept_new_branch"
    if st.button(label, key=key, disabled=locked):
        st.session_state.pop("git-remote-offer", None)
        _remote_save(root, address, insecure, **{confirmed: True})


def _remote_section(repo: Repository) -> None:
    """Show, check and change the server (remote) of the data folder. Draws nothing without Git,
    without a repository or when Git does not provide the state (the other hints suffice then).
    The root is bound in this run; callbacks never read the data folder."""
    if not git_available():
        return
    root = git_root(repo.root)
    if root is None:
        return
    try:
        info = cached_remote_info(root)
    except GitError:
        return
    merge_open = _merge_open(repo)
    st.subheader(t("Server (remote)"))
    _remote_status(info, merge_open)
    if st.session_state.pop("git-remote-reset", False):
        # before the field; afterwards it would not be allowed
        st.session_state["git-remote-url"] = ""
    raw = st.text_input(
        t("New server address") if info.name else t("Server address"),
        key="git-remote-url",
        on_change=_remote_url_changed,
        placeholder="https://git.example.com/team/sprint-daten.git",
        help=t(
            "Allowed are https://…, ssh://…, git@server:path and a complete folder path. "
            "User name, password and token do not belong in the address. The app does not "
            "sign in by itself: the computer's credential service handles the login; if it "
            "is missing, the app explains the next step (depending on the operating "
            "system)."
        ),
    )
    if st.session_state.pop("git-remote-rejected", False):
        _show_problem(secret_in_url_error())
        st.caption(
            t(
                "The input was discarded and the field cleared. Please enter the address "
                "again without user name, password, token and parameters (everything from "
                "“?”)."
            )
        )
    insecure = False
    if raw.strip().lower().startswith("http://"):
        insecure = st.checkbox(
            t("Use the unencrypted connection anyway"), key="git-remote-insecure"
        )
    address = None
    if raw.strip():
        try:
            address = parse_remote_url(raw, allow_insecure=insecure)
        except GitError as e:
            _show_problem(e)
    locked = merge_open or bool(info.special)
    # Both buttons belong together: side by side, left-aligned, only as wide as their text.
    with st.container(horizontal=True):
        check_clicked = st.button(
            t("Check connection"), key="git-remote-check", disabled=address is None
        )
        save_clicked = st.button(
            t("Save"),
            type="primary",
            key="git-remote-save",
            disabled=address is None or locked,
        )
    if address is not None and (check_clicked or save_clicked):
        st.session_state.pop("git-remote-offer", None)
        if save_clicked:
            _remote_save(root, address, insecure)
        else:
            _remote_check(root, address, insecure)
    _remote_offer(root, address, insecure, locked)
    if info.name:
        _share_mode_setting(root)
        _signin_section(root, info)


def _signin_section(root: Path, info: RemoteInfo) -> None:
    """Geführte Token-Anmeldung für https-Server. Die App reicht den Token nur an den
    Anmeldedienst von Git weiter (``git credential approve``), speichert und zeigt ihn nie."""
    if not is_https(info.url):
        return
    if st.session_state.pop("signin-reset", False):
        st.session_state["signin-token"] = ""  # vor dem Feld; danach wäre es nicht erlaubt
    st.subheader(t("Set up sign-in"))
    shown = st.session_state.pop("signin-result", None)
    if shown is not None:
        kind, content = shown
        if kind == "error":
            _show_problem(content, interactive=False)
        else:
            st.success(content)
    state = helper_state(root)
    helper = suggested_helper()
    if state == "plain":
        st.warning(
            t(
                "Git stores sign-ins here in plain text (`credential.helper store`). The "
                "app hands no token to it. Please use a credential helper of the computer "
                "and remove `store` from the Git setting."
            )
        )
    elif state == "none":
        if helper:
            st.info(
                t(
                    (
                        "No Git credential helper is configured on this computer yet. The app "
                        "can switch on “{name}” for your user account (`git config --global "
                        "credential.helper {name}`); the repository stays unchanged."
                    ),
                    name=helper,
                )
            )
            if st.button(
                t("Switch on credential helper “{name}”", name=helper), key="signin-helper"
            ):
                try:
                    enable_helper(helper)
                except GitError as e:
                    st.session_state["signin-result"] = ("error", e)
                else:
                    invalidate_status()
                    st.session_state["signin-result"] = (
                        "ok",
                        t("Credential helper “{name}” is switched on.", name=helper),
                    )
                st.rerun()
        else:
            st.info(
                t(
                    "There is no secure credential helper on this computer that the app "
                    "could switch on. `gh auth setup-git` (GitHub CLI) or a credential "
                    "helper of your distribution (e.g. `git-credential-libsecret`) can set "
                    "one up; then enter the token here."
                )
            )
    guide = host_guide(host_kind(root))
    st.markdown(guide.steps)
    can_store = state == "ok"
    if guide.username and "signin-user" not in st.session_state:
        st.session_state["signin-user"] = guide.username
    with st.form("signin-form", clear_on_submit=True, border=False):
        user = st.text_input(t("User name"), key="signin-user")
        token = st.text_input(
            t("Access token"),
            type="password",
            key="signin-token",
            autocomplete="off",
            help=t(
                "The token goes only to the Git credential helper. The app does not store "
                "it and never shows it again."
            ),
        )
        submitted = st.form_submit_button(
            t("Save and check token"), type="primary", disabled=not can_store
        )
    if submitted:
        try:
            store_token(root, info.url, user, token)
            try:
                with st.spinner(t("Checking the sign-in …")):
                    verify(root, info.url)
            except GitError as e:
                if e.kind == "auth":  # nur ein abgelehnter Token wird entfernt (genau dieser)
                    with contextlib.suppress(GitError):
                        forget_token(root, info.url, user, token)
                raise
        except GitError as e:
            st.session_state["signin-result"] = ("error", e)
        else:
            st.session_state["signin-result"] = (
                "ok",
                t("Signed in: the server accepted the token."),
            )
        invalidate_status()
        st.session_state["signin-reset"] = True
        st.rerun()
    confirmed = can_store and st.checkbox(
        t("Delete all stored sign-ins for this server (also for other repositories)"),
        key="signin-forget-ok",
    )
    if confirmed and st.button(t("Delete stored sign-in"), key="signin-forget"):
        try:
            forget_token(root, info.url)
        except GitError as e:
            st.session_state["signin-result"] = ("error", e)
        else:
            st.session_state["signin-result"] = (
                "ok",
                t("The stored sign-in for this server was deleted."),
            )
        st.rerun()


def _attributes_applied(data: Path) -> None:
    try:
        apply_attributes(data)
    except (GitError, OSError, ValueError) as e:  # ValueError: not a UTF-8 file
        st.session_state["commit_error"] = e if isinstance(e, GitError) else folder_problem(data, e)
        return
    st.session_state["flash"] = [
        (
            "success",
            t(
                "`.gitattributes` created. The change is listed among the open changes; "
                "“Save and share” takes it the usual way."
            ),
        )
    ]


def _attributes_section(repo: Repository) -> None:
    """Offer of a ``.gitattributes`` (YAML and reports with LF) for an existing data repository,
    with a preview of the files that change. Written only on a click, and then only to the
    working folder: committing and sharing go the usual way through “Save and share” (as a merge
    request if configured)."""
    try:
        offer = attributes_offer(repo.root)
    except GitError, OSError:
        return
    if offer is None:
        return
    st.subheader(t("Set line endings"))
    st.markdown(
        t(
            "This data folder does not say that YAML files and reports are always stored with LF. "
            "Without it, the first save on a machine with `core.autocrlf` (Windows) may rewrite "
            "every line ending and add noise to the history. This creates the file {file} with "
            "these lines:",
            file=md_code(offer.file.name),
        )
    )
    st.code("\n".join(offer.rules), language=None)
    if offer.affected:
        st.warning(
            t(
                "Affected ({count}): these tracked files are stored with CRLF in the repository "
                "and are converted to LF on the next save (a one-time, purely technical change "
                "of the line endings):",
                count=len(offer.affected),
            )
        )
        st.dataframe(pd.DataFrame({t("File"): list(offer.affected)}), hide_index=True)
    else:
        st.caption(t("No existing file changes because of this."))
    st.button(
        t("Create `.gitattributes`"),
        key="attributes-apply",
        on_click=_attributes_applied,
        args=(repo.root,),
    )


def _share_mode_changed(root: Path) -> None:
    mode = SHARE_MERGE_REQUEST if st.session_state.get("git-share-mr") else SHARE_DIRECT
    try:
        set_share_mode(root, mode)
    except GitError as e:
        st.session_state["commit_error"] = e


def _HOST_LABELS() -> dict[str, str]:
    return {
        "": t("Detect automatically"),
        HOST_GITLAB: "GitLab",
        HOST_GITHUB: "GitHub",
        HOST_FORGEJO: "Forgejo / Gitea / Codeberg",
        HOST_GENERIC: t("Other server"),
    }


def _host_changed(root: Path) -> None:
    try:
        set_host(root, st.session_state.get("git-host") or None)
    except GitError as e:
        st.session_state["commit_error"] = e


def _auto_merge_changed(root: Path) -> None:
    try:
        set_auto_merge(root, bool(st.session_state.get("git-auto-merge")))
    except GitError as e:
        st.session_state["commit_error"] = e


def _share_mode_setting(root: Path) -> None:
    """Share via merge request instead of directly to the main branch (e.g. GitLab with a
    protected ``main``). Applies to this data repository on this machine."""
    try:
        current = share_mode(root) == SHARE_MERGE_REQUEST
    except GitError:
        return
    st.session_state["git-share-mr"] = current
    st.checkbox(
        t("Share via merge request"),
        key="git-share-mr",
        on_change=_share_mode_changed,
        args=(root,),
        help=t(
            "“Save and share” then uploads to a branch of your own and creates a "
            "merge/pull request there or updates it (depending on the server, no access "
            "token needed). The main branch stays untouched; “Pull from server” fetches "
            "the others' state once the merge request is merged."
        ),
    )
    if not current:
        return
    try:
        chosen = host_setting(root)
        host = host_kind(root)
        detected = detected_host(root)
        st.session_state["git-auto-merge"] = auto_merge(root)
    except GitError:
        return
    labels = _HOST_LABELS()
    st.session_state["git-host"] = chosen or ""
    st.selectbox(
        t("Kind of server"),
        list(labels),
        format_func=lambda key: (
            labels[key] if key else t("Detect automatically ({host})", host=labels[detected])
        ),
        key="git-host",
        on_change=_host_changed,
        args=(root,),
        help=t(
            "Decides how the merge/pull request is created. GitLab: push options, "
            "including auto-merge. Forgejo/Gitea/Codeberg: AGit flow (push to “refs/for”). "
            "GitHub: the app holds no access token; it uploads the branch and shows the "
            "link where you open the pull request. Other servers: the branch is uploaded "
            "and you open the merge request there."
        ),
    )
    if host in (HOST_GITLAB, HOST_GENERIC):
        st.toggle(
            t("Merge automatically when the pipeline is green"),
            key="git-auto-merge",
            on_change=_auto_merge_changed,
            args=(root,),
            help=t(
                "Sets the GitLab push option “merge when pipeline succeeds”: GitLab merges "
                "once the pipeline (and any required approvals) have passed; depending on "
                "the version a project without a pipeline must be merged by hand. Every "
                "share switches auto-merge on again; switch it off here to merge merge "
                "requests by hand."
            ),
        )


def page_data_dir(repo: Repository, setup: bool = False) -> None:
    st.header(t("Data folder"))
    if setup:
        st.warning(
            t(
                "No data folder found. A **Git repository** is recommended: changes are "
                "traceable and shareable with the team. Please choose an existing folder "
                "(also possible without Git), create a new data repository or clone an "
                "existing one."
            )
        )
    else:
        root = git_root(repo.root)
        st.markdown(t("Current: `{path}`", path=repo.root.resolve()))
        if problem := git_problem(repo.root):
            _show_problem(problem)
        else:
            st.caption(
                t("Git repository: `{path}`", path=root)
                if root
                else t("Attention: not inside a Git repository.")
            )
        _remote_section(repo)
        if root:
            _attributes_section(repo)
    if recent := _recent_dirs(repo):
        st.subheader(t("Recently used"))
        for n, folder in enumerate(recent):
            left, switch, forget = st.columns([6, 1.2, 1.2], vertical_alignment="center")
            left.markdown(_recent_label(folder))
            switch.button(
                t("Switch"),
                key=f"recent-go-{n}",
                on_click=_switch_clicked,
                args=(folder,),
                disabled=not _dir_exists(folder),
            )
            forget.button(
                t("Remove"),
                key=f"recent-forget-{n}",
                on_click=_forget_clicked,
                args=(folder,),
                help=t("Only removes it from the list; the folder stays."),
            )
        st.caption(_switch_hint(repo))
    choose, create, clone = st.tabs(
        [
            t("Choose existing folder"),
            t("Create new data repository"),
            t("Clone repository"),
        ]
    )
    home = Path.home()
    with choose:
        path = _path_input(t("Folder"), "data-path", str(repo.root.resolve()))
        if st.button(t("Apply"), type="primary", key="data-choose", disabled=path is None):
            try:
                if not path.is_dir():
                    st.error(t("Folder not found: {path}", path=path))
                elif problem := git_problem(path):
                    # Git rejects the folder, but the app also works without Git: next to the
                    # reason, "Use without Git" stays (creating a repository is not possible there).
                    _show_problem(problem)
                    st.session_state["offer-init"] = str(path)
                elif git_root(path) is None:
                    st.warning(
                        t(
                            "The folder is not in a Git repository. The program also works "
                            "without Git – only commit and history are then unavailable. "
                            "You can create a repository here or use the folder without "
                            "Git. An unpacked ZIP archive is not a repository; for the "
                            "data of an existing team choose “Clone repository” further "
                            "down instead."
                        )
                    )
                    st.session_state["offer-init"] = str(path)
                elif problem := _use_data_dir(teams_dir(path) or path):
                    st.error(problem)
                else:
                    st.rerun()
            except OSError as e:  # no access, not readable: a message instead of the error page
                _show_problem(folder_problem(path, e))
        offer = st.session_state.get("offer-init")
        if offer and st.button(
            t("Use without Git"), key="data-without-git", disabled=not Path(offer).is_dir()
        ):
            try:
                target = teams_dir(Path(offer)) or Path(offer)
            except OSError as e:
                _show_problem(folder_problem(Path(offer), e))
                st.stop()
            # Deliberate choice: without teams and without Git, do not go back to the setup but
            # on to "New team", permanently per folder, even after reloading the tab.
            try:
                remember_without_git(target)
            except SettingsError as e:
                st.error(_settings_problem(e, t("The folder was not adopted.")))
            else:
                if problem := _use_data_dir(target):
                    # Do not adopt halfway: the decision only holds together with the switch.
                    with contextlib.suppress(SettingsError):
                        forget_without_git(target)
                    st.error(problem)
                else:
                    st.session_state.pop("offer-init", None)
                    st.rerun()
        if (
            offer
            and not git_problem(Path(offer))
            and st.button(t("Create Git repository in {path}", path=offer), key="data-init-here")
        ):
            try:
                target = init_data_repository(Path(offer), teams_folder=False)
                found = teams_dir(target) or target
            except GitError as e:
                _show_problem(e)
            except OSError as e:
                _show_problem(folder_problem(Path(offer), e))
            else:
                if problem := _use_data_dir(found):
                    st.error(problem)
                else:
                    st.session_state.pop("offer-init", None)
                    st.rerun()
    with create:
        st.caption(
            t(
                "Creates the folder with `git init`, a `.gitignore` (no spreadsheets) and "
                "the subfolder `teams`; inside it is a `.gitattributes` (YAML and reports "
                "with LF) that is shared with the data. Then create a team under **New "
                "team**."
            )
        )
        path = _path_input(t("New folder"), "data-new", str(home / "sprint-daten"))
        if st.button(t("Create"), type="primary", key="data-create", disabled=path is None):
            try:
                occupied = path.is_dir() and any(path.iterdir()) and teams_dir(path) is None
            except OSError as e:  # not readable: cannot tell whether it is empty
                _show_problem(folder_problem(path, e))
                st.stop()
            if occupied:
                st.error(
                    t(
                        "{path} is not empty – please choose an empty or new folder.",
                        path=path,
                    )
                )
            else:
                try:
                    target = init_data_repository(path)
                except GitError as e:
                    _show_problem(e)
                else:
                    if problem := _use_data_dir(target):
                        st.error(problem)
                    else:
                        st.rerun()
    with clone:
        st.caption(
            t(
                "For colleagues: clone the team's shared data repository. The app does not "
                "sign in by itself and never asks for a password. If the server requires a "
                "login, your computer's credential service handles it; if it is missing, "
                "the app then explains the next step."
            )
        )
        url = st.text_input(
            t("Address"), placeholder="https://git.example.com/team/sprint-daten.git"
        )
        path = _path_input(t("Target folder"), "data-clone", str(home / "sprint-daten"))
        if st.button(
            t("Clone"),
            type="primary",
            key="data-clone-go",
            disabled=not url.strip() or path is None,
        ):
            with st.spinner(t("Cloning …")):
                try:
                    clone_repository(url.strip(), path)
                except GitError as e:
                    _show_problem(_clone_problem(e))
                else:
                    if problem := _use_data_dir(teams_dir(path) or path):
                        st.error(problem)
                    else:
                        st.rerun()


def page_check(repo: Repository) -> None:
    st.header(t("Check all teams"))
    for key, issues in check_all(repo, today()).items():
        if not issues:
            st.success(t("{team}: no findings", team=key))
            continue
        st.subheader(key)
        for i in issues:
            # Location and text contain names from the files (people, products, keys): never
            # interpret as Markdown (links, images, formatting).
            show = st.error if i.level is Level.ERROR else st.warning
            show(f"{md_code(i.where)}: {md_plain(i.message)}")


def page_help(repo: Repository) -> None:
    st.header(t("Help"))
    st.markdown(
        t(
            "The web interface edits the same files as the command line – both can be "
            "mixed. Changes are saved locally. If the data is in a Git repository, "
            "**Commit changes** in the sidebar saves the changes there; if the team has a "
            "server, **Save and share** saves them and shares them with the team. More in "
            "the tab “Collaboration (Git)”."
        )
    )
    workflow, terms, fields, team, collaboration, commands = st.tabs(
        [
            t("Workflow"),
            t("Terms"),
            t("Input fields"),
            t("Team settings"),
            t("Collaboration (Git)"),
            t("Command line"),
        ]
    )
    with workflow:
        for step in WORKFLOW:
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment="center")
                left.caption(t(step.when))
                left.markdown(f"**{t(step.title)}**  \n{t(step.text)}")
                with right:
                    page_link(step.page)
    with terms:
        term, meaning = t("Term"), t("Meaning")
        st.table(
            pd.DataFrame([(t(a), t(b)) for a, b in TERMS], columns=[term, meaning]).set_index(term)
        )
        st.subheader(t("Capacity source in the forecast"))
        source = t("Source")
        st.table(
            pd.DataFrame(
                [(t(a), t(b)) for a, b in CAPACITY_SOURCES], columns=[source, meaning]
            ).set_index(source)
        )
    with fields:
        for f in FIELDS.values():
            with st.container(border=True):
                st.markdown(f"**{t(f.title)}**  \n{t(f.what)}")
                st.caption(f"{t('Source')}: {t(f.source)} · {t('Example')}: {t(f.example)}")
    with team:
        setting, meaning = t("Setting"), t("Meaning")
        st.table(
            pd.DataFrame(
                [(s.title, s.text) for s in SETTINGS], columns=[setting, meaning]
            ).set_index(setting)
        )
        page_link("einstellungen", t("Change settings"))
    with collaboration:
        for title, text in GIT_HELP:
            with st.container(border=True):
                st.markdown(f"**{t(title)}**  \n{t(text)}")
    with commands:
        command, purpose = t("Command"), t("Purpose")
        st.table(
            pd.DataFrame([(a, t(b)) for a, b in COMMANDS], columns=[command, purpose]).set_index(
                command
            )
        )
        st.caption(t("Run with `uv run …` in the tool's folder."))


# --- Sidebar and page call ------------------------------------------------------------


def sidebar(repo: Repository) -> None:
    """Language and team selection in the sidebar (before the page, so the page knows them)."""
    teams = repo.teams()
    with st.sidebar:
        _active_repo_caption(repo)
        _switch_panel(repo)
        codes = list(LANGUAGES)
        st.session_state.setdefault("language", language())
        st.selectbox(
            "Sprache / Language",
            codes,
            format_func=LANGUAGES.get,
            key="language",
            on_change=_language_changed,
        )
        if not teams:
            st.info(t("No team yet."))
            return
        wanted = st.session_state.get("selected_team")
        team = st.selectbox("Team", teams, index=teams.index(wanted) if wanted in teams else 0)
        st.session_state["selected_team"] = team


@st.cache_resource
def _update_check() -> updater.AutoUpdate:
    """Check for a new version in the background once per server start."""
    return updater.AutoUpdate().start()


def _shutdown_soon() -> None:
    """Stops the server shortly after the message is drawn (the update process takes care of
    the restart)."""
    import threading

    threading.Timer(1.5, lambda: os._exit(0)).start()


def _manual_update_check(check: updater.Check | None) -> None:
    """ "Check for updates" button (the automatic check only runs once a day)."""
    manual = st.session_state.get("manual-check")
    if manual is not None:
        if manual.error:
            st.caption(t("Search not possible: {error}", error=manual.error))
        else:
            st.caption(t("Version {current} is up to date.", current=manual.current))
    if check is not None and check.installation is None:
        return  # not installed with uv: nothing to update here
    if st.button(t("Check for updates"), icon=":material/refresh:", key="manual-check-button"):
        with st.spinner(t("Searching …")):
            st.session_state["manual-check"] = updater.check(force=True, timeout=8.0)
        st.rerun()


def _update_panel() -> None:
    # Do not wait for the background thread: the result appears in the next run.
    check = st.session_state.get("manual-check") or _update_check().result()
    if check is None or not check.available:
        _manual_update_check(check)
        return
    restarting = t("Updating and restarting … the window will reopen shortly.")
    if st.session_state.get("restarting"):
        st.info(restarting)
        return
    if (
        updater.load_state().get("attempted") == check.latest
        and st.session_state.get("update-started") is None
    ):
        st.warning(
            t(
                (
                    "Version {latest} is available, but the update did not take effect (log: "
                    "`{log}`). If necessary, run the install script again."
                ),
                latest=check.latest,
                log=updater.log_file(),
            )
        )
        return
    with st.container(border=True):
        st.markdown(
            t(
                "**New version {latest}** available (installed: {current}).",
                latest=check.latest,
                current=check.current,
            )
        )
        if updater.mode() is updater.Mode.ON:
            st.caption(t("Will be installed automatically on close."))
        if st.button(t("Update and restart now"), icon=":material/system_update:"):
            if error := updater.restart_with_update():
                st.error(error)
                return
            st.session_state["restarting"] = True
            st.session_state["update-started"] = True
            st.info(restarting)
            _shutdown_soon()


def sidebar_footer(repo: Repository) -> None:
    """Git area and hints, drawn after the page so that what was just saved already shows up
    as an open change."""
    _update_panel()
    _git_panel(repo)
    st.caption(
        t(
            "Data: `{path}`  \nAs of: {day}  \n{version}",
            path=repo.root.resolve(),
            day=f"{today():%d.%m.%Y}",
            version=status_line(),
        )
    )


COMMIT_DEFAULT = "Sprint data updated"


def _commit_default() -> str:
    return t(COMMIT_DEFAULT)


def _load_changes(
    root: Path, pending: list[tuple[str, str]]
) -> tuple[list[FileChange], Path | None] | None:
    """Changed files with values (and the Git root) once per run; ``None`` without Git access."""
    try:
        return cached_file_changes(root, pending), git_root(root)
    except GitError:
        return None


def _reset_commit_message() -> None:
    """Back to the default message (after a commit); the next change brings a new suggestion."""
    st.session_state["commit_message"] = st.session_state["commit_message_auto"] = _commit_default()


def _refresh_commit_message(
    root: Path, loaded: tuple[list[FileChange], Path | None] | None
) -> None:
    """Follows the changes with the suggested message as long as the user has not edited it."""
    suggested = _commit_default()
    if loaded is not None:
        files, top = loaded
        named = [
            replace(
                fc,
                file=_view_name(root, fc.file, top),
                orig=_view_name(root, fc.orig, top) if fc.orig else "",
            )
            for fc in files
        ]
        suggested = suggest_message(named) or suggested
    current = st.session_state.get("commit_message", "").strip()
    if current in ("", st.session_state.get("commit_message_auto"), _commit_default()):
        st.session_state["commit_message"] = suggested
    st.session_state["commit_message_auto"] = suggested


def _commit_clicked(root: Path, tags: list[str]) -> None:
    """Callback of the commit button; runs before the next run of the script."""
    message = st.session_state.get("commit_message", "").strip() or _commit_default()
    use_tags = tags and st.session_state.get("use_tags", True)
    try:
        rev = commit_directory(root, message, tags if use_tags else None)
    except GitError as e:
        st.session_state["commit_error"] = e
        return
    st.session_state["pending_tags"] = []
    st.session_state["last_commit"] = rev
    _reset_commit_message()


# "Save and share" runs in the button's callback, in the script thread. If another request from
# the browser arrives meanwhile (second click, input, a trailing run after saving), Streamlit
# immediately starts a new run and stops the old one at its next touch of ``st.session_state``.
# The old callback then aborts after the sync, before it stores the result: the sync has run,
# the message is missing forever, and the new run shows the sidebar in the middle of the sync
# (commit made, merge and upload apparently not). So the callback first stores the result in a
# plain slot (``_SyncSlot``, without a Streamlit breakpoint); each run waits at its start for a
# limited time for a still running sync and picks up its result (``collect_sync_result``); a
# second click does not start a second sync and says so. Everything belongs to one browser
# session (key: Streamlit's session ID), not to the process: a sync in one window does not
# block the others. The results carry the data folder: if the session switches the folder, they
# no longer apply.
SYNC_WAIT_SECONDS = 10.0  # how long a new run waits for a running sync
SYNC_SLOT_TTL = 3600.0  # how long the slot of an idle (orphaned) session is kept
SYNC_RUNNING_KEY = "sync-running"  # session state: the sync was still running when drawing


def _now() -> float:
    return time.monotonic()


class _SyncSlot:
    """Lock ("is a sync running right now?") and not yet adopted results of a browser session.
    All accesses are short and free of Streamlit, so they are also safe from an already
    stopped run."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._running = False
        self._done: dict[str, list[SyncResult]] = {}  # data folder -> results, oldest first
        self.touched = _now()

    @property
    def running(self) -> bool:
        with self._cond:
            return self._running

    def begin(self) -> bool:
        """Non-blocking: ``False`` if a sync is already running."""
        with self._cond:
            if self._running:
                return False
            self._running = True
            return True

    def end(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()

    def wait_idle(self, timeout: float) -> bool:
        """Waits at most ``timeout`` seconds until no sync is running anymore; ``False`` if it
        is still running after that."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._running, timeout)

    def put(self, root: Path, result: SyncResult) -> None:
        with self._cond:
            self._done.setdefault(str(root), []).append(result)

    def pending(self, root: Path) -> list[SyncResult]:
        """The results for this data folder (oldest first). Those for other data folders
        expire: they belong to a folder this session has left."""
        with self._cond:
            mine = str(root)
            for other in [folder for folder in self._done if folder != mine]:
                del self._done[other]
            return list(self._done.get(mine, ()))

    def discard(self, root: Path, result: SyncResult) -> None:
        with self._cond:
            results = self._done.get(str(root), [])
            for i, candidate in enumerate(results):
                if candidate is result:
                    del results[i]
                    break
            if not results:
                self._done.pop(str(root), None)


_SYNC_SLOTS: dict[str, _SyncSlot] = {}  # session ID -> slot
_SYNC_SLOTS_GUARD = threading.Lock()


def _session_key() -> str:
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx is not None else ""


def _find_sync_slot(create: bool) -> _SyncSlot | None:
    """The slot of this session. On access, the slots of orphaned sessions are removed: unused
    for a long time and without a running sync (the own session counts as just used)."""
    key = _session_key()
    now = _now()
    with _SYNC_SLOTS_GUARD:
        slot = _SYNC_SLOTS.get(key)
        if slot is None and create:
            slot = _SYNC_SLOTS[key] = _SyncSlot()
        if slot is not None:
            slot.touched = now
        for other, candidate in list(_SYNC_SLOTS.items()):
            if now - candidate.touched > SYNC_SLOT_TTL and not candidate.running:
                del _SYNC_SLOTS[other]
        return slot


def _sync_slot() -> _SyncSlot:
    slot = _find_sync_slot(create=True)
    assert slot is not None
    return slot


def _remember_sync_result(result: SyncResult) -> None:
    """Stores the result of a sync in the session state and cleans up the state that depends
    on it. May run repeatedly (also after an aborted first attempt)."""
    if result.committed:
        st.session_state["pending_tags"] = []
        _reset_commit_message()
    # An earlier result that has not been shown yet is not overwritten but moves to the list of
    # earlier ones (the sidebar shows both). Running this repeatedly changes nothing.
    previous = st.session_state.get("sync_result")
    earlier = st.session_state.get("sync_earlier", [])
    if previous is not None and previous is not result and all(r is not previous for r in earlier):
        st.session_state["sync_earlier"] = [*earlier, previous]
    st.session_state["sync_result"] = result
    st.session_state.pop("tags-server", None)  # the tag sync is no longer current
    st.session_state.pop("tags-server-failed", None)
    st.session_state.pop("unrelated-confirm", None)  # a confirmation applies only once
    # The prompt about the foreign history stays across runs (checkbox, button).
    if result.error is not None and result.error.kind == "unrelated_histories":
        st.session_state["unrelated"] = result.error
    else:
        st.session_state.pop("unrelated", None)
    if result.pulled_files:
        clear_team_cache()  # files have changed: reload


def _apply_sync_results(slot: _SyncSlot, root: Path) -> None:
    """Adopts the stored results of this data folder into the session state, oldest first. A
    result stays in the slot until it is adopted: if this attempt aborts too, the next run
    picks it up."""
    for result in slot.pending(root):
        _remember_sync_result(result)
        slot.discard(root, result)


def collect_sync_result() -> None:
    """At the start of each run, before any Git query: wait for a limited time for a still
    running sync (it belongs to a stopped, older run or an earlier click) and adopt its result
    in case that callback could no longer store it. If the sync takes longer, drawing
    continues; the sidebar says that it is still running."""
    slot = _find_sync_slot(create=False)
    if slot is None:  # nothing was ever shared in this session
        st.session_state.pop(SYNC_RUNNING_KEY, None)
        return
    if slot.wait_idle(SYNC_WAIT_SECONDS):
        st.session_state.pop(SYNC_RUNNING_KEY, None)
    else:
        st.session_state[SYNC_RUNNING_KEY] = True
    _apply_sync_results(slot, data_dir())


def _sync_clicked(
    root: Path,
    tags: list[str],
    allow_invalid: bool = False,
    allow_unrelated: bool = False,
    push: bool = True,
) -> None:
    """The "Save and share" action: secure own changes, fetch the others', upload. With
    ``push=False`` ("Pull from server") it only secures and adopts the server state."""
    slot = _sync_slot()
    if not slot.begin():  # a sync of this session is still running: do not start another
        st.session_state.setdefault("flash", []).append(
            (
                "warning",
                t(
                    "A sync was still running: this click was not carried out. After the "
                    "result of the running sync, click again if needed."
                ),
            )
        )
        return
    try:
        message = st.session_state.get("commit_message", "").strip() or _commit_default()
        use_tags = tags and st.session_state.get("use_tags", True)
        result = sync(
            root,
            message,
            tags if use_tags else None,
            today(),
            allow_invalid=allow_invalid,
            allow_unrelated=allow_unrelated,
            push=push,
        )
        slot.put(root, result)  # before releasing: whoever wakes up afterwards finds it
    finally:
        slot.end()
    _apply_sync_results(slot, root)


def _abort_sync_clicked(root: Path) -> None:
    """Explicit abort of a hanging sync (never automatic)."""
    if not abort_running_sync(root):
        st.session_state.setdefault("flash", []).append(
            ("info", t("Nothing is running any more: the sync had already finished."))
        )


def _unrelated_cancel() -> None:
    st.session_state.pop("unrelated", None)
    st.session_state.pop("unrelated-confirm", None)


def _continues_pull_only() -> bool:
    """Does the sync that is being continued (after conflicts, after the prompt about the
    foreign history) belong to "Pull from server"? Then continuing uploads nothing either."""
    last = st.session_state.get("sync_result")
    return bool(last is not None and last.pull_only)


def _unrelated_go(root: Path, tags: list[str]) -> None:
    push = not _continues_pull_only()
    _unrelated_cancel()
    _sync_clicked(root, tags, allow_unrelated=True, push=push)


def _unrelated_dialog(root: Path, tags: list[str], error: UnrelatedHistoriesError) -> None:
    """The server has an unrelated history: explain and merge only after explicit confirmation.
    The default is to cancel (button disabled until the checkbox is ticked)."""
    with st.container(border=True):
        st.error(f"**{git_title(error.kind)}**  \n{error.hint_md}")
        st.markdown(error.render(md_code))  # names server address and branch: as code
        page_link("datenordner", t("Change server address"))  # the address is usually the problem
        sure = st.checkbox(t("Yes, merge both histories"), key="unrelated-confirm")
        st.button(
            t("Merge both histories"),
            key="unrelated-go",
            type="primary",
            disabled=not sure,
            on_click=_unrelated_go,
            args=(root, tags),
        )
        st.button(t("Cancel"), key="unrelated-cancel", on_click=_unrelated_cancel)


def _fetch_clicked(root: Path) -> None:
    fetch_remote(root)


def _abort_clicked(root: Path) -> None:
    try:
        abort_unfinished(root)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        st.session_state["flash"] = [("success", t("Merge aborted."))]


def _reattach_clicked(root: Path) -> None:
    try:
        done = reattach(root)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        text = t("Back on branch {branch}.", branch=md_code(done.branch))
        if done.rescue and done.commits and done.changes:
            text += " " + t(
                (
                    "The commits from the state without a branch and the open changes are on "
                    "the rescue branch {rescue} (a separate branch just for saved work); the "
                    "main branch does not contain them."
                ),
                rescue=md_code(done.rescue),
            )
        elif done.rescue and done.changes:
            text += " " + t(
                (
                    "The open changes are on the rescue branch {rescue} (a separate branch "
                    "just for saved work); the main branch does not contain them."
                ),
                rescue=md_code(done.rescue),
            )
        elif done.rescue:
            text += " " + t(
                "The commits from the state without a branch are on the rescue branch {rescue}.",
                rescue=md_code(done.rescue),
            )
        st.session_state["flash"] = [("success", text)]


def _identity_clicked() -> None:
    try:
        set_identity(st.session_state.get("git-name", ""), st.session_state.get("git-email", ""))
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        st.session_state["flash"] = [
            ("success", t("Name and email address saved. Please try again."))
        ]


def _clone_problem(error: GitError) -> GitError:
    """When cloning there are no own changes and no "Save and share": the hints for server not
    reachable and not found talk about cloning."""
    hints = {
        "offline": t(
            "The server is not reachable. Check the internet connection or VPN and then "
            "choose “Clone” again."
        ),
        "not_found": t(
            "The repository was not found. Please check the address (spelling, upper and "
            "lower case) or ask whoever runs the server whether it exists and you have "
            "access."
        ),
    }
    if error.kind not in hints:
        return error
    return GitError(str(error), error.kind, hints[error.kind], error.raw)


def _show_problem(error: GitError, interactive: bool = True) -> None:
    """Error with heading, next step and (expandable) the message from Git. Without a hint the
    message itself is shown; output from Git and the server (names and lines that others
    control) as code, never as Markdown. Without ``interactive`` no input fields (name,
    email): the fields exist only once per page."""
    st.error(f"**{git_title(error.kind)}**  \n{error.hint_md or error.render(md_code_lines)}")
    if error.hint and str(error):
        with st.expander(t("Technical message")):
            st.code(str(error), language=None)
    if interactive and error.kind == "identity":
        st.text_input(t("Name"), key="git-name")
        st.text_input(t("Email address"), key="git-email")
        st.button(t("Save"), key="git-identity", on_click=_identity_clicked)


def _show_sync_result(result: SyncResult, root: Path, tags: list[str], latest: bool = True) -> None:
    """Message about a sync. An earlier sync that has not been shown yet (``latest`` is false)
    appears without buttons and input fields: those exist only for the latest one."""
    done = []
    if result.committed:
        done.append(t("Own changes saved ({rev})", rev=result.committed))
    if result.pulled:
        done.append(t("{count} change(s) by others taken over", count=len(result.pulled)))
    if result.pushed and result.merge_request_branch:
        done.append(
            t("Uploaded to branch {branch}", branch=md_code(result.merge_request_branch))
            + (
                " · " + t("[Open merge/pull request]({url})", url=result.merge_request_url)
                if result.merge_request_url
                else " · " + t("Open or check the merge/pull request on the server")
            )
        )
    elif result.pushed:
        done.append(t("Uploaded"))
    if result.error is None:
        if result.pull_only and (result.committed or result.merged):
            done.append(t("Not uploaded yet: “Save and share” uploads it"))
        st.success(" · ".join(done) if done else t("Everything is up to date."))
    else:
        if done:
            st.info(t("Done so far:") + " " + " · ".join(done))
        if result.error.kind != "unrelated_histories":  # the prompt is below
            _show_problem(result.error, interactive=latest)
        if latest and result.error.kind == "sync_busy":
            st.button(
                t("Abort running sync"),
                key="sync-abort",
                on_click=_abort_sync_clicked,
                args=(root,),
            )
        if latest and result.error.kind == "not_found":  # usually the address is wrong
            page_link("datenordner", t("Change server address"))
        if result.validation:
            st.markdown("\n".join(f"- {line}" for line in result.validation))
            if latest:
                st.button(
                    t("Share anyway"),
                    key="git-force",
                    on_click=_sync_clicked,
                    args=(root, tags, True),
                    help=t("Uploads the data although the check reports new errors."),
                )
    for note in result.notes:  # notes, even if everything succeeded
        st.warning(note)
    if result.pulled:
        with st.expander(t("New from others"), expanded=True):
            _show_incoming(result.pulled, result.pulled_files)


def _show_incoming(commits: list[Commit], files: list[tuple[str, str]]) -> None:
    for c in commits:
        # Author and subject are controlled by others: as code, never as Markdown.
        st.markdown(f"`{c.rev}` {c.day} {md_code(c.author)}: {md_code(c.subject)}")
    if files:
        st.code("\n".join(f"{status:>2} {file}" for status, file in files), language=None)


def _status_text(state: SyncState) -> str:
    """One line on the state relative to the server."""
    if state.unfinished or state.conflicts:
        return t("Merge incomplete")
    if state.detached:
        return t("No branch selected")
    if state.remote is None:
        return t("No server set up – changes stay local.")
    parts = []
    if state.ahead:
        parts.append(t("{count} not shared yet", count=state.ahead))
    if state.behind:
        parts.append(t("{count} new from others", count=state.behind))
    if not parts and state.unborn:
        parts.append(t("no data saved yet"))
    elif not parts and state.upstream is None:
        # Server is set, but the branch was never uploaded (freshly set, usually empty server):
        # "in sync" would be wrong, nothing is there yet.
        parts.append(t("not on the server yet – “Save and share” uploads it"))
    elif not parts:
        parts.append(t("in sync with {upstream}", upstream=md_code(state.upstream)))
    if state.fetch_error is not None:
        if state.offline:
            parts.append(t("Server not reachable"))
        elif state.fetch_error.kind in {"not_writable", "locked", "unsafe_directory"}:
            # An error on this machine, nothing the server would have reported.
            parts.append(t("Check not possible: {kind}", kind=git_title(state.fetch_error.kind)))
        else:
            parts.append(t("Server reports: {kind}", kind=git_title(state.fetch_error.kind)))
    elif state.fetched_at is None:
        parts.append(t("Server state not checked yet"))
    else:
        minutes = int((time.time() - state.fetched_at) // 60)
        parts.append(
            t("Server state checked {minutes} min ago", minutes=minutes)
            if minutes
            else t("Server state just checked")
        )
    return " · ".join(parts)


_VIEW_FILES = 25
_VIEW_ROWS = MAX_VALUES
_VIEW_TEXT = 80


def _diff_clean(text: str) -> str:
    """Like :func:`_view_clean` for multi-line text (diff): line breaks and tabs stay, text
    direction control characters are dropped, other control characters become spaces."""
    return "".join(
        c
        if c in "\n\t"
        else ""
        if c in _BIDI_CONTROLS
        else " "
        if unicodedata.category(c) in _BLANKED_CATEGORIES
        else c
        for c in text
    )


def _view_clean(text: str) -> str:
    """Make line breaks and tabs visible, remove text direction control characters, turn other
    control characters into spaces (like :func:`md_code`)."""
    text = text.replace("\n", "⏎").replace("\t", "⇥")
    return "".join(
        "" if c in _BIDI_CONTROLS else " " if unicodedata.category(c) in _BLANKED_CATEGORIES else c
        for c in text
    )


_BOUND_ITEMS = 1000  # entries per list or object
_BOUND_TEXT = 1000  # characters per text
_BOUND_NODES = 5000  # nodes per value
_BOUND_DEPTH = 8
_BOUND_BITS = 128  # the view shows larger integers only truncated


class _Raw(str):
    """Text already finished for the view (truncation, large number)."""


class _ViewDumper(yaml.SafeDumper):
    pass


_ViewDumper.add_representer(
    _Raw, lambda dumper, data: dumper.represent_scalar("tag:yaml.org,2002:str", str(data))
)


def _bound(value: Any, left: list[int], depth: int = 0) -> Any:
    """Truncates ``value`` to an excerpt that fits a cell of 80 characters (depth, number of
    entries and nodes, length of the texts). Large integers are not dumped: ``yaml.safe_dump``
    and ``str`` fail from 4300 digits on."""
    left[0] -= 1
    if left[0] < 0 or depth > _BOUND_DEPTH:
        return _Raw("…")
    if isinstance(value, bool) or value is None or isinstance(value, (float, date)):
        return value
    if isinstance(value, int):
        if value.bit_length() <= _BOUND_BITS:
            return value
        return _Raw(f"{'-' if value < 0 else ''}{hex(abs(value))[:14]}… ({value.bit_length()} Bit)")
    if isinstance(value, str):
        return value if len(value) <= _BOUND_TEXT else _Raw(value[:_BOUND_TEXT] + "…")
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _BOUND_ITEMS:
                out[_Raw("…")] = _Raw("…")
                break
            out[_bound(k, left, depth + 1)] = _bound(v, left, depth + 1)
        return out
    if isinstance(value, list):
        items = [_bound(v, left, depth + 1) for v in value[:_BOUND_ITEMS]]
        if len(value) > _BOUND_ITEMS:
            items.append(_Raw("…"))
        return items
    if isinstance(value, (set, frozenset)):
        shown: set[Any] = {_bound(v, left, depth + 1) for v in islice(value, _BOUND_ITEMS)}
        if len(value) > _BOUND_ITEMS:
            shown.add(_Raw("…"))
        return shown
    if isinstance(value, (bytes, bytearray)):
        return _Raw(f"bytes, {len(value)} Byte")
    try:  # all other types: as bounded text
        return _Raw(repr(value)[:_BOUND_TEXT])
    except Exception:
        return _Raw(t("(value cannot be shown)"))


def _view_text(value: object) -> str:
    """Value in the notation of the file (``null``, ``true``, ``'1'`` for text); missing: "–".
    The value is truncated first (:func:`_bound`) so that large values stay fast."""
    if value is MISSING:
        return "–"
    try:
        text = yaml.dump(
            _bound(value, [_BOUND_NODES]),
            Dumper=_ViewDumper,
            allow_unicode=True,
            default_flow_style=True,
            width=1_000_000,
        ).strip()
        text = text.removesuffix("\n...").strip()
    except Exception:  # a cell must never stop the page
        try:
            text = repr(value)[:_BOUND_TEXT]
        except Exception:
            text = t("(value cannot be shown)")
    return _view_clean(text)


def _formula_safe(text: str, value: object = None) -> str:
    """Table export: text that Excel would read as a formula gets an apostrophe (display only).
    Numbers stay as they are."""
    # Only real numbers in number format stay; the short form of large numbers and ``-.inf``
    # do not.
    number = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and re.fullmatch(r"-?\d+(\.\d+)?(e[+-]?\d+)?", text) is not None
    )
    if not number and text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _view_clip(text: str, start: int) -> str:
    text = ("…" if start else "") + text[start:]
    return text if len(text) <= _VIEW_TEXT else text[: _VIEW_TEXT - 1] + "…"


def _view_pair(old: object, new: object) -> tuple[str, str]:
    """Before and after as table cells. If they are too long, both start shortly before the
    first difference so that the difference is visible."""
    a, b = _view_text(old), _view_text(new)
    if len(a) > _VIEW_TEXT or len(b) > _VIEW_TEXT:
        common = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), None)
        common = min(len(a), len(b)) if common is None else common
        start = max(0, common - 10)
        a, b = _view_clip(a, start), _view_clip(b, start)
    if a == b:
        b += t(" (difference not visible, check the file)")
    return _formula_safe(a, old), _formula_safe(b, new)


_VIEW_LABEL = 120
# Finished table rows per file: the result of ``cached_file_changes`` keeps its objects as
# long as it is valid; this cache is cleared together with it.
_ROWS: dict[tuple[int, str], tuple[FileChange, list[tuple[str, str, str]]]] = {}
_ROWS_MAX = 300
on_invalidate(_ROWS.clear)


def _file_rows(fc: FileChange) -> list[tuple[str, str, str]]:
    """Rows (field, before, after) of the first values of a file, plus a remainder row."""
    key = (id(fc), language())
    cached = _ROWS.get(key)
    if cached and cached[0] is fc:
        return cached[1]
    rows = []
    for v in fc.values[:_VIEW_ROWS]:
        label = _view_clean(v.label)
        if len(label) > _VIEW_LABEL:
            label = label[: _VIEW_LABEL - 1] + "…"
        rows.append((_formula_safe(label), *_view_pair(v.old, v.new)))
    if fc.omitted:
        rows.append((t("… and {n} more", n=fc.omitted), "", ""))
    if len(_ROWS) >= _ROWS_MAX:
        _ROWS.clear()
    _ROWS[key] = (fc, rows)
    return rows


def _view_name(root: Path, file: str, git_root_path: Path | None) -> str:
    """File name relative to the data folder, if possible."""
    if git_root_path is not None:
        with contextlib.suppress(ValueError):
            return (git_root_path / file).relative_to(root.resolve()).as_posix()
    return file


def _changes_view(root: Path, loaded: tuple[list[FileChange], Path | None] | None) -> None:
    """The "What has changed?" action: values before and after per changed file. File names
    and values come from files that others put into the repository: only as code or in
    tables."""
    if loaded is None:
        st.caption(t("The change view is not available right now."))
        return
    files, top = loaded
    st.markdown(f"**{t('What has changed?')}**")
    show_text = st.toggle(
        t("Show line-by-line difference"),
        key="git-text-diff",
        help=t(
            "Shows the text of each file before and after (like `git diff`), also for the minutes."
        ),
    )
    for fc in files[:_VIEW_FILES]:
        shown_fc = replace(
            fc,
            file=_view_name(root, fc.file, top),
            orig=_view_name(root, fc.orig, top) if fc.orig else "",
        )
        if shown_fc.orig:
            st.markdown(_lost_status(shown_fc))  # "renamed: old -> new", both as code
        else:
            st.markdown(f"{md_code(shown_fc.file)} – {status_name(fc.status)}")
        if fc.skipped:
            st.caption(t("not evaluated (too many or too large files)"))
        elif not fc.readable:
            st.caption(t("no value view"))
        elif fc.values:
            st.dataframe(
                pd.DataFrame(_file_rows(fc), columns=[t("Field"), t("Before"), t("After")]),
                hide_index=True,
                width="stretch",
            )
        elif any(c in fc.status for c in "MT") and not any(c in fc.status for c in "A?D"):
            st.caption(t("no change in values (only notation or order)"))
        if show_text and not fc.skipped:
            try:
                text = text_diff(root, Change(fc.status, fc.file, fc.orig))
            except GitError:
                text = ""
            if text:
                st.code(_diff_clean(text), language="diff")
    if len(files) > _VIEW_FILES:
        st.caption(t("… and {n} more", n=len(files) - _VIEW_FILES))


@st.fragment(run_every="30m")
def _background_fetch(root: str) -> None:
    """Fetches the server state when the sidebar is first drawn and then every 30 minutes in
    the background (only while a session is connected; ``idle.py`` remains authoritative)."""
    start_background_fetch(Path(root))


def _git_panel(repo: Repository) -> None:
    if not git_available():
        _show_problem(classify("", missing=True))
        return
    if git_root(repo.root) is None:
        if problem := git_problem(repo.root):
            _show_problem(problem)
        else:
            st.caption(t("The data folder is not inside a Git repository – commit not possible."))
        return
    if last := st.session_state.pop("last_commit", None):
        st.success(
            t("Committed ({rev}). Nothing is shared until you choose “Save and share”.", rev=last)
        )
    if error := st.session_state.pop("commit_error", None):
        if isinstance(error, GitError):
            _show_problem(error)
        else:
            st.error(error)
    earlier = st.session_state.pop("sync_earlier", [])
    if result := st.session_state.pop("sync_result", None):
        tags_now = list(st.session_state.get("pending_tags", []))
        for old in earlier:  # unshown syncs that the latest one has not overwritten
            _show_sync_result(old, repo.root, tags_now, latest=False)
        _show_sync_result(result, repo.root, tags_now)
    if unrelated := st.session_state.get("unrelated"):
        _unrelated_dialog(repo.root, list(st.session_state.get("pending_tags", [])), unrelated)
    if st.session_state.get(SYNC_RUNNING_KEY):
        # A sync of this session is still running (it takes longer than the run wanted to
        # wait). No Git queries alongside: they would show the state midway, and a concurrent
        # ``git status`` can make the sync's ``git add`` fail on the index lock.
        st.info(
            t(
                "The sync with the server is still running. Choose “Refresh” to see its "
                "result as soon as it has finished."
            )
        )
        st.button(t("Refresh"), key="git-sync-refresh", icon=":material/refresh:")
        if (held := sync_running_seconds(repo.root)) is not None and held >= LOCK_WARN_SECONDS:
            st.button(
                t("Abort running sync"),
                key="sync-abort-running",
                on_click=_abort_sync_clicked,
                args=(repo.root,),
            )
        return
    _background_fetch(str(repo.root))
    try:
        changes = cached_pending_changes(repo.root)
        state = cached_sync_state(repo.root)
    except GitError as e:
        st.warning(
            t(
                "Git reports a problem with the data folder. Please check in your file "
                "manager that the folder is still there and writable (for network drives: "
                "connected), then reload the page. Help: “Help” page, “Collaboration "
                "(Git)” tab."
            )
        )
        with st.expander(t("Technical message")):
            st.code(str(e), language=None)
        return
    tags = st.session_state.get("pending_tags", [])
    st.caption(_status_text(state))
    if state.remote is None:
        page_link("datenordner", t("Set up server"))
    with st.expander(
        t("Git: {count} pending change(s)", count=len(changes))
        if changes
        else t("Git: everything committed"),
        expanded=bool(changes) or state.behind > 0 or state.unfinished is not None,
        icon=":material/commit:",
    ):
        if state.unfinished or state.conflicts:
            st.warning(hint_for("conflict"))
            st.button(
                t("Abort merge"),
                key="git-abort",
                on_click=_abort_clicked,
                args=(repo.root,),
            )
            return
        if state.detached:
            st.warning(hint_for("detached"))
            st.button(
                t("Back to the branch"),
                key="git-reattach",
                on_click=_reattach_clicked,
                args=(repo.root,),
            )
            return
        if state.behind:
            commits, files = incoming(repo.root)
            st.markdown(t("**New from others** (not taken over yet)"))
            _show_incoming(commits, files)
        if changes:
            st.code("\n".join(f"{status:>2} {file}" for status, file in changes), language=None)
            loaded = _load_changes(repo.root, changes)
            _changes_view(repo.root, loaded)
            _refresh_commit_message(repo.root, loaded)
            st.text_input(t("Commit message"), key="commit_message")
            if tags:
                st.checkbox(t("Set tags: {tags}", tags=", ".join(tags)), value=True, key="use_tags")
        else:
            st.caption(t("No pending changes in the data folder."))
        if state.remote is not None:
            st.button(
                t("Save and share"),
                type="primary",
                icon=":material/sync:",
                key="git-sync",
                on_click=_sync_clicked,
                args=(repo.root, list(tags)),
                help=t(
                    "Saves your changes, fetches those of the others, merges both and "
                    "uploads the result."
                ),
            )
            st.button(
                t("Pull from server"),
                icon=":material/download:",
                key="git-pull",
                on_click=_sync_clicked,
                args=(repo.root, list(tags), False, False, False),
                help=t(
                    "Fetches the changes of the others into this data folder and merges "
                    "them with yours (your open changes are saved first). Uploads nothing."
                ),
            )
            st.button(
                t("Check state"),
                icon=":material/refresh:",
                key="git-fetch",
                on_click=_fetch_clicked,
                args=(repo.root,),
                help=t("Asks the server whether there is anything new (changes nothing)."),
            )
        if changes:
            st.button(
                t("Commit changes"),
                type="secondary" if state.remote is not None else "primary",
                icon=":material/save:",
                on_click=_commit_clicked,
                args=(repo.root, list(tags)),
                help=t("Save locally only, without sharing."),
            )


# --- Discard changes, history, tags ----------------------------------------------------------

# Status values of ``git status --porcelain`` (without spaces), also combined.
_STATUS_NAMES = {
    "M": "changed", "MM": "changed", "T": "changed", "TM": "changed",
    "D": "deleted", "MD": "deleted",
    "A": "new", "??": "new", "AM": "new", "AD": "new, then deleted",
    "R": "renamed", "RM": "renamed and changed", "RD": "renamed, then deleted",
    "C": "copied", "CM": "copied and changed",
    "DD": "Conflict", "UU": "Conflict", "AA": "Conflict", "UD": "Conflict", "DU": "Conflict",
    "AU": "Conflict", "UA": "Conflict",
}  # fmt: skip


def status_name(status: str) -> str:
    """Readable name of a Git status (unknown ones count as "changed")."""
    return t(_STATUS_NAMES.get(status, "changed"))


def _lost_status(item: Lost | FileChange) -> str:
    """Status of a lost change; for renames with the old and new path."""
    name = status_name(item.status)
    if item.orig:
        # As code: paths can contain characters that Markdown would otherwise interpret.
        return t(
            "{name}: {orig} → {file}", name=name, orig=md_code(item.orig), file=md_code(item.file)
        )
    return name


def _git_action(action: Callable[[], object], ok: Callable[[object], str]) -> None:
    """Runs a Git operation in the callback; the message or error appears in the next run."""
    try:
        result = action()
    except GitError as e:
        st.session_state["commit_error"] = e
        return
    clear_team_cache()
    kind = "success"
    if isinstance(result, GitError):  # warning, e.g. tag only set locally
        # The message names tags and lines from the server (hooks): as code, never as Markdown.
        kind, text = "warning", t("Done locally only: {error}", error=result.full(md_code_lines))
    else:
        text = ok(result)
    st.session_state["flash"] = [(kind, text)]


def _tags_check_clicked(root: Path) -> None:
    """Asks the server for the tags (network, only on click) and remembers the result."""
    try:
        tags = list_tags(root, check_server=True)
        # Without local tags the list does not reveal whether the sync succeeded.
        st.session_state["tags-server-failed"] = not tags and not server_reachable(root)
        st.session_state["tags-server"] = tags
    except GitError as e:
        st.session_state["commit_error"] = e


def _tags_recheck(root: Path) -> None:
    """After a tag action, refresh the server state that was already queried."""
    if "tags-server" in st.session_state:
        _tags_check_clicked(root)


def _tag_delete_go(root: Path, name: str) -> None:
    st.session_state.pop(f"tag-confirm-{name}", None)  # the confirmation applies only once
    _git_action(
        lambda: delete_tag(root, name),
        lambda _: t("Tag {name} deleted.", name=md_code(name)),
    )
    _tags_recheck(root)


def _tag_upload_go(root: Path, name: str) -> None:
    _git_action(
        lambda: upload_tag(root, name),
        lambda _: t("Tag {name} uploaded to the server.", name=md_code(name)),
    )
    _tags_recheck(root)


def _tag_state(tag: Tag) -> str:
    """Where the tag exists (empty as long as the server has not been queried)."""
    if not tag.local:
        return t("only on the server")
    if tag.on_server is None:
        return ""
    if not tag.on_server:
        return t("local only")
    return t("different") if tag.differs else t("on the server")


def _discard_request(files: list[str] | None) -> None:
    st.session_state["discard-request"] = files if files is not None else "ALL"
    st.session_state.pop("discard-confirm", None)


def _discard_cancel() -> None:
    st.session_state.pop("discard-request", None)
    st.session_state.pop("discard-confirm", None)


def _discard_selected(lost: list) -> None:
    chosen = [item.file for i, item in enumerate(lost) if st.session_state.get(f"disc-{i}")]
    if chosen:
        _discard_request(chosen)


def _discard_go(root: Path, files: list[str] | None) -> None:
    _discard_cancel()
    _git_action(
        lambda: discard(root, files),
        lambda trash: (
            t("Changes discarded. Backup copy: {path}", path=md_code(str(trash)))
            if trash
            else t("Changes discarded.")
        ),
    )


def _tab_changes(repo: Repository, locked: bool = False) -> None:
    lost = discard_preview(repo.root)
    if not lost:
        st.success(t("No pending changes in the data folder."))
        return
    st.caption(
        t(
            "Discarding resets files to the last saved (committed) state. A backup copy is "
            "placed in the trash under `.git` first."
        )
    )
    for i, item in enumerate(lost):
        st.checkbox(
            t(
                "{file} – {status} (+{added} −{removed} lines)",
                file=md_code(item.file),  # labels of widgets are interpreted as Markdown too
                status=_lost_status(item),
                added=item.added,
                removed=item.removed,
            ),
            key=f"disc-{i}",
        )
    left, right = st.columns(2)
    left.button(t("Discard selected …"), on_click=_discard_selected, args=(lost,), disabled=locked)
    right.button(
        t("Discard everything …"), on_click=_discard_request, args=(None,), disabled=locked
    )
    request = st.session_state.get("discard-request")
    if request is None:
        return
    files = None if request == "ALL" else request
    shown = [item for item in lost if files is None or item.file in files]
    with st.container(border=True):
        st.warning(
            t(
                "This will be lost ({count} file(s)):  \n{list}",
                count=len(shown),
                list="  \n".join(
                    f"{md_code(i.file)} – {_lost_status(i)}, +{i.added} −{i.removed}" for i in shown
                ),
            )
        )
        sure = st.checkbox(t("Yes, discard these changes"), key="discard-confirm")
        ok, cancel = st.columns(2)
        ok.button(
            t("Discard now"),
            type="primary",
            disabled=not sure or locked,
            on_click=_discard_go,
            args=(repo.root, files),
        )
        cancel.button(t("Cancel"), on_click=_discard_cancel)


def _entry_label(e: HistoryEntry) -> str:
    return f"{e.day} · {e.author} · {e.subject} ({e.short})"


def _tab_history(repo: Repository, locked: bool = False) -> None:
    team = st.session_state.get("selected_team")
    scopes = [t("Data folder")]
    if team and repo.exists(team):
        scopes = [t("Team"), t("Sprint"), t("File"), *scopes]
    kind = st.radio(t("Show for"), scopes, horizontal=True, key="history-scope")
    scope = repo.root
    if team and repo.exists(team) and kind != t("Data folder"):
        base = repo.team_dir(team)
        scope = base
        if kind == t("Sprint"):
            ids = sorted(p.stem for p in (base / "sprints").glob("*.yaml"))
            if ids:
                scope = base / "sprints" / f"{st.selectbox(t('Sprint'), ids[::-1])}.yaml"
        elif kind == t("File"):
            files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*.yaml"))
            scope = base / st.selectbox(t("File"), files)
    entries = history(repo.root, scope)
    if not entries:
        st.info(t("No saved changes for this selection yet."))
        return
    chosen = st.selectbox(
        t("Current status"), entries, format_func=_entry_label, key=f"history-entry-{scope}"
    )
    if chosen.files:
        st.code("\n".join(chosen.files), language=None)
    rel = scope.resolve().relative_to(git_root(repo.root) or repo.root.resolve()).as_posix()
    left, right = st.columns(2)
    left.button(
        t("Restore this state"),
        type="primary",
        key="history-restore",
        disabled=locked,
        on_click=_git_action,
        args=(
            lambda: restore_version(repo.root, scope, chosen.rev),
            lambda rev: t("Restored as a new change ({rev}).", rev=rev),
        ),
        help=t(
            (
                "Resets {scope} to the state after this change. That is itself a change and "
                "can be taken back here."
            ),
            scope=md_code(rel),
        ),
    )
    right.button(
        t("Take back this change"),
        key="history-revert",
        disabled=chosen.merge or locked,
        on_click=_git_action,
        args=(
            lambda: revert_commit(repo.root, chosen.rev),
            lambda rev: t("Taken back as a new change ({rev}).", rev=rev),
        ),
        help=t("Undoes exactly this change (e.g. a restore)."),
    )


def _tab_tags(repo: Repository, locked: bool = False) -> None:
    checked = st.session_state.get("tags-server")
    tags = checked if checked is not None else list_tags(repo.root)
    st.button(
        t("Compare with server"),
        key="tags-check",
        icon=":material/refresh:",
        on_click=_tags_check_clicked,
        args=(repo.root,),
        help=t("Asks the server for its tags (network) and shows where each one exists."),
    )
    if checked is None:
        failed = False
    elif tags:
        failed = all(tag.on_server is None for tag in tags)
    else:
        failed = bool(st.session_state.get("tags-server-failed"))
    if failed:
        st.warning(
            t(
                "The server could not be queried (unreachable or not set up). Only the "
                "tags on this computer are shown."
            )
        )
    if tags:
        # st.table interprets Markdown in all cells; names and messages of the tags are
        # controlled by others.
        st.table(
            pd.DataFrame(
                [
                    (md_code(tag.name), _tag_state(tag), tag.target, tag.day, md_code(tag.subject))
                    for tag in tags
                ],
                columns=[t("Tag"), t("Server"), t("Current status"), t("Date"), t("Message")],
            ).set_index(t("Tag"))
        )
    else:
        st.caption(t("No tags yet."))
    local_only = [tag.name for tag in tags if tag.local and tag.on_server is False]
    if local_only:
        st.selectbox(t("Upload tag to server"), local_only, key="tag-upload")
        st.button(
            t("Upload to server"),
            key="tag-upload-go",
            disabled=locked,
            on_click=_tag_upload_go,
            args=(repo.root, st.session_state.get("tag-upload", local_only[0])),
        )
    entries = history(repo.root, limit=60)
    with st.form("tag-set"):
        name = st.text_input(t("New tag"), placeholder="team/2026.21")
        target = st.selectbox(
            t("At state"), entries or [None], format_func=lambda e: _entry_label(e) if e else "HEAD"
        )
        message = st.text_input(t("Message (optional)"))
        if st.form_submit_button(t("Set tag"), disabled=locked):
            _git_action(
                lambda: set_tag(repo.root, name, target.rev if target else "HEAD", message or None),
                lambda _: t("Tag {name} set and shared.", name=md_code(name)),
            )
            _tags_recheck(repo.root)
            st.rerun()
    if tags:
        doomed = st.selectbox(t("Delete tag"), [tag.name for tag in tags])
        # The confirmation belongs to the selected tag: changing the selection requires a new one.
        sure = st.checkbox(
            t("Yes, delete the tag locally and on the server"), key=f"tag-confirm-{doomed}"
        )
        st.button(
            t("Delete tag"),
            disabled=not sure or locked,
            on_click=_tag_delete_go,
            args=(repo.root, doomed),
        )


def page_history(repo: Repository) -> None:
    st.header(t("Changes and history"))
    if problem := st.session_state.pop("commit_error", None):
        if isinstance(problem, GitError):
            _show_problem(problem)
        else:
            st.error(problem)
    if not git_available():
        _show_problem(classify("", missing=True))
        return
    if git_root(repo.root) is None:
        if problem := git_problem(repo.root):
            _show_problem(problem)
        else:
            st.info(t("The data folder is not inside a Git repository – commit not possible."))
        return
    locked = _merge_open(repo)
    if locked:
        st.warning(
            t(
                "A merge is still open. Until it is finished or aborted, restoring, "
                "reverting, discarding and tags are locked (Git would reject them). Please "
                "resolve the conflict first or choose “Abort merge” – both are available "
                "on every team page."
            )
        )
    changes, history_tab, tags = st.tabs([t("Open changes"), t("History"), t("Tags")])
    with changes:
        _tab_changes(repo, locked)
    with history_tab:
        _tab_history(repo, locked)
    with tags:
        _tab_tags(repo, locked)


TEAM_PAGES = {
    "start": page_start,
    "forecast": page_forecast,
    "fehltage": page_absences,
    "sprints": page_calendar,
    "vorplanung": page_preplanning,
    "planning": page_planning,
    "review": page_review,
    "produkte": page_products,
    "tickets": page_tickets,
    "analyse": page_analysis,
    "personen": page_people,
    "produktliste": page_product_list,
    "einstellungen": page_settings,
}
# Pages that show no forecast and therefore only read the reference date from ``fc``.
NO_FORECAST = {"personen", "produktliste", "einstellungen"}
GLOBAL_PAGES = {
    "datenordner": page_data_dir,
    "verlauf": page_history,
    "neues_team": page_new_team,
    "pruefung": page_check,
    "hilfe": page_help,
}


# --- Resolve conflicts and stale inputs -----------------------------------------------------

# State that is kept when files change (everything else is form input).
_KEEP_STATE = {
    "selected_team", "flash", "pending_tags", "commit_message", "commit_message_auto", "use_tags",
    "language",
    "enabled-pages", "sync_result", "sync_earlier", SYNC_RUNNING_KEY, "last_commit",
    "commit_error", "restarting", "update-started",
    "manual-check", "offer-init", "browse-error", "seen-versions", "planning-step",
    "planning-goto", "planning-last-sprint", "board-sprint", "formula-sprint",
    "active-data-dir", "folder-state",
}  # fmt: skip


def _discard_stale_inputs(repo: Repository, team: str) -> None:
    """If the team's files have changed since the last drawing (sharing, other programs), open
    forms are stale: saving would overwrite foreign changes. The inputs are then discarded and
    read again from the files."""
    seen = st.session_state.setdefault("seen-versions", {})
    ident = f"{repo.root.resolve()}|{team}"
    old = seen.get(ident)
    if old is None or old == team_version(repo.team_dir(team)):
        return
    for name in list(st.session_state.keys()):
        if name not in _KEEP_STATE and not str(name).startswith(("git-", "data-", "conf-")):
            del st.session_state[name]
    st.warning(
        t(
            "The data has changed since this page was opened (e.g. by sharing or another "
            "person). Unsaved input was discarded and the page reloaded – please check and "
            "save again."
        )
    )


def _remember_version(repo: Repository, team: str) -> None:
    seen = st.session_state.setdefault("seen-versions", {})
    seen[f"{repo.root.resolve()}|{team}"] = team_version(repo.team_dir(team))


def _show_value(value: object) -> str:
    if value is MISSING:
        return t("(removed)")
    text = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, width=1000).strip()
    # As code: the values also come from the other person.
    return md_code(text.removesuffix("\n...").strip()[:200])


def _conf_key(i: int, j: int | None) -> str:
    return f"conf-{i}-{'file' if j is None else j}"


def _resolve_clicked(root: Path, pending: list[ConflictFile], tags: list[str]) -> None:
    """Adopts the decisions and continues "Save and share"."""
    choices: dict[str, dict[tuple[str, ...], str]] = {}
    for i, cf in enumerate(pending):
        if cf.whole:
            choices[cf.file] = {(): st.session_state.get(_conf_key(i, None))}
        else:
            choices[cf.file] = {
                kc.path: st.session_state.get(_conf_key(i, j)) for j, kc in enumerate(cf.keys)
            }
    for name in [k for k in st.session_state if str(k).startswith("conf-")]:
        del st.session_state[name]
    try:
        resolve_conflicts(root, choices)
    except GitError as e:
        st.session_state["commit_error"] = e
        return
    _sync_clicked(root, tags, push=not _continues_pull_only())


def _restore_clicked(root: Path, file: Path) -> None:
    try:
        restore_file(root, file)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        st.session_state["flash"] = [
            (
                "success",
                t(
                    "{file} reset to the last saved state.",
                    file=md_code(str(file)),
                ),
            )
        ]


def _conflict_diffs(root: Path, file: str) -> None:
    """For each side of the conflict file, what it changed relative to the common state."""
    try:
        mine, theirs = conflict_text_diffs(root, file)
    except GitError:
        return
    if not (mine or theirs):
        return
    with st.expander(t("Difference to the common state")):
        if mine:
            st.caption(t("My change"))
            st.code(_diff_clean(mine), language="diff")
        if theirs:
            st.caption(t("Other change"))
            st.code(_diff_clean(theirs), language="diff")


def page_conflicts(repo: Repository, error: ConflictError | None = None) -> None:
    """Guided recovery: as long as conflicts are open, editing is blocked."""
    st.header(t("Resolve conflicts"))
    st.warning(
        t(
            "Two people changed the same data. Until the conflict is resolved, editing is "
            "locked so that nothing is overwritten. Nothing is lost: both versions are "
            "saved."
        )
    )
    if problem := st.session_state.pop("commit_error", None):
        if isinstance(problem, GitError):
            _show_problem(problem)
        else:
            st.error(problem)
    try:
        state = cached_sync_state(repo.root)
    except GitError as e:
        _show_problem(e)
        return
    tags = st.session_state.get("pending_tags", [])
    if state.unfinished in ("merge", "rebase") or state.conflicts:
        pending = pending_conflicts(repo.root)
        st.markdown(
            t(
                "For each entry: **My change** keeps what you entered, **Other change** "
                "takes what the other person entered. Afterwards everything is merged, "
                "checked and shared."
            )
        )
        ready = True
        show_diffs = st.toggle(
            t("Show line-by-line difference"),
            key="git-conflict-diff",
            help=t(
                "Shows the text of each file before and after (like `git diff`), also for "
                "the minutes."
            ),
        )
        for i, cf in enumerate(pending):
            if not cf.open:
                st.caption(t("{file}: is merged automatically", file=md_code(cf.file)))
                continue
            with st.container(border=True):
                st.markdown(f"**{md_code(cf.file)}**")
                if cf.whole:
                    mine = t("(deleted by me)") if cf.ours_deleted else t("my version")
                    theirs = t("(deleted by others)") if cf.theirs_deleted else t("other version")
                    st.caption(t("The file can only be decided as a whole."))
                    options = {"ours": t("My change: {v}", v=mine),
                               "theirs": t("Other change: {v}", v=theirs)}  # fmt: skip
                    pick = st.radio(
                        cf.file, list(options), format_func=options.get, index=None,
                        key=_conf_key(i, None), label_visibility="collapsed",
                    )  # fmt: skip
                    ready = ready and pick is not None
                if show_diffs:
                    _conflict_diffs(repo.root, cf.file)
                for j, kc in enumerate(cf.keys):
                    options = {
                        "ours": t("My change: {v}", v=_show_value(kc.ours)),
                        "theirs": t("Other change: {v}", v=_show_value(kc.theirs)),
                    }
                    pick = st.radio(
                        md_code(kc.label), list(options), format_func=options.get, index=None,
                        key=_conf_key(i, j),
                    )  # fmt: skip
                    ready = ready and pick is not None
        left, right = st.columns(2)
        left.button(
            t("Apply decisions and share"),
            type="primary",
            disabled=not ready,
            on_click=_resolve_clicked,
            args=(repo.root, pending, list(tags)),
            key="conf-apply",
        )
        right.button(
            t("Abort merge"),
            on_click=_abort_clicked,
            args=(repo.root,),
            key="conf-abort",
            help=t("Discards the merge; your own changes are kept."),
        )
        return
    # Conflict markers without an open merge (e.g. from another program).
    files = error.files if error else []
    st.error(
        t(
            "These files contain conflict markers (`<<<<<<<`), but no merge is running any "
            "more. The file can be reset to the last saved state; changes in it that are "
            "not committed are lost."
        )
    )
    for n, file in enumerate(files):
        left, right = st.columns([4, 2], vertical_alignment="center")
        left.code(str(file), language=None)
        right.button(
            t("Restore last saved state"),
            key=f"conf-restore-{n}",
            on_click=_restore_clicked,
            args=(repo.root, file),
        )


def _merge_open(repo: Repository) -> bool:
    """Is a merge (or rebase) still in progress, or are there conflicts? Then every writing page
    is blocked."""
    if not git_available() or git_root(repo.root) is None:
        return False
    try:
        current = cached_sync_state(repo.root)
    except GitError:
        return False
    return current.unfinished in ("merge", "rebase") or bool(current.conflicts)


# Global pages that create or change files (the others only read or check on their own).
LOCKED_PAGES = {"neues_team"}


def run_page(key: str) -> None:
    """Called by the page files under web/seiten."""
    repo = repository()
    show_flash()  # once, centrally: hints appear on every page, never later elsewhere
    if needs_setup(repo.root):
        page_data_dir(repo, setup=True)
        return
    team = st.session_state.get("selected_team")
    # Open merge: editing is blocked until it is resolved.
    if (key in LOCKED_PAGES or key not in GLOBAL_PAGES) and _merge_open(repo):
        page_conflicts(repo)
        return
    if key in GLOBAL_PAGES:
        GLOBAL_PAGES[key](repo)
        return
    if team is None or not repo.exists(team):
        st.header(t(PAGE_INFO[key][0]))
        st.info(t("No team yet – create a team or import one with an import plugin."))
        page_link("neues_team")
        return
    try:
        data = repo.load_cached(team)
    except ConflictError as e:
        page_conflicts(repo, e)
        return
    except DataError as e:
        st.error(str(e))
        return
    _discard_stale_inputs(repo, team)
    try:
        # The people, products and settings pages only need the reference date.
        fc = Forecast(data, today(), []) if key in NO_FORECAST else build_forecast(data, today())
        TEAM_PAGES[key](repo, data, fc)
    except DataError as e:  # write or delete error outside save(), sprint sequence unclear
        st.error(str(e))
    finally:
        # Also after ``st.rerun()`` (an exception): the own saved state counts as seen,
        # otherwise the next run would take it for a foreign change.
        _remember_version(repo, team)


def run_plugin_page(page: WebPage) -> None:
    """Page of a plugin (see sprintforecast.plugins)."""
    repo = repository()
    show_flash()
    if _merge_open(repo):
        page_conflicts(repo)
        return
    try:
        page.render(repo)
    except FileAccessError as e:  # write or read error in the plugin
        st.error(str(e))
