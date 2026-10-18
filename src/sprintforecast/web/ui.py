# SPDX-License-Identifier: EUPL-1.2
"""Seiten und Seitenleiste der Weboberfläche. Einstieg: web/app.py, Seiten: web/seiten/*.py.

Liest und schreibt dieselben YAML-Dateien wie die Kommandozeile. Konfiguration über
Umgebungsvariablen: SPRINTFORECAST_DATEN (Datenverzeichnis), SPRINTFORECAST_STICHTAG.
Texte sind über i18n.t übersetzbar; interne Spaltenschlüssel der Tabellen bleiben deutsch,
angezeigt werden die übersetzten Beschriftungen.
"""

from __future__ import annotations

import contextlib
import copy
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import streamlit as st
import yaml
from streamlit.runtime.scriptrunner import get_script_run_ctx

from sprintforecast import updater
from sprintforecast.analysis import (
    MIN_SAMPLES,
    average_focus_factor,
    band,
    buffer_hint,
    completion,
    few_samples,
    focus_factor,
    sample_count,
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
from sprintforecast.config import SettingsError, config_dir
from sprintforecast.engine import MIN_THIN_HISTORY, UNSURE_SOURCES, gaps_in_window
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
    NO_WINDOW,
    GitError,
    NewBranchError,
    RemoteAddress,
    cached_pending_changes,
    classify,
    clone_repository,
    commit_directory,
    has_credentials,
    hint_for,
    init_data_repository,
    md_code,
    new_branch_error,
    parse_remote_url,
    remote_special_error,
    secret_in_url_error,
)
from sprintforecast.git import repo_root as git_root
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
    Commit,
    ConflictFile,
    RemoteInfo,
    SyncResult,
    SyncState,
    abort_unfinished,
    cached_remote_info,
    check_remote,
    git_available,
    incoming,
    pending_conflicts,
    reattach,
    resolve_conflicts,
    restore_file,
    set_identity,
    set_remote,
    sync,
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
    command_text,
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
from sprintforecast.report import (
    absence_status_label,
    band_note,
    capacity_label,
    capacity_source_note,
    fmt,
    fmt_capacity,
    pct,
    period,
    render,
    source_label,
    status,
)
from sprintforecast.settings import SETTINGS, Kind, Setting, applicable, changes
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
    absence_matrix,
    absence_sprints,
    apply_calendar,
    apply_product_values,
    board_steps_done,
    calendar_table,
    calendar_to_save,
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
else:  # erst beim ersten Zugriff laden (Kaltstart)
    alt = LazyModule("altair")
    pd = LazyModule("pandas")

# Seiten: Dateiname unter web/seiten → (Titel, Material-Icon). Gruppen für die Navigation.
# Titel und Gruppen sind deutsche Quelltexte und werden bei der Anzeige übersetzt.
PAGES: dict[str, dict[str, tuple[str, str]]] = {
    # Aufgaben im Sprint in zeitlicher Reihenfolge: vorbereiten, Planning, abschließen.
    "Aufgaben": {
        "start": ("Start", ":material/home:"),
        "fehltage": ("Sprint vorbereiten: Fehltage", ":material/event_busy:"),
        "vorplanung": ("PO-Vorplanung", ":material/groups:"),
        "planning": ("Planning", ":material/edit_note:"),
        # Bewusst kein Haken-Symbol (task_alt, check …): In der Schrittleiste steht ein Haken für
        # „erledigt“ – das Seiten-Icon darf ihn nicht vortäuschen.
        "review": ("Sprint abschließen (Review)", ":material/flag:"),
    },
    "Auswertung": {
        "forecast": ("Forecast", ":material/trending_up:"),
        "analyse": ("Analyse", ":material/insights:"),
        "produkte": ("Produktverteilung", ":material/pie_chart:"),
    },
    "Team verwalten": {
        "sprints": ("Sprintkalender", ":material/calendar_month:"),
        "personen": ("Personen", ":material/group:"),
        "produktliste": ("Produkte", ":material/category:"),
        "einstellungen": ("Einstellungen", ":material/tune:"),
        "neues_team": ("Neues Team", ":material/group_add:"),
    },
    "Daten & Hilfe": {
        "datenordner": ("Datenordner", ":material/folder_open:"),
        "verlauf": ("Änderungen und Verlauf", ":material/history:"),
        "pruefung": ("Prüfung", ":material/fact_check:"),
        "hilfe": ("Hilfe", ":material/help:"),
    },
}
PAGE_INFO = {key: info for group in PAGES.values() for key, info in group.items()}
# Seiten, die nur erscheinen, wenn das Team den Funktionsbereich nutzt (Team → Einstellungen).
PAGE_FEATURES = {"vorplanung": "products", "produkte": "products", "produktliste": "products"}


def enabled_pages(repo: Repository) -> set[str]:
    """Seiten für das gewählte Team: Seiten abgeschalteter Funktionsbereiche entfallen."""
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
        return  # Seite gehört zu einem abgeschalteten Funktionsbereich
    title, icon = PAGE_INFO[key]
    st.page_link(page_path(key), label=label or t(title), icon=icon)


def today() -> date:
    raw = os.environ.get(STICHTAG_ENV)
    return date.fromisoformat(raw) if raw else date.today()


def stichtag_problem() -> str | None:
    """Meldung, wenn die Umgebung keinen gültigen Stichtag enthält (sonst scheitert ``today``)."""
    raw = os.environ.get(STICHTAG_ENV)
    if raw:
        try:
            date.fromisoformat(raw)
        except ValueError:
            return t(
                "Die Umgebungsvariable `{name}` enthält „{value}“ – erwartet wird ein Datum im "
                "Format JJJJ-MM-TT. Bitte die Variable korrigieren oder entfernen und die "
                "Weboberfläche neu starten.",
                name=STICHTAG_ENV,
                value=raw,
            )
    return None


# Der Datenordner gehört zur Browser-Sitzung (nicht zum Prozess): Wechselt eine Sitzung den
# Ordner, speichern andere offene Fenster weiter in ihren eigenen.
DATA_DIR_KEY = "active-data-dir"


def data_dir() -> Path:
    """Datenordner dieser Sitzung; beim ersten Aufruf der Vorgabe des Prozesses (Umgebung,
    gemerkter Ordner)."""
    raw = st.session_state.get(DATA_DIR_KEY)
    if raw is None:
        raw = st.session_state[DATA_DIR_KEY] = str(default_data_dir())
    return Path(raw)


def repository() -> Repository:
    return Repository(data_dir())


def apply_language() -> None:
    """Sprache für diesen Durchlauf festlegen (aus Einstellung bzw. Umgebung)."""
    set_language(None)
    set_language(language())


def _settings_problem(error: SettingsError, consequence: str) -> str:
    """Meldung zu nicht speicherbaren Einstellungen: was passiert ist, was unterblieb und was
    zu tun ist."""
    return t(
        "{error}  \n{consequence} Bitte prüfen, ob der Ordner `{folder}` beschreibbar ist "
        "(Schreibrechte, freier Speicherplatz, bei Netzlaufwerken: verbunden), und es dann "
        "noch einmal versuchen.",
        error=error,
        consequence=consequence,
        folder=config_dir(),
    )


def _language_changed() -> None:
    code = st.session_state["language"]
    try:
        save_language(code)
    except SettingsError as e:
        st.session_state["language"] = language()  # die Auswahl zeigt wieder die gültige Sprache
        st.session_state.setdefault("flash", []).append(
            ("error", _settings_problem(e, t("Die Sprache wurde nicht geändert.")))
        )
        return
    set_language(code)


def help_text(key: str) -> str:
    f = FIELDS[key]
    return f"{t(f.what)}\n\n{t('Quelle')}: {t(f.source)}\n\n{t('Beispiel')}: {t(f.example)}"


def _steps_frame(fc: Forecast, entry: TimelineEntry) -> pd.DataFrame:
    return pd.DataFrame([{t("Kennzahl"): s.name, t("Formel"): s.formula} for s in steps(fc, entry)])


# --- Speichern mit Prüfung -----------------------------------------------------------


def _next_step() -> str:
    """Was die Seitenleiste nach dem Speichern anbietet: ``"share"`` („Speichern und teilen“,
    der Datenordner hat einen Server), ``"commit"`` („Änderungen committen“) oder ``""`` (nichts:
    kein Git, ein Problem oder ein Zustand, der erst gelöst werden muss). Nutzt nur den
    Zwischenspeicher, den die Seitenleiste ohnehin füllt; vor dem Schreiben abfragen, denn das
    leert ihn."""
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
    """Gibt es nach dem Speichern etwas zu committen? Dieselbe Abfrage (und derselbe
    Zwischenspeicher) wie in der Seitenleiste. Bei einem Git-Fehler gilt „ja“."""
    try:
        return bool(cached_pending_changes(data_dir()))
    except GitError:
        return True


def _saved_text(names: str, step: str) -> str:
    if step == "share":
        return t(
            "Gespeichert: {names}. Mit **Speichern und teilen** in der Seitenleiste in Git "
            "sichern und mit dem Team teilen (nur lokal: **Änderungen committen**).",
            names=names,
        )
    if step == "commit":
        return t(
            "Gespeichert: {names}. In Git übernehmen mit **Änderungen committen** in der "
            "Seitenleiste.",
            names=names,
        )
    return t("Gespeichert: {names}.", names=names)


def save(
    data_after: TeamData,
    filenames: list[str],
    write: Callable[[], list[Path]],
    tag: str | None = None,
    block_on_all_errors: bool = False,
    flash: bool = False,
) -> bool:
    """Prüft den neuen Stand und schreibt bei Erfolg. Committet wird über die Seitenleiste.

    Mit ``flash`` erscheinen Hinweise erst im nächsten Durchlauf (für ``st.rerun()``)."""

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
        st.error(t("Nicht gespeichert – bitte die Fehler beheben."))
        return False
    step = _next_step()
    try:
        paths = write()
    except FileAccessError as e:
        st.error(str(e))
        return False
    if step and not _has_open_changes():  # der Inhalt war schon so gespeichert: nichts zu tun
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
    """Zeitraum, Arbeitstage und Feiertage eines Sprints."""
    days = team_workdays(data.team, s.start, s.end)
    region, country = data.team.capacity.region, data.team.capacity.country
    hol = [f"{d:%d.%m.} {name}" for d in days if (name := holiday_name(d, region, country))]
    last = f"{days[-1]:%d.%m.%Y}" if days else f"{s.end:%d.%m.%Y}"
    text = t(
        "**{id}**: {start} – {last} (letzter Arbeitstag; der nächste Sprint beginnt am {next}), "
        "{days} Arbeitstage ({week})",
        id=s.id,
        start=f"{s.start:%d.%m.}",
        last=last,
        next=f"{s.end:%d.%m.}",
        days=len(days),
        week=workweek_label(data.team),
    )
    if hol:
        text += t(" · davon Feiertage: {holidays}", holidays=", ".join(hol))
    if not data.sprint(s.id):
        text += t(" · noch keine Sprintdatei")
    return text


# --- Seiten ---------------------------------------------------------------------------


def _signed(value: float) -> str:
    return ("+" if value > 0 else "") + fmt(value)


def _whatif_inputs(fc: Forecast, unit: str, prefix: str = "whatif") -> dict[str, Assumption]:
    """Prognose des Teams für offene Sprints: Commitment − voraussichtlich nicht erledigt +
    zusätzlich erledigt = erwartete Velocity. Nichts wird gespeichert."""
    assumed: dict[str, Assumption] = {}
    for sprint in open_velocity_sprints(fc):
        st.markdown(f"**{t('Sprint {id}', id=sprint.id)}**")
        default_ist = default_forecast_ist(fc, sprint)
        ist_col, open_col, extra_col, result_col = st.columns(4)
        ist = ist_col.number_input(
            t("Commitment ({unit})", unit=unit),
            min_value=0.0,
            value=default_ist,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-ist",
            help=t(
                "Eingeplante Menge des Sprints. Vorbelegt mit dem erfassten Commitment, "
                "sonst mit dem des vorherigen Sprints."
            ),
        )
        not_done = open_col.number_input(
            t("Voraussichtlich nicht erledigt ({unit})", unit=unit),
            min_value=0.0,
            value=None,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-open",
            help=t("Menge der Tickets, die laut Prognose des Teams nicht fertig werden."),
        )
        extra = extra_col.number_input(
            t("Zusätzlich erledigt ({unit})", unit=unit),
            min_value=0.0,
            value=None,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-extra",
            help=t("Menge, die laut Prognose zusätzlich zum Commitment geschafft wird."),
        )
        changed = not_done is not None or extra is not None or ist != default_ist
        if ist is None or not changed:
            result_col.metric(t("Erwartet erledigt"), "–")
            continue
        assumed[sprint.id] = Assumption(ist, not_done, extra)
        result_col.metric(t("Erwartet erledigt"), f"{fmt(assumed[sprint.id].expected, 2)} {unit}")
    return assumed


def _whatif_title() -> str:
    return t("Was-wäre-wenn: Prognose des Teams für offene Sprints")


def _whatif_caption(note: str) -> None:
    """Gemeinsamer Einleitungstext beider Was-wäre-wenn-Panels; ``note`` sagt, was mit der
    Annahme geschieht."""
    st.caption(
        t(
            "Prognose des Teams für einen noch nicht abgeschlossenen Sprint eintragen: "
            "Commitment, was voraussichtlich nicht fertig wird und was zusätzlich geschafft "
            "wird. Der Forecast PLAN der nächsten Sprints wird damit neu berechnet."
        )
        + " "
        + note
    )


@st.fragment
def _whatif_panel(fc: Forecast, upcoming: list[TimelineEntry], unit: str) -> None:
    """Was-wäre-wenn: erwartete erledigte Menge offener Sprints → Forecast PLAN der nächsten."""
    sprints = open_velocity_sprints(fc)
    if not sprints:
        return
    with st.expander(_whatif_title(), icon=":material/science:"):
        _whatif_caption(t("Nichts wird gespeichert."))
        assumed = _whatif_inputs(fc, unit)
        if not assumed:
            return
        scenario = whatif_forecast(fc, assumed)
        plan_now, plan_new = (
            f"Forecast PLAN ({unit})",
            t("Forecast PLAN mit Annahme ({unit})", unit=unit),
        )
        diff = t("Differenz")
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
                    t("n. Velocity-Trend"): fmt(other.result.normalized_velocity.trend, 2)
                    if other
                    else "–",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True)


# Die Icons kommen aus PAGES: Eine Aufgabe hat überall dasselbe Icon (Startseite, Seitenleiste,
# Schrittleiste), und kein Seiten-Icon täuscht einen Haken („erledigt“) vor.
START_TASKS = {
    "prepare": ("Sprint vorbereiten", PAGE_INFO["fehltage"][1]),
    "planning": ("Planning", PAGE_INFO["planning"][1]),
    "review": ("Sprint abschließen", PAGE_INFO["review"][1]),
}


def _start_clicked(page: str, sprint_id: str | None) -> None:
    if sprint_id is not None:
        st.session_state[BOARD_SPRINT] = sprint_id  # die Zielseite öffnet diesen Sprint
    st.session_state["start-goto"] = page


def page_start(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Einstieg über die drei Aufgaben; jede führt zur nächsten sinnvollen Seite."""
    st.header(t("Was möchtest du tun?"))
    if (goto := st.session_state.pop("start-goto", None)) is not None:
        st.switch_page(page_path(goto))
    tasks = start_tasks(
        fc, "vorplanung" in st.session_state.get("enabled-pages", PAGE_INFO) and bool(data.products)
    )
    for col, task in zip(st.columns(len(tasks)), tasks, strict=True):
        title, icon = START_TASKS[task.key]
        with col, st.container(border=True):
            st.subheader(f"{'✅' if task.done else '⬜'} {t(title)}")
            st.write(task.hint)
            st.button(
                t("Öffnen"),
                key=f"start-{task.key}",
                icon=icon,
                type="secondary" if task.done else "primary",
                on_click=_start_clicked,
                args=(task.page, task.sprint_id),
            )
    st.caption(
        t(
            "Danach: den **Forecast** ansehen, mit **Analyse** und **Produktverteilung** auswerten "
            "oder unter **Team verwalten** Sprintkalender, Personen und Produkte pflegen."
        )
    )
    page_link("forecast")


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
            # Kurz halten: Die Zeile unter der Zahl kürzt Streamlit mit „…“; wie viele Sprints die
            # Spanne trägt, steht darum in der Beschriftung darunter.
            delta=(
                t("Spanne {low}–{high}", low=fmt(b.low), high=fmt(b.high))
                if b
                else t("Spanne nicht berechenbar")
            ),
            delta_color="off",
            help=_formula_help(fc, e, "plan")
            + "\n\n"
            + t(
                "Kapazität {capacity} PT · Roadmap {roadmap} · Kleinkram {small}",
                capacity=capacity_label(e),
                roadmap=fmt(e.result.roadmap, 2),
                small=fmt(e.result.small_stuff, 2),
            )
            + "\n\n"
            + t("Fehltage: {state}", state=absence_status_label(e.sprint))
            + (
                "\n\n"
                + t("Prognose beim Planning: {plan} {unit}", plan=fmt(view.frozen), unit=unit)
                if (view := plan_view(e)).frozen is not None
                else ""
            ),
        )
        col.caption(
            t(
                "Kapazität {capacity} PT · Fehltage {state}",
                capacity=capacity_label(e),
                state=absence_status_label(e.sprint),
            )
        )
        if b:
            col.caption(t("Spanne aus den letzten {samples} Sprints", samples=b.samples))
    _forecast_notes(fc, upcoming)

    capacity_col, trend_col, plan_col = (
        t("Kapazität (PT)"),
        t("n. Velocity-Trend"),
        t("Prognose aktuell ({unit})", unit=unit),
    )
    frozen_col, diff_col = t("Prognose beim Planning ({unit})", unit=unit), t("Differenz")
    show_frozen = any(e.sprint.forecast_plan is not None for e in upcoming)
    small_col = t("Kleinkram")
    rows = []
    for e in upcoming:
        view = plan_view(e)
        row = {
            "Sprint": e.sprint.id,
            t("Zeitraum"): period(e),
            "Status": status(fc, e).replace("*", ""),
            t("Fehltage"): absence_status_label(e.sprint),
            capacity_col: capacity_label(e),
            trend_col: fmt(e.result.normalized_velocity.trend, 2),
            plan_col: fmt(e.result.plan),
        }
        if show_frozen:
            row[frozen_col] = fmt(view.frozen)
            row[diff_col] = "–" if view.difference is None else _signed(view.difference)
        rows.append(
            row | {"Roadmap": fmt(e.result.roadmap, 2), small_col: fmt(e.result.small_stuff, 2)}
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            capacity_col: st.column_config.TextColumn(help=general("capacity")),
            trend_col: st.column_config.TextColumn(help=general("trend")),
            plan_col: st.column_config.TextColumn(help=general("plan")),
            "Roadmap": st.column_config.TextColumn(help=general("roadmap")),
            small_col: st.column_config.TextColumn(help=general("small_stuff")),
        },
    )
    _whatif_panel(fc, upcoming, unit)
    for source in UNSURE_SOURCES:
        unsure = [e.sprint.id for e in upcoming if e.result.plan_capacity_source is source]
        if unsure:
            st.warning(
                t(
                    "Für {sprints} sind noch keine Fehltage erfasst – die Kapazität ist nur "
                    "geschätzt ({source}). Auf der Seite **Sprint vorbereiten: Fehltage** "
                    "eintragen.",
                    sprints=", ".join(unsure),
                    source=source_label(source),
                )
            )
    current = fc.current
    if current and current.result.planning_total is not None:
        st.info(
            t(
                "Planning {id}: Summe {total} {unit}, Delta zum Forecast PLAN {delta} {unit}",
                id=current.sprint.id,
                total=fmt(current.result.planning_total, 2),
                delta=fmt(current.result.planning_delta, 2),
                unit=unit,
            )
        )

    st.subheader(t("Verlauf"))
    history = fc.history(10)
    nvel, avg = t("n. Velocity"), t("Ø n. Velocity")
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
                    "Scope Creep": pct(e.result.scope_creep.value),
                }
                for e in history
            ]
        ),
        hide_index=True,
        column_config={
            nvel: st.column_config.TextColumn(help=general("normalized_velocity")),
            avg: st.column_config.TextColumn(help=general("average")),
            "Fulfillment": st.column_config.TextColumn(help=general("fulfillment")),
            "Scope Creep": st.column_config.TextColumn(help=general("scope_creep")),
        },
    )
    _formula_expander(fc)
    chart = _chart(fc, history + [e for e in upcoming if e not in history], unit)
    if chart is None:
        st.info(
            t(
                "Noch keine Werte für ein Diagramm – nach den ersten Sprints Planning und Review "
                "erfassen (oder die Historie über ein Import-Plugin übernehmen)."
            )
        )
    else:
        st.altair_chart(chart, width="stretch")

    if st.button(t("Bericht FORECAST.md schreiben")):
        path = repo.team_dir(team.key) / "FORECAST.md"
        write_text(path, render(fc))
        st.success(t("Geschrieben: {path}", path=path))


def _forecast_notes(fc: Forecast, upcoming: list[TimelineEntry]) -> None:
    """Hinweise zur Belastbarkeit direkt an den Kacheln: wenig Daten, dünne Historie und ein
    Trend-Modus, der Rauschen fortschreibt."""
    if sample_count(fc) < MIN_THIN_HISTORY:
        st.info(
            t(
                "Noch kein Forecast: bisher {samples} Sprint(s) mit Velocity. Ab {min} Sprints "
                "entsteht ein erster Forecast (mit Hinweis „Historie dünn“); die Velocity "
                "im Review erfassen oder die Historie über ein Import-Plugin übernehmen.",
                samples=sample_count(fc),
                min=MIN_THIN_HISTORY,
            )
        )
    if sample_count(fc) and few_samples(fc):
        st.warning(
            t(
                "Wenig Daten: bisher nur {samples} Sprints mit Velocity (ab {min} ist die Spanne "
                "belastbarer). Plan und Spanne sind grobe Hinweise.",
                samples=sample_count(fc),
                min=MIN_SAMPLES,
            )
        )
    series = [x.result.normalized_velocity.value for x in fc.history()]
    if gaps := gaps_in_window(series, fc.data.team.forecast.window):
        st.info(
            t(
                "Lücken: {count} Sprint(s) ohne Velocity im Fenster des Durchschnitts werden "
                "übersprungen; das Fenster reicht entsprechend weiter zurück.",
                count=gaps,
            )
        )
    if any(e.result.trend_fallback for e in upcoming):
        st.info(
            t(
                "Historie dünn: Für den Trend-Modus {mode} reicht die Historie nicht, es gilt "
                "„konstant“ (letzter Durchschnitt).",
                mode=fc.data.team.forecast.trend_mode.value,
            )
        )
    if fc.data.team.forecast.trend_mode is not TrendMode.FLAT:
        st.warning(
            t(
                "Trend-Modus {mode}: schreibt Schwankungen fort und kann steigen oder fallen "
                "(Vorsicht bei langen Horizonten). Robust ist „konstant“ – einstellbar unter "
                "**Team verwalten → Einstellungen**.",
                mode=fc.data.team.forecast.trend_mode.value,
            )
        )


def _formula_help(fc: Forecast, e: TimelineEntry | None, key: str) -> str:
    """Tooltip-Text: symbolische Formel einer Kennzahl."""
    if e is None or (s := formula_step(fc, e, key)) is None:
        return ""
    return s.formula


@st.fragment
def _formula_expander(fc: Forecast) -> None:
    """Ausklappbarer Rechenweg mit allen Kennzahlen eines Sprints."""
    if not sprint_options(fc, None):
        return
    with st.expander(t("Rechenweg: Formeln"), icon=":material/function:"):
        sprint = sprint_select(fc.data, fc, "formula-sprint", "current", None)
        entry = fc.entry(sprint.id) if sprint else None
        if entry is not None:
            _rechenweg(fc, entry)


def _rechenweg(fc: Forecast, entry: TimelineEntry) -> None:
    """Erst eine Erklärung in Alltagssprache, die eingesetzten Werte und Quellen darunter
    auf Wunsch."""
    st.markdown(plain_explanation(fc, entry))
    with st.popover(t("Eingesetzte Werte und Quellen"), icon=":material/table:"):
        st.dataframe(_steps_frame(fc, entry), hide_index=True, width="stretch")


def _next_dates(fc: Forecast) -> None:
    """Die nächsten Sprint-Termine mit dem, was dort zu tun ist."""
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
                t("erfasst ✓") if done else t("Velocity und Erledigt je Produkt erfassen"),
                "review",
            )
        )
    if planning is not None:
        missing = fc.data.sprint(planning.sprint.id) is None
        items.append(
            (
                f"Planning {planning.sprint.id}",
                day_label(planning.sprint.start),
                t("Fehltage → Forecast PLAN → Commitment")
                + (t(" (Fehltage noch nicht erfasst)") if missing else ""),
                "planning",
            )
        )
    if not items:
        return
    with st.container(border=True):
        st.caption(t("Nächste Termine"))
        for title, when, todo, page in items:
            left, middle, right = st.columns([2, 4, 2], vertical_alignment="center")
            left.markdown(f"**{title}**  \n{when}")
            middle.markdown(todo)
            with right:
                page_link(page, t("Öffnen"))


def _chart(fc: Forecast, entries: list[TimelineEntry], unit: str) -> alt.Chart | None:
    """Liniendiagramm; None, solange es keine Werte gibt (leere Daten lässt Altair scheitern)."""
    records = []
    metric, forecast_col = t("Kennzahl"), t("Prognose")
    for e in entries:
        r = e.result
        future = e.sprint.end > fc.today
        values = {
            t("Commitment / PLAN"): r.plan if future else r.forecast_ist.value,
            "Velocity": r.velocity.trend if future else r.velocity.value,
            t("n. Velocity"): r.normalized_velocity.trend
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
    st.header(t("Planbare Fehltage"))
    # Gewählter Sprint und Schrittleiste wie auf den Boards; die Tabelle darunter zeigt weiter
    # mehrere Sprints.
    if (board_sprint := sprint_select(data, fc, "absences-sprint")) is not None:
        _board_nav(data, board_sprint, "fehltage")
    st.markdown(help_text("absences").replace("\n\n", "  \n"))
    if not data.people:
        st.warning(t("Noch keine Personen erfasst – zuerst auf der Seite **Personen** anlegen."))
        return
    count = st.number_input(
        t("Anzahl Sprints"), min_value=1, max_value=26, value=data.team.forecast.horizon + 1
    )
    past = st.number_input(
        t("Vergangene Sprints"),
        min_value=0,
        max_value=26,
        value=0,
        key="absences-past",
        help=t(
            "Zeigt zusätzlich die letzten abgeschlossenen Sprints, um Fehltage nachzutragen. "
            "Sie fließen in die erwarteten Fehltage ein (Einstellung); eine beim Review "
            "eingefrorene Kapazität ändert sich dadurch nicht."
        ),
    )
    sprints = absence_sprints(data, fc, int(count), int(past))
    if not sprints:
        st.info(t("Keine Sprints gefunden."))
        return
    for s in sprints:
        caption = sprint_caption(data, s)
        st.caption(caption + (f" · {t('abgeschlossen')}" if s.end <= fc.today else ""))
    rows = absence_matrix(data.people, sprints)
    column_config: dict[str, Any] = {
        "id": None,
        "Person": st.column_config.TextColumn(t("Person"), disabled=True),
    }
    for s in sprints:
        column_config[s.id] = st.column_config.NumberColumn(
            s.id,
            min_value=0.0,
            max_value=float(len(team_workdays(data.team, s.start, s.end))),
            step=0.5,
            help=t(
                "Fehltage in Arbeitstagen der Person (0,5 = halber Tag), nicht in Personentagen: "
                "Wer in Teilzeit arbeitet, trägt die Tage ein, an denen sonst gearbeitet würde; "
                "die FTE rechnet die Kapazität selbst herunter."
            ),
        )
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config=column_config,
        hide_index=True,
        key=f"absences-{data.team.key}-{sprints[0].id}-{len(sprints)}",
        placeholder="",  # leer = nicht im Team (siehe Hinweis darunter), nicht „None“
    )
    st.caption(t("Leere Zellen: Person ist in diesem Sprint nicht im Team."))
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
                "Für Sprints mit unbekannten Fehltagen werden Fehltage nach den letzten "
                "Sprints mit bestätigten Fehltagen erwartet: Ø {rate} der Kapazität "
                "(Sprints {sprints}).",
                rate=pct(history.rate),
                sprints=", ".join(history.sprints),
            )
            if history.rate is not None
            else t(
                "Noch kein Sprint mit bestätigten Fehltagen in der Historie – bis dahin wird "
                "für unbekannte Fehltage ohne Abzug gerechnet (Kalender und Personenliste)."
            )
        )
    to_save = sprints_to_save(data, sprints, edited_sprints)
    preview = with_sprints(data, to_save)
    fc_preview = build_forecast(preview, fc.today)
    if new := [s.id for s in to_save if data.sprint(s.id) is None]:
        st.caption(
            t("Beim Speichern werden die Sprintdateien {sprints} angelegt.", sprints=", ".join(new))
        )
    st.subheader(
        t("Kapazität und Prognose") + (t(" (Vorschau, noch nicht gespeichert)") if to_save else "")
    )
    if next_sprint := next((s for s in edited_sprints if s.start > fc.today), None):
        next_entry = fc_preview.entry(next_sprint.id)
        if next_entry is not None and next_entry.result.plan is not None:
            st.markdown(
                t(
                    "**In den nächsten Sprint {id} passen {plan} {unit}** "
                    "(Kapazität {capacity} PT)",
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
                    t("Fehltage"): absence_status_label(s),
                    t("Kapazität (PT)"): capacity_label(e) if e else "–",
                    f"Forecast PLAN ({data.team.unit.value})": fmt(e.result.plan) if e else "–",
                }
                for s in edited_sprints
                for e in [fc_preview.entry(s.id)]
            ]
        ),
        hide_index=True,
    )
    # Nach dem Speichern neu laden, damit die Schrittleiste oben den gespeicherten Stand (Haken)
    # zeigt; die Meldung erscheint dann im nächsten Durchlauf (flash).
    if st.button(t("Fehltage speichern"), type="primary", disabled=not to_save) and save(
        preview,
        [f"{s.id}.yaml" for s in to_save],
        lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        flash=True,
    ):
        st.rerun()
    _reset_absences(repo, data, fc.today)


def _absence_states(live: list[Sprint], sprints: list[Sprint]) -> set[str]:
    """Stand der Fehltage je Sprint anzeigen; „niemand fehlt“ lässt sich ausdrücklich
    bestätigen. Liefert die Sprints, für die das (ohne Einträge) bestätigt ist."""
    st.subheader(t("Stand der Fehltage"))
    st.caption(
        t(
            "Sprints mit eingetragenen Fehltagen sind bestätigt. **Niemand fehlt** bestätigt "
            "ausdrücklich, dass es keine Fehltage gibt; ohne Bestätigung gelten die Fehltage als "
            "unbekannt und werden geschätzt."
        )
    )
    frame = pd.DataFrame(
        [
            {
                "Sprint": s.id,
                t("Stand"): absence_status_label(s),
                t("Niemand fehlt"): (
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
            t("Stand"): st.column_config.TextColumn(disabled=True),
            t("Niemand fehlt"): st.column_config.CheckboxColumn(
                help=t("Bestätigt ausdrücklich: In diesem Sprint fehlt niemand.")
            ),
        },
        hide_index=True,
        key=f"absence-states-{sprints[0].id}-{len(sprints)}",
    )
    return {str(r["Sprint"]) for r in edited.to_dict("records") if r[t("Niemand fehlt")]}


def _reset_absences(repo: Repository, data: TeamData, today: date) -> None:
    """Künftige Sprints ohne Informationen zu Fehltagen zurück auf „unbekannt“."""
    resettable = resettable_sprints(data, today)
    if not resettable:
        return
    st.subheader(t("Fehltage zurücksetzen"))
    st.caption(
        t(
            "Für diese Sprints wurden Fehltage bestätigt, sonst ist nichts erfasst. Zurücksetzen "
            "löscht die Sprintdatei: Es liegen dann keine Informationen vor, die Fehltage werden "
            "wieder nach der Historie geschätzt (ohne Historie ohne Abzug); die Kapazität kommt "
            "weiter aus Kalender und Personen."
        )
    )
    chosen = st.multiselect(
        t("Sprints"),
        [s.id for s in resettable],
        default=[s.id for s in resettable],
        key=f"reset-absences-{data.team.key}",
    )
    if st.button(t("Auf „keine Informationen“ zurücksetzen"), disabled=not chosen):
        for sprint_id in chosen:
            repo.delete_sprint(data.team.key, sprint_id)
        st.session_state["flash"] = [
            ("success", t("Zurückgesetzt: {sprints}", sprints=", ".join(chosen)))
        ]
        st.rerun()


def page_calendar(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Sprintkalender"))
    st.markdown(
        t(
            "Künftige Sprints entstehen automatisch aus dem Kalender: Jeder Sprint beginnt am Tag "
            "nach dem letzten Tag des vorherigen und dauert {days} Kalendertage (Einstellung "
            "*Sprintlänge*). Eine Sprintdatei wird angelegt, sobald etwas für den Sprint "
            "gespeichert wird – oder hier mit **Sprints anlegen**.  \n"
            "Weicht ein Sprint ab (z. B. drei Wochen über Weihnachten), den **letzten Tag** "
            "ändern; die folgenden Sprints verschieben sich mit. Arbeitstage zählen laut "
            "Arbeitswoche des Teams ({week}) vom Start bis einschließlich zum letzten Tag, "
            "Feiertage werden erst bei der Kapazität abgezogen.",
            days=data.team.sprint.length_days,
            week=workweek_label(data.team),
        )
    )
    count = st.number_input(t("Anzahl Sprints"), min_value=1, max_value=26, value=6, key="cal-n")
    sprints = absence_sprints(data, fc, int(count))
    if not sprints:
        st.info(t("Keine Sprints gefunden."))
        return
    rows = calendar_table(data, sprints, fc.today)
    for row in rows:
        row["Status"] = t(row["Status"])
    frame = pd.DataFrame(rows, columns=CALENDAR_COLUMNS)
    for col in ("Start", "Letzter Tag"):
        frame[col] = pd.to_datetime(frame[col])
    edited = st.data_editor(
        frame,
        column_config={
            "Sprint": st.column_config.TextColumn(disabled=True),
            "Start": st.column_config.DateColumn(t("Start"), format="DD.MM.YYYY", disabled=True),
            "Letzter Tag": st.column_config.DateColumn(
                t("Letzter Tag"),
                format="DD.MM.YYYY",
                help=t("Der nächste Sprint beginnt am Tag danach."),
            ),
            "Arbeitstage": st.column_config.NumberColumn(
                t("Arbeitstage"),
                disabled=True,
                help=t(
                    "Arbeitstage der Arbeitswoche des Teams ({week}) vom Start bis einschließlich "
                    "zum letzten Tag, ohne Abzug von Feiertagen.",
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
            t("Beim Speichern: ")
            + ", ".join(
                f"{s.id} ({t('neu') if data.sprint(s.id) is None else t('geändert')})"
                for s in to_save
            )
        )
    if st.button(
        t("Sprints anlegen bzw. speichern"), type="primary", disabled=bool(errors) or not to_save
    ):
        preview = with_sprints(data, to_save)
        # Überschneidungen meldet die Prüfung am Nachfolger – ihn mit prüfen.
        ids = [x.id for x in preview.sprints]
        saved = {x.id for x in to_save}
        checked = saved | {ids[i + 1] for i, sid in enumerate(ids[:-1]) if sid in saved}
        save(
            preview,
            [f"{sid}.yaml" for sid in checked],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )


# Der irgendwo bewusst gewählte Sprint gilt auf allen Seiten, die einen Sprint wählen.
BOARD_SPRINT = "board-sprint"


def sprint_options(fc: Forecast, history: int | None = 6) -> list[str]:
    """Wählbare Sprints in fester Reihenfolge: letzte abgeschlossene, laufender, kommende."""
    return [e.sprint.id for e in fc.history(history)] + [e.sprint.id for e in fc.upcoming()]


def sprint_select(
    data: TeamData,
    fc: Forecast,
    key: str,
    purpose: str = "planning",
    history: int | None = 6,
) -> Sprint | None:
    """Gemeinsame Sprintauswahl aller Seiten: gleiche Beschriftung und Reihenfolge. Vorgabe ist
    der zuletzt gewählte Sprint, sonst der Vorschlag der Aufgabe (``purpose``, siehe
    ``Forecast.default_entry``: planning = nächstes Planning, review = offener Rückblick),
    ersatzweise der laufende Sprint."""
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


# Die drei Boards der Produktwerte; mit „Fehltage“ davor die Schrittleiste (Reihenfolge wie in
# Seitenleiste und Startseite: vorbereiten, PO-Vorplanung, Planning, Review).
BOARDS = ("vorplanung", "planning", "review")
BOARD_STEPS = ("fehltage", *BOARDS)

# Schrittleiste: Alle Schritte sind gleich aufgebaut – ein Link in einem Container mit Schlüssel,
# in einem Raster gleich breiter Spalten. Gleiche Höhe, Breite und Ausrichtung; nur die Farbe
# unterscheidet den aktiven Schritt, darum springt beim Wechsel nichts. Der Text bricht nie um
# (Überlanges würde gekürzt; bei der Mindestbreite passt aber auch der längste Titel samt
# Erledigt-Symbol, der Tooltip nennt nur den Stand). Je nach Breite des Bereichs stehen
# alle Schritte nebeneinander, zu zweit oder untereinander – nie überlappend (Container-Abfrage
# statt Fensterbreite, denn die Seitenleiste verändert den Platz).
BOARD_NAV_STEP_REM = 16  # Mindestbreite eines Schritts (der längste Titel samt Symbol passt)
# Zustand „erledigt“: grünes Haken-Symbol am Ende des Schrittnamens (Material-Icon in Markdown-
# Farbe). Offene Schritte tragen kein Zeichen; ihr Zustand steht nur im Tooltip.
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
    """CSS der Schrittleiste; ab der Breite, in der alle ``count`` Schritte nebeneinander
    passen, stehen sie in einer Zeile."""
    wide = count * BOARD_NAV_STEP_REM + (count - 1) * 0.5
    return BOARD_NAV_CSS.replace(
        "</style>",
        f"@container (min-width: {wide:g}rem) {{\n"
        f"    div.st-key-board-nav {{ grid-template-columns: repeat({count}, minmax(0, 1fr)); }}\n"
        "}\n</style>",
    )


def _board_nav(data: TeamData, sprint: Sprint, current: str) -> None:
    """Schrittleiste Fehltage → PO-Vorplanung → Planning → Review mit dem Stand für den
    gewählten Sprint – Wechsel mit einem Klick. Seiten abgeschalteter Funktionsbereiche
    (PO-Vorplanung ohne Produkte) entfallen."""
    done = board_steps_done(data.sprint(sprint.id))
    enabled = st.session_state.get("enabled-pages", BOARD_STEPS)
    steps = [key for key in BOARD_STEPS if key in enabled]
    st.html(_board_nav_css(len(steps)))
    with st.container(key="board-nav-box"), st.container(key="board-nav"):
        for key in steps:
            title, icon = PAGE_INFO[key]
            active = key == current
            if done[key]:
                label = f"{t(title)} {BOARD_STEP_DONE_MARK}"
                hint = t("erfasst für Sprint {id}", id=sprint.id)
            else:  # offen: kein Zeichen, nur der Tooltip sagt es
                label = t(title)
                hint = t("noch offen für Sprint {id}", id=sprint.id)
            with st.container(key=f"board-{'active' if active else 'step'}-{key}"):
                st.page_link(page_path(key), label=label, icon=icon, help=hint, width="stretch")


def _number(label: str, value: float | None, key: str, help: str | None = None) -> float | None:
    return st.number_input(
        label, min_value=0.0, value=value, step=0.25, format="%.2f", key=key, help=help
    )


# --- Produkte: Tabelle und Diagramm ---------------------------------------------------

# Anzeige für nicht erfasste Werte in Tabellen (statt des vorgegebenen „None“).
NO_VALUE = "–"

# Kategorische Farben in fester Reihenfolge (Produkt = Katalogposition); Standard neutral.
SERIES_COLORS = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
]  # fmt: skip
STANDARD_COLOR = "#9a9a94"
MAX_PRODUCT_COLORS = len(SERIES_COLORS)


def _others() -> str:
    return t("Weitere")


def _standard_text(d: Distribution, unit: str) -> str:
    basis = t("Roadmap-Anteil des Forecast PLAN") if d.basis.value == "roadmap" else "Forecast PLAN"
    if d.available is None or not d.active_count:
        return t(
            "Standard: {basis} / Anzahl betreuter Produkte – noch nicht berechenbar.", basis=basis
        )
    if any(r.product.share is not None for r in d.rows if r.active):
        return t(
            "Standard = {basis}{frozen} {available} {unit}: Produkte mit festem Anteil "
            "bekommen diesen, der Rest verteilt sich gleichmäßig auf die übrigen.",
            basis=basis,
            frozen=t(" (Prognose beim Planning, eingefroren)") if d.plan_frozen else "",
            available=fmt(d.available, 2),
            unit=unit,
        )
    return t(
        "Standard = {basis}{frozen} {available} {unit} / {count} betreute Produkte = "
        "**{share} {unit}** je Produkt.",
        basis=basis,
        frozen=t(" (Prognose beim Planning, eingefroren)") if d.plan_frozen else "",
        available=fmt(d.available, 2),
        unit=unit,
        count=d.active_count,
        share=fmt(d.available / d.active_count, 2),
    )


def _distribution_caption(d: Distribution, unit: str) -> str:
    return _standard_text(d, unit) + _frozen_note(d, unit)


def _frozen_note(d: Distribution, unit: str) -> str:
    """Hinweis, wenn die verteilbare Menge beim Planning eingefroren wurde und die aktuelle
    Prognose davon abweicht."""
    if not d.plan_frozen or d.plan is None or d.current_plan is None:
        return ""
    diff = d.current_plan - d.plan
    if abs(diff) < 0.05:
        return ""
    return " " + t(
        "Prognose aktuell: {current} {unit} (Differenz {diff} {unit}).",
        current=fmt(d.current_plan, 2),
        unit=unit,
        diff=_signed(diff),
    )


def _production_hint(d: Distribution, data: TeamData, unit: str) -> None:
    """Kapazität der Personen mit Produktionszugriff und Warnung bei Überplanung – ein
    Engpasshinweis (grobe Näherung über den Kapazitätsanteil), keine Zusage."""
    if not d.features.production:
        return
    planned = d.total("production_planned")
    entered = planned is not None or d.total("production_done") is not None
    if d.production_state == "unconfigured":
        if entered:
            st.info(
                t(
                    "Produktionszugriff: Niemand ist als berechtigt markiert (Team verwalten → "
                    "Personen) – ob die Gruppe die eingeplanten Tickets schafft, lässt sich nicht "
                    "prüfen."
                )
            )
        return
    if d.production_state == "unavailable":
        if planned:
            st.warning(
                t(
                    "Produktionszugriff: Die als berechtigt markierten Personen haben in diesem "
                    "Sprint keine Kapazität (Fehltage, Feiertage oder nicht im Team) – "
                    "eingeplante Tickets mit Produktionszugriff ({planned} {unit}) kann niemand "
                    "bearbeiten (Engpass).",
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
            "Produktionszugriff: {count} Person(en) = {share} der Kapazität → bis zu "
            "**{available} {unit}** möglich (grobe Näherung: Kapazitätsanteil × Forecast PLAN), "
            "eingeplant {planned} {unit}.",
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
                "Mehr Tickets mit Produktionszugriff eingeplant, als die Gruppe schaffen kann "
                "({over} {unit} zu viel) – andere Personen können sie nicht bearbeiten.",
                over=fmt(over, 2),
                unit=unit,
            )
        )


def _product_editor(
    d: Distribution, editable: list[str], key: str, unit: str
) -> list[dict[str, Any]] | None:
    """Tabelle Produkt × Standard/Vorplanung/Planning/Erledigt; ``editable`` sind bearbeitbar."""
    if not d.rows:
        st.info(
            t(
                "Für diesen Sprint sind keine Produkte hinterlegt – Produkte unter **Team "
                "verwalten → Produkte** anlegen (optional)."
            )
        )
        return None
    column_config: dict[str, Any] = {
        "_id": None,
        "Produkt": st.column_config.TextColumn(t("Produkt"), disabled=True),
        "PO": st.column_config.TextColumn(disabled=True) if d.features.po else None,
    }
    for m, label in MEASURES.items():
        column_config[label] = st.column_config.NumberColumn(
            f"{measure_label(m)} ({unit})",
            min_value=0.0,
            step=0.25,
            format="%.2f",
            disabled=m not in editable,
            help=t(FIELDS[m].what)
            if m in FIELDS
            else t("Verfügbare Menge / Anzahl betreuter Produkte"),
        )
    show_production = d.features.production and (
        d.production_share is not None or any(d.has(m) for m in PRODUCTION_MEASURES)
    )
    for m, label in PRODUCTION_MEASURES.items():
        column_config[label] = (
            st.column_config.NumberColumn(
                f"{measure_label(m)} ({unit})",
                min_value=0.0,
                step=0.25,
                format="%.2f",
                disabled=m not in editable,
                help=t(
                    "Teilmenge von Planning bzw. Erledigt: Tickets, die nur Personen mit "
                    "Produktionszugriff bearbeiten können."
                ),
            )
            if show_production
            else None
        )
    frame = pd.DataFrame(product_values_table(d))
    for label in (*MEASURES.values(), *PRODUCTION_MEASURES.values()):
        frame[label] = frame[label].astype("float64").round(2)
    edited = st.data_editor(
        frame,
        column_config=column_config,
        hide_index=True,
        key=key,
        placeholder=NO_VALUE,  # nur die Anzeige: „nicht erfasst“ bleibt in den Daten None
    )
    st.caption(_distribution_caption(d, unit))
    return edited.to_dict("records")


def _product_table(d: Distribution, unit: str) -> bool:
    """Schreibgeschützte Tabelle Produkt × Standard/Vorplanung/Planning/Erledigt (Auswertung).
    False, wenn der Sprint keine Produkte hat."""
    if not d.rows:
        st.info(
            t(
                "Für diesen Sprint sind keine Produkte hinterlegt – Produkte unter **Team "
                "verwalten → Produkte** anlegen (optional)."
            )
        )
        return False
    show_production = d.features.production and (
        d.production_share is not None or any(d.has(m) for m in PRODUCTION_MEASURES)
    )
    columns = dict(MEASURES) | (PRODUCTION_MEASURES if show_production else {})
    frame = pd.DataFrame(product_values_table(d))
    frame = frame.drop(columns=["_id", *([] if d.features.po else ["PO"])])
    frame = frame[["Produkt", *(["PO"] if d.features.po else []), *columns.values()]]
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


def _product_chart(d: Distribution, unit: str) -> alt.Chart | None:
    """Gruppierte Balken je Produkt: Standard (grau), Vorplanung, Planning, Erledigt."""
    product, metric = t("Produkt"), t("Kennzahl")
    records = [
        {product: r.product.name, metric: measure_label(m), unit: value}
        for r in d.rows
        for m in MEASURES
        if (value := r.value(m)) is not None
    ]
    if not records:
        return None
    labels = [measure_label(m) for m in MEASURES]
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
                scale=alt.Scale(domain=labels, range=[STANDARD_COLOR, *SERIES_COLORS[:3]]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[f"{product}:N", f"{metric}:N", alt.Tooltip(f"{unit}:Q", format=".2f")],
        )
    )


def _product_colors(names: list[str]) -> alt.Scale:
    """Farbe folgt dem Produkt (Position in der Produktliste), nicht seinem Rang."""
    others = _others()
    domain = [n for n in names if n != others]
    rng = [SERIES_COLORS[i % MAX_PRODUCT_COLORS] for i in range(len(domain))]
    if others in names:
        domain.append(others)
        rng.append(STANDARD_COLOR)
    return alt.Scale(domain=domain, range=rng)


def _product_name(fc: Forecast, product_id: str, name: str) -> str:
    """Bei mehr als acht Produkten werden die hinteren als „Weitere“ zusammengefasst."""
    products = fc.data.products
    if len(products) <= MAX_PRODUCT_COLORS:
        return name
    index = next((i for i, p in enumerate(products) if p.id == product_id), None)
    return name if index is not None and index < MAX_PRODUCT_COLORS - 1 else _others()


def _product_rank(fc: Forecast, product_id: str) -> int:
    """Position in der Produktliste – bestimmt die Stapelreihenfolge."""
    ids = [p.id for p in fc.data.products]
    return ids.index(product_id) if product_id in ids else len(ids)


def _history_chart(
    fc: Forecast, entries: list[TimelineEntry], measure: str, unit: str
) -> alt.Chart | None:
    product = t("Produkt")
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
    rows = [b for b in all_rows if b.sprints]  # nur Produkte mit mindestens einem Wert
    if not rows:
        st.info(t("Noch kein **Erledigt je Produkt** erfasst – im Review eintragen."))
        return
    product, direction = t("Produkt"), t("Richtung")
    more, less = t("mehr als Standard"), t("weniger als Standard")
    saldo = f"{t('Saldo')} ({unit})"
    frame = pd.DataFrame(
        [
            {
                product: b.product.name,
                "Sprints": b.sprints,
                f"Σ Standard ({unit})": round(b.standard, 2),
                f"Σ {t('Erledigt')} ({unit})": round(b.done, 2),
                saldo: round(b.difference, 2),
                direction: more if b.difference >= 0 else less,
                t("ohne Wert"): b.missing,
            }
            for b in rows
        ]
    )
    missing_col = t("ohne Wert")
    st.altair_chart(
        alt.Chart(frame)
        .mark_bar(cornerRadius=4)
        .encode(
            y=alt.Y(f"{product}:N", sort=[b.product.name for b in rows], title=None),
            x=alt.X(f"{saldo}:Q"),
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
            "Saldo = Σ Erledigt − Σ Standard über die Sprints, in denen für das Produkt Erledigt "
            "erfasst ist. Positiv: Das Produkt hat mehr bekommen als den gleichmäßigen Anteil. "
            "Sprints ohne Wert (nicht erfasst, nicht 0) zählen nicht mit."
        )
    )


def _preview_forecast(data: TeamData, fc: Forecast, base: Sprint, after: Sprint) -> Forecast:
    """Forecast für die Vorschau einer Eingabe. Ist der Sprint noch nicht gespeichert und hat
    die Eingabe nichts geändert, bleibt es beim bisherigen Forecast – eine (leere) Sprintdatei
    würde sonst die Kapazität von der Schätzung auf „alle anwesend“ umstellen."""
    if data.sprint(after.id) is None and after.products == base.products:
        return fc
    return build_forecast(with_sprints(data, [after]), fc.today)


def _base_sprint(data: TeamData, sprint: Sprint) -> Sprint:
    return copy.deepcopy(data.sprint(sprint.id) or sprint)


# --- Planning (geführter Ablauf zum Sprintstart) --------------------------------------

PLANNING_STEPS = ["1 · Fehltage", "2 · Forecast PLAN & Einplanung", "3 · Commitment"]
STEP_KEY = "planning-step"


def _goto(step: int) -> None:
    st.session_state["planning-goto"] = step


def _unfreeze_panel(repo: Repository, data: TeamData, sprint: Sprint, unit: str) -> None:
    """Eingefrorenen Forecast PLAN zur Korrektur eines Fehlers wieder freigeben."""
    with st.expander(
        t("Forecast PLAN {plan} {unit} ist eingefroren", plan=fmt(sprint.forecast_plan), unit=unit),
        icon=":material/lock:",
    ):
        st.warning(
            t(
                "Das Einfrieren hebst du nur auf, um einen **Fehler** zu korrigieren. Tickets, die "
                "nach dem Planning hinzugezogen oder herausgenommen wurden, gehören **nicht "
                "nachträglich ins Planning**, sondern fließen im **Review** ein (Davon nicht "
                "erledigt / Zusätzlich erledigt). Nach dem Aufheben wird der Forecast PLAN neu "
                "berechnet und beim nächsten Speichern des Plannings wieder eingefroren."
            )
        )
        # Nach dem Aufheben die Bestätigung zurücksetzen, damit sie beim nächsten Einfrieren
        # desselben Sprints nicht noch angehakt ist.
        if st.session_state.pop("unfreeze-reset", None) == sprint.id:
            st.session_state[f"unfreeze-{sprint.id}"] = False
        confirmed = st.checkbox(
            t("Ja, es handelt sich um eine Fehlerkorrektur"), key=f"unfreeze-{sprint.id}"
        )
        if st.button(
            t("Einfrieren aufheben"), disabled=not confirmed, key=f"unfreeze-go-{sprint.id}"
        ):
            released = copy.deepcopy(sprint)
            released.forecast_plan = None
            if save(
                with_sprints(data, [released]),
                [f"{released.id}.yaml"],
                lambda: [repo.save_sprint(data.team.key, released)],
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
    # Neuer Sprint gewählt → beim ersten Schritt beginnen.
    if st.session_state.get("planning-last-sprint") != sprint.id:
        st.session_state["planning-last-sprint"] = sprint.id
        st.session_state["planning-goto"] = 0
    if (goto := st.session_state.pop("planning-goto", None)) is not None:
        st.session_state[STEP_KEY] = goto
    st.caption(
        t(
            "Planning am **{day}** · Ablauf: zuerst die bekannten Fehltage, dann mit dem Forecast "
            "PLAN die Tickets einplanen, vor dem Sprintstart das Commitment eintragen.",
            day=day_label(sprint.start),
        )
    )
    step = st.radio(
        t("Schritt"),
        range(len(PLANNING_STEPS)),
        format_func=lambda i: t(PLANNING_STEPS[i]),
        horizontal=True,
        key=STEP_KEY,
        label_visibility="collapsed",
    )
    recorded = data.sprint(sprint.id)
    done = [
        board_steps_done(recorded)["fehltage"],  # wie der Haken der Schrittleiste oben
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


def _planning_absences(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    st.subheader(t("Bekannte Fehltage"))
    st.caption(sprint_caption(data, sprint))
    if not data.people:
        st.warning(
            t(
                "Noch keine Personen erfasst – Kapazität nur geschätzt. Personen unter "
                "**Team verwalten → Personen** anlegen."
            )
        )
        st.button(t("Weiter"), on_click=_goto, args=(1,), type="primary")
        return
    base = _base_sprint(data, sprint)
    shown_sprint = copy.deepcopy(base)
    prefilled = not absences_known(base) and bool(base.expected_absences)
    if prefilled:
        shown_sprint.absences = dict(base.expected_absences)
        st.info(
            t(
                "Vorbelegt mit den angekündigten Fehltagen aus der PO-Vorplanung – bitte "
                "prüfen und bestätigen."
            )
        )
    days = len(team_workdays(data.team, base.start, base.end))
    edited = st.data_editor(
        pd.DataFrame(absence_matrix(data.people, [shown_sprint])),
        column_config={
            "id": None,
            "Person": st.column_config.TextColumn(t("Person"), disabled=True),
            base.id: st.column_config.NumberColumn(
                t("Fehltage"),
                min_value=0.0,
                max_value=float(days),
                step=0.5,
                help=help_text("absences"),
            ),
        },
        hide_index=True,
        key=f"planning-absences-{base.id}",
        placeholder="",  # leer = Person ist in diesem Sprint nicht im Team, nicht „None“
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
                "Fehltage für {id}: {state}. Gerechnet wird mit {capacity} PT. Bekannte Fehltage "
                "bitte eintragen – oder ausdrücklich bestätigen, dass niemand fehlt. „Weiter ohne "
                "Bestätigung“ lässt die Fehltage unbekannt.",
                id=after.id,
                state=absence_status_label(after),
                capacity=capacity_label(entry) if entry else "–",
            )
        )
    left, right = st.columns(2)
    left.metric(
        t("Kapazität (PT)"),
        fmt_capacity(entry.result.plan_capacity, entry.capacity_digits) if entry else "–",
        help=_formula_help(fc_after, entry, "capacity"),
    )
    right.metric(
        t("Prognose aktuell ({unit})", unit=data.team.unit.value),
        fmt(entry.result.plan) if entry else "–",
        help=_formula_help(fc_after, entry, "plan"),
    )
    if after.capacity is not None:
        st.info(
            t(
                "In der Sprintdatei ist eine feste Kapazität ({capacity} PT) eingetragen – sie "
                "gilt statt der Berechnung aus den Fehltagen.",
                capacity=fmt_capacity(after.capacity, data.team.capacity.rounding),
            )
        )
    if to_save:
        if st.button(t("Fehltage speichern und weiter"), type="primary"):
            ok = save(
                preview,
                [f"{after.id}.yaml"],
                lambda: [repo.save_sprint(data.team.key, after)],
                flash=True,
            )
            if ok:
                _goto(1)
                st.rerun()
    elif unconfirmed:
        nobody, skip = st.columns(2)
        if nobody.button(t("Niemand fehlt – bestätigen und weiter"), type="primary"):
            confirmed = copy.deepcopy(after)
            confirmed.absence_state = AbsenceState.CONFIRMED
            ok = save(
                with_sprints(data, [confirmed]),
                [f"{after.id}.yaml"],
                lambda: [repo.save_sprint(data.team.key, confirmed)],
                flash=True,
            )
            if ok:
                _goto(1)
                st.rerun()
        skip.button(t("Weiter ohne Bestätigung"), on_click=_goto, args=(1,))
    else:
        st.button(t("Weiter"), on_click=_goto, args=(1,), type="primary")


def _planning_plan(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    entry = fc.entry(sprint.id)
    st.subheader(t("Forecast PLAN – so viel einplanen"))
    if entry is None:
        st.info(t("Für diesen Sprint gibt es keine Prognose."))
        return
    r = entry.result
    view = plan_view(entry)
    cols = st.columns(5 if view.frozen is not None else 4)
    cols[0].metric(
        t("Kapazität (PT)"),
        fmt_capacity(r.plan_capacity, entry.capacity_digits),
        # Die Quelle steht unter dem Wert (nicht im Wert): sonst wird die Zahl abgeschnitten.
        delta=capacity_source_note(entry) or None,
        delta_color="off",
        delta_arrow="off",
        help=t("Quelle: {source}", source=source_label(r.plan_capacity_source) or "–")
        + "\n\n"
        + _formula_help(fc, entry, "capacity"),
    )
    cols[1].metric(
        t("Prognose aktuell ({unit})", unit=unit),
        fmt(r.plan),
        help=_formula_help(fc, entry, "plan"),
    )
    rest = cols[2:]
    if view.frozen is not None:
        rest[0].metric(
            t("Prognose beim Planning ({unit})", unit=unit),
            fmt(view.frozen),
            delta=None if view.difference is None else _signed(view.difference),
            delta_color="off",
            help=t(
                "Beim Planning eingefroren (Basis der Standardverteilung je Produkt). Die Zahl "
                "darunter ist die Differenz der aktuellen Prognose zu diesem Stand."
            ),
        )
        rest = rest[1:]
    rest[0].metric(
        f"Roadmap ({pct(data.team.forecast.roadmap_share)})",
        fmt(r.roadmap, 2),
        help=_formula_help(fc, entry, "roadmap"),
    )
    rest[1].metric(
        t("Kleinkram"), fmt(r.small_stuff, 2), help=_formula_help(fc, entry, "small_stuff")
    )
    if note := band_note(fc, entry):
        st.caption(note)
    with st.expander(t("Rechenweg"), icon=":material/function:"):
        _rechenweg(fc, entry)
    if r.plan_capacity_source in UNSURE_SOURCES:
        st.warning(t("Noch keine Fehltage erfasst – die Kapazität ist nur geschätzt."))
        st.button(t("Zurück zu den Fehltagen"), on_click=_goto, args=(0,))
    features = data.team.features
    if features.products and data.products:
        st.subheader(t("Einplanung je Produkt"))
        d = distribution(fc, entry)
        carried = False
        for row in d.rows:
            if row.planned is None and row.preplanned is not None:
                row.planned = row.preplanned
                carried = True
        if carried:
            st.caption(
                t(
                    "Die Einplanung ist mit der letzten PO-Vorplanung vorbelegt – bitte prüfen, "
                    "anpassen und speichern."
                )
            )
        rows = _product_editor(
            d,
            ["preplanned", "planned", "production_planned"],
            f"planning-products-{sprint.id}",
            unit,
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
            planned = d_preview.total("planned")
            if planned is not None and r.plan is not None:
                rest = r.plan - planned
                (st.success if rest >= 0 else st.warning)(
                    t(
                        "Eingeplant je Produkt: **{planned} {unit}** von {plan} {unit} – ",
                        planned=fmt(planned, 2),
                        plan=fmt(r.plan),
                        unit=unit,
                    )
                    + (
                        t("noch {rest} frei.", rest=fmt(rest, 2))
                        if rest >= 0
                        else t("{rest} zu viel.", rest=fmt(-rest, 2))
                    )
                )
            if chart := _product_chart(d_preview, unit):
                st.altair_chart(chart, width="stretch")
            if after.products != base.products or data.sprint(after.id) is None:
                if st.button(t("Produktwerte speichern und weiter"), type="primary"):
                    ok = save(
                        preview,
                        [f"{after.id}.yaml"],
                        lambda: [repo.save_sprint(data.team.key, after)],
                        flash=True,
                    )
                    if ok:
                        _goto(2)
                        st.rerun()
                return
    elif features.products:
        st.caption(
            t(
                "Optional: Mit Produkten unter **Team verwalten → Produkte** lässt sich hier die "
                "Verteilung auf die Produkte planen und auswerten."
            )
        )
    elif features.production and _planning_production(repo, data, fc, sprint, entry):
        return
    st.button(t("Weiter"), on_click=_goto, args=(2,), type="primary")


def _planning_production(
    repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint, entry: TimelineEntry
) -> bool:
    """Teams ohne Produktverteilung: Menge mit Produktionszugriff je Sprint. True, wenn eine
    Änderung gespeichert werden kann (der Aufrufer zeigt dann kein „Weiter“)."""
    unit = data.team.unit.value
    st.subheader(t("Themen mit Produktionszugriff"))
    base = _base_sprint(data, sprint)
    planned = _number(
        t("Davon mit Produktionszugriff ({unit})", unit=unit),
        base.production_planned,
        f"production-planned-{base.id}",
        t(
            "Teilmenge des Plannings: Tickets, die nur Personen mit Produktionszugriff "
            "bearbeiten können."
        ),
    )
    after = copy.deepcopy(base)
    after.production_planned = planned
    preview = with_sprints(data, [after])
    fc_preview = _preview_forecast(data, fc, base, after)
    _production_hint(distribution(fc_preview, fc_preview.entry(after.id) or entry), data, unit)
    if after.production_planned == base.production_planned:
        return False
    if st.button(t("Speichern und weiter"), type="primary", key="production-planned-save"):
        ok = save(
            preview,
            [f"{after.id}.yaml"],
            lambda: [repo.save_sprint(data.team.key, after)],
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
    st.subheader(t("Commitment – vor dem Sprintstart"))
    if entry:
        st.caption(
            t(
                "Prognose aktuell {plan} {unit}{frozen} · Kapazität {capacity} PT",
                plan=fmt(entry.result.plan),
                frozen=(
                    t(
                        ", beim Planning {frozen} {unit}",
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
            t("Summe Planning je Produkt: {total} {unit}", total=fmt(sum(planned), 2), unit=unit)
        )
    with st.form(f"planning-{sprint.id}"):
        forecast_ist = _number(
            t("Commitment ({unit})", unit=unit),
            sprint.forecast_ist,
            f"fist-{sprint.id}",
            help_text("forecast_ist"),
        )
        p = sprint.planning or Planning()
        with st.expander(t("Kontrollrechnung (optional)"), expanded=sprint.planning is not None):
            st.caption(
                t(
                    "Prüft, ob die Planung in den Forecast PLAN passt: Delta = Forecast PLAN − "
                    "(Überkipper + Backlog − Korrekturen). Wirkt sich auf keine andere Kennzahl "
                    "aus. Ist das Commitment leer, wird es mit Überkipper + Backlog vorbelegt; "
                    "weicht er davon ab, erscheint ein Hinweis."
                )
            )
            carryover = _number(
                t("Überkipper ({unit})", unit=unit),
                p.carryover or None,
                f"carry-{sprint.id}",
                help_text("carryover"),
            )
            backlog = _number(
                f"Backlog ({unit})", p.backlog or None, f"backlog-{sprint.id}", help_text("backlog")
            )
            corrections_raw = st.text_input(
                t("Korrekturen Restaufwände ({unit})", unit=unit),
                " ".join(f"{c:g}" for c in p.corrections),
                help=help_text("corrections"),
            )
        refreeze = False
        if offer := refreeze_offer(sprint, entry):
            refreeze = st.checkbox(
                t(
                    "Forecast PLAN neu einfrieren ({frozen} → {current} {unit})",
                    frozen=fmt(offer[0]),
                    current=fmt(offer[1]),
                    unit=unit,
                ),
                value=False,
                key=f"refreeze-{sprint.id}",
                help=t(
                    "Der beim ersten Planning eingefrorene Wert ist die Basis der "
                    "Standardverteilung je Produkt und bleibt sonst unverändert."
                ),
            )
        submitted = st.form_submit_button(t("Planning speichern"), type="primary")
    if not submitted:
        return
    try:
        corrections = parse_numbers(corrections_raw)
    except ValueError:
        st.error(t("Korrekturen: bitte endliche Zahlen mit Leerzeichen getrennt eingeben."))
        return
    prefilled = apply_planning(
        sprint,
        forecast_ist,
        Planning(carryover=carryover or 0.0, backlog=backlog or 0.0, corrections=corrections),
    )
    freeze_plan(sprint, entry, fc.today, refreeze=refreeze)
    prefill_note = (
        t(
            "Commitment aus Überkipper + Backlog übernommen: {value} {unit}",
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
        after,
        [f"{sprint.id}.yaml"],
        lambda: [repo.save_sprint(data.team.key, sprint)],
        flash=True,
    ):
        # Die Hinweise erscheinen im nächsten Durchlauf; er zeichnet auch die Schrittleiste neu.
        flash = st.session_state.setdefault("flash", [])
        if (
            prefill_note
        ):  # im nächsten Durchlauf ist das Commitment gespeichert, kein Vorschlag mehr
            flash.append(("info", prefill_note))
        e = build_forecast(after, fc.today).entry(sprint.id)
        if e and e.result.planning_total is not None:
            flash.append(
                (
                    "info",
                    t(
                        "Planning-Summe {total} {unit} · Forecast PLAN {plan} {unit} · Delta "
                        "{delta} {unit}",
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
                    t("Planning {id} vollständig – der Sprint kann starten.", id=sprint.id),
                )
            )
        st.rerun()


def _review_prognosis_hint(sprint: Sprint, unit: str) -> None:
    """Letzte Prognose des Teams aus der PO-Vorplanung – zum Vergleich mit dem Ergebnis."""
    if not sprint.prognoses:
        return
    last = sprint.prognoses[-1]
    text = t(
        "Letzte Prognose ({at}): erwartet erledigt **{expected} {unit}**",
        at=f"{last.at:%d.%m.%Y %H:%M}",
        expected=fmt(last.expected_done, 2),
        unit=unit,
    )
    if last.comment:
        text += f" – {last.comment}"
    if sprint.velocity is not None and last.expected_done is not None:
        text += " · " + t(
            "Abweichung zur Velocity: {diff} {unit}",
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
    unit = data.team.unit.value
    computed = sprint_capacity(data.team, data.people, sprint).rounded if data.people else None
    st.caption(
        t(
            "Im Review wird festgehalten, was der Sprint geschafft hat: erledigte Menge, was "
            "nicht fertig wurde und was zusätzlich erledigt wurde. Nach dem Planning "
            "hinzugezogene oder herausgenommene Tickets fließen hier ein – nicht nachträglich "
            "ins Planning."
        )
    )
    _review_prognosis_hint(sprint, unit)
    with st.form(f"review-{sprint.id}"):
        velocity = _number(
            t("Geschafft – Velocity ({unit})", unit=unit),
            sprint.velocity,
            f"velocity-{sprint.id}",
            help_text("velocity"),
        )
        not_done_col, extra_col = st.columns(2)
        not_done = not_done_col.number_input(
            t("Davon nicht erledigt ({unit})", unit=unit),
            key=f"not-done-{sprint.id}",
            min_value=0.0,
            value=sprint.not_done,
            step=0.25,
            format="%.2f",
            help=t(
                "Menge des Commitments, die im Sprint nicht fertig wurde. Optional – "
                "Velocity = Commitment − nicht erledigt + zusätzlich erledigt."
            ),
        )
        additional = extra_col.number_input(
            t("Zusätzlich erledigt ({unit})", unit=unit),
            key=f"additional-done-{sprint.id}",
            min_value=0.0,
            value=sprint.additional_done,
            step=0.25,
            format="%.2f",
            help=t("Menge, die zusätzlich zum Commitment geschafft wurde. Optional."),
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
            st.markdown(f"**{t('Erledigt je Produkt')}**")
            product_rows = _product_editor(
                distribution(fc, entry), review_measures, f"review-products-{sprint.id}", unit
            )
        elif data.team.features.production and not data.team.features.products:
            st.markdown(f"**{t('Themen mit Produktionszugriff')}**")
            production_done = _number(
                t("Davon mit Produktionszugriff erledigt ({unit})", unit=unit),
                sprint.production_done,
                f"production-done-{sprint.id}",
                t(
                    "Teilmenge der Velocity: Tickets, die nur Personen mit Produktionszugriff "
                    "bearbeiten können."
                ),
            )
        st.markdown(f"**{t('Personentage des Sprints')}**")
        capacity = _number(
            t("Verfügbare Personentage (PT) – wird eingefroren"),
            sprint.capacity if sprint.capacity is not None else computed,
            f"capacity-{sprint.id}",
            t(
                "Nur die Bezugsgröße, um die geschaffte Menge zwischen Sprints vergleichbar zu "
                "machen (Velocity / Personentage). Vorbelegt laut Personenliste und Fehltagen; "
                "wird hier eingefroren."
            )
            + (
                "\n\n"
                + t(
                    "Laut Personenliste und Fehltagen: {capacity} PT",
                    capacity=fmt_capacity(computed, data.team.capacity.rounding),
                )
                if computed
                else ""
            ),
        )
        tag = st.checkbox(
            t("Beim Commit Tag {tag} setzen", tag=f"{data.team.key}/{sprint.id}"),
            value=True,
            key=f"review-tag-{sprint.id}",
        )
        submitted = st.form_submit_button(t("Review speichern"), type="primary")
    if not submitted:
        return
    if capacity is None:
        st.error(t("Bitte die verfügbaren Personentage angeben."))
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
    if save(
        with_sprints(data, [sprint]),
        [f"{sprint.id}.yaml"],
        lambda: [repo.save_sprint(data.team.key, sprint)],
        tag=f"{data.team.key}/{sprint.id}" if tag else None,
        flash=True,
    ):
        st.rerun()  # die Schrittleiste oben zeigt den gespeicherten Stand


def page_analysis(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Analyse"))
    st.caption(
        t(
            "Ergänzt den Forecast. Die Werte auf der Seite **Forecast** (Forecast PLAN, Roadmap, "
            "Kleinkram) bleiben unverändert."
        )
    )
    unit = data.team.unit.value
    window = data.team.forecast.window

    st.subheader(t("Bandbreite"))
    rows = []
    for e in fc.upcoming():
        b = band(fc, e)
        rows.append(
            {
                "Sprint": e.sprint.id,
                f"Forecast PLAN ({unit})": fmt(e.result.plan),
                t("konservativ"): fmt(b.low if b else None),
                t("mittel"): fmt(b.mid if b else None),
                t("optimistisch"): fmt(b.high if b else None),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(
        t(
            "Forecast mit der niedrigsten, mittleren (Median) und höchsten normierten Velocity "
            "der letzten {window} Sprints statt des Trends – zeigt, wie stark die Planung "
            "schwanken kann.",
            window=window,
        )
    )

    st.subheader(t("Wann ist es fertig?"))
    share = data.team.forecast.roadmap_share
    with st.form("completion"):
        rest = st.number_input(
            t("Restmenge ({unit})", unit=unit), min_value=0.0, value=None, step=1.0, key="rest",
            help=t("Noch offene Arbeit, z. B. die Summe eines Roadmap-Themas."),
        )  # fmt: skip
        basis = st.radio(
            t("Verfügbar je Sprint"),
            ["roadmap", "total"],
            format_func=lambda k: (
                t("Roadmap-Anteil ({share})", share=pct(share))
                if k == "roadmap"
                else t("gesamter Forecast")
            ),
            horizontal=True,
            key="basis",
        )
        project = st.number_input(
            t("Projektanteil (%)"),
            min_value=1.0,
            max_value=100.0,
            value=100.0,
            step=5.0,
            key="project_share",
            help=t(
                "Welcher Teil der oben gewählten Kapazität in dieses Projekt fließt – z. B. 50, "
                "wenn parallel ein zweites Roadmap-Thema gleich stark bearbeitet wird."
            ),
        )
        submitted = st.form_submit_button(t("Berechnen"), type="primary")
    if submitted and rest:
        basis_share = share if basis == "roadmap" else 1.0
        used_share = basis_share * project / 100
        result = completion(data, fc.today, rest, used_share)
        if result is None:
            st.warning(t("Zu wenig Historie für eine Fertigstellungsprognose."))
        else:
            # Der Wert bleibt kurz („später als 2027.21“), damit er nicht abgeschnitten wird; die
            # Länge der Simulation steht darunter.
            later = t("später als {last}", last=result.sprints[-1] if result.sprints else "–")
            horizon = t("Simulation über {count} Sprints", count=len(result.sprints))
            left, middle, right = st.columns(3)
            left.metric(
                t("je Sprint für das Projekt ({share} des Forecasts)", share=pct(used_share)),
                f"≈ {fmt(result.per_sprint, 1)} {unit}",
                help=t("Median der normierten Velocity × typische Kapazität × Anteil."),
            )
            frequency = t(
                "Modellabhängige Häufigkeit in der Simulation aus {count} Sprints Historie – keine "
                "Zusage.",
                count=result.samples,
            )
            for column, label, reached in (
                (middle, t("in 50 % der Simulationen"), result.p50),
                (right, t("in 85 % der Simulationen"), result.p85),
            ):
                column.metric(
                    label,
                    reached or later,
                    delta=None if reached else horizon,
                    delta_color="off",
                    delta_arrow="off",
                    help=frequency,
                )
            done_col = t("fertig bis dahin")
            chart = pd.DataFrame({"Sprint": result.sprints, done_col: result.cumulative})
            # vom ersten Sprint mit Chance bis zum ersten mit (fast) 100 %
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
                        title=t("Wahrscheinlichkeit"),
                    ),
                    tooltip=["Sprint:N", alt.Tooltip(f"{done_col}:Q", format=".0%")],
                ),
                width="stretch",
            )
            caption = t(
                "Monte-Carlo-Simulation ({runs} Durchläufe, Stichprobe: {samples} Sprints) ab "
                "dem nächsten Sprint: je Sprint eine zufällige normierte Velocity der letzten "
                "Sprints × Kapazität. Die Prozentwerte sind modellabhängige Häufigkeiten, keine "
                "Zusagen.",
                runs=f"{result.runs:,}",
                samples=result.samples,
            )
            if result.samples < MIN_SAMPLES:
                st.warning(
                    t(
                        "Wenig Daten: Die Simulation zieht aus nur {samples} Sprints (ab {min} "
                        "sind Aussagen belastbarer). Die Häufigkeiten sind grobe Hinweise.",
                        samples=result.samples,
                        min=MIN_SAMPLES,
                    )
                )
            if result.trend_capacity_sprints:
                listed = ", ".join(result.trend_capacity_sprints[:4])
                if len(result.trend_capacity_sprints) > 4:
                    listed += " …"
                caption += t(
                    " Ohne Personenliste mit Ø Kapazität gerechnet: {sprints}.", sprints=listed
                )
            if not result.p85:
                caption += t(
                    " Die Simulation reicht höchstens {count} Sprints in die Zukunft; die "
                    "Restmenge ist dafür zu groß oder der Anteil je Sprint zu klein.",
                    count=len(result.sprints),
                )
            st.caption(caption)

    st.subheader(t("Fokusfaktor"))
    st.metric(
        t("Ø Fokusfaktor (letzte {window} Sprints)", window=window),
        fmt(average_focus_factor(fc), 2),
        help=t(
            "Velocity / Kapazität. Dieselbe Größe wie die normierte Velocity, nur ohne "
            "Referenzkapazität (n. Velocity = Fokusfaktor × Referenzkapazität). Er hängt von "
            "der Schätzeinheit ab (bei Story Points z. B. von der Schätzskala des Teams) und "
            "ist daher nicht zwischen Teams vergleichbar – sinnvoll ist der Verlauf im eigenen "
            "Team. Literaturwerte (0,6–0,8) beziehen sich meist auf reine Arbeitszeit; zählt "
            "die Kapazität alle Anwesenheitstage, liegen die Werte niedriger."
        ),
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"Sprint": e.sprint.id, t("Fokusfaktor"): fmt(focus_factor(e), 2)}
                for e in fc.history(window)
            ]
        ),
        hide_index=True,
    )

    st.subheader(t("Puffer für Ungeplantes"))
    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        st.info(t("Scope Creep wurde zuletzt nicht erfasst – keine Empfehlung möglich."))
    else:
        text = t(
            "Ø Scope Creep der letzten {count} Sprints: **{scope}** des Commitments = "
            "**{late}** des Forecast PLAN · eingestellter Kleinkram-Anteil (bezogen auf den "
            "Forecast PLAN): **{small}**",
            count=hint.samples,
            scope=pct(hint.average_scope_creep),
            late=pct(hint.average_late_share),
            small=pct(hint.configured_small_stuff),
        )
        if hint.buffer_too_small:
            st.warning(text + t(" – der Puffer ist kleiner als der ungeplante Anteil."))
        elif hint.sufficient_data:
            st.success(text + t(" – passt."))
        else:
            st.info(text + t(" – zu wenige Werte für eine Empfehlung."))


def _prognosis_history(data: TeamData, sprints: list[Sprint], unit: str) -> None:
    """Bisherige Prognosen der offenen Sprints aus früheren Vorplanungen."""
    if not any((recorded := data.sprint(sprint.id)) and recorded.prognoses for sprint in sprints):
        return
    details = st.toggle(t("Alle Details der Prognosen"), key="prognosis-details")
    rows = []
    for sprint in sprints:
        recorded = data.sprint(sprint.id)
        for p in recorded.prognoses if recorded else []:
            row = {
                t("Zeitpunkt"): f"{p.at:%d.%m.%Y %H:%M}",
                "Sprint": sprint.id,
                t("Kommentar"): p.comment or "",
            }
            if details:
                row |= {
                    f"Commitment ({unit})": fmt(p.forecast_ist, 2),
                    t("nicht erledigt"): fmt(p.not_done, 2),
                    t("zusätzlich erledigt"): fmt(p.additional_done, 2),
                }
            row |= {
                t("erwartet erledigt"): fmt(p.expected_done, 2),
                t("Forecast PLAN {id}", id=p.target or "–"): fmt(p.plan),
            }
            rows.append(row)
    if rows:
        st.markdown(f"**{t('Bisherige Prognosen')}**")
        st.dataframe(pd.DataFrame(rows[::-1]), hide_index=True)


def _available_text(d: Distribution, data: TeamData, unit: str) -> str:
    """Woraus sich die verteilbare Menge ergibt (Forecast PLAN bzw. dessen Roadmap-Anteil)."""
    return _available_base(d, data, unit) + _frozen_note(d, unit)


def _available_base(d: Distribution, data: TeamData, unit: str) -> str:
    if d.plan is None:
        return t("Für diesen Sprint ist noch kein Forecast PLAN berechenbar.")
    frozen = t(" (Prognose beim Planning, eingefroren)") if d.plan_frozen else ""
    if d.basis is ProductBasis.ROADMAP:
        share = data.team.forecast.roadmap_share
        return t(
            "Verteilbar = Roadmap-Anteil des Forecast PLAN{frozen}: {plan} {unit} × {share} = "
            "{available} {unit}. Der Kleinkram-Anteil wird nicht auf Produkte verteilt "
            "(Einstellung „Standardverteilung je Produkt aus“).",
            frozen=frozen,
            plan=fmt(d.plan, 2),
            unit=unit,
            share=pct(share),
            available=fmt(d.available, 2),
        )
    return t(
        "Verteilbar = Forecast PLAN{frozen}: {plan} {unit}.",
        frozen=frozen,
        plan=fmt(d.plan, 2),
        unit=unit,
    )


def page_preplanning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Board der POs vor dem Planning: je Produkt vorsehen, was in den Sprint soll."""
    st.header(t("PO-Vorplanung"))
    unit = data.team.unit.value
    if not data.products:
        st.info(
            t(
                "Noch keine Produkte erfasst. Die PO-Vorplanung verteilt die Sprint-Menge auf die "
                "Produkte des Teams."
            )
        )
        page_link("produktliste", t("Produkte anlegen"))
        return
    sprint = sprint_select(data, fc, "vorplanung-sprint")
    entry = fc.entry(sprint.id) if sprint else None
    if sprint is None or entry is None:
        return
    _board_nav(data, sprint, "vorplanung")
    st.caption(
        t(
            "Vor dem Planning tragen die POs ein, wie viel sie je Produkt für den Sprint vorsehen. "
            "Zum Vergleich steht der **Standard** – die gleichmäßige Verteilung bzw. der "
            "vereinbarte Anteil des Produkts."
        )
    )
    headline = st.container()
    assumed: dict[str, Assumption] = {}
    comment = ""
    if open_velocity_sprints(fc):
        with st.expander(_whatif_title(), icon=":material/science:"):
            _whatif_caption(
                t(
                    "Das gilt nur für diese Ansicht; mit **Vorplanung speichern** wird die "
                    "Annahme samt Kommentar als Prognose festgehalten. Die Velocity selbst wird "
                    "erst im Review erfasst."
                )
            )
            assumed = _whatif_inputs(fc, unit, "vorplanung-whatif")
            comment = (
                st.text_input(
                    t("Kommentar zur Prognose"),
                    key=f"vorplanung-comment-{sprint.id}",
                    placeholder=t(
                        "Woher stammt die Annahme? z. B. Prognose aus dem Daily vom 16.10."
                    ),
                )
                if assumed
                else ""
            )
            _prognosis_history(data, list(open_velocity_sprints(fc)), unit)
    expected = dict(sprint.expected_absences)
    if data.people:
        with st.expander(t("Angekündigte Fehltage"), icon=":material/event_busy:"):
            st.caption(
                t(
                    "Schon bekannte oder erwartete Fehltage für diesen Sprint. Sie sind eine "
                    "Prognose für die POs und wirken auf Kapazität und Forecast PLAN, bis im "
                    "Planning die Fehltage bestätigt werden (dort werden sie vorbelegt)."
                )
            )
            if absences_known(sprint):
                st.info(
                    t(
                        "Die Fehltage dieses Sprints sind bereits bestätigt – die "
                        "angekündigten Fehltage haben keine Wirkung mehr."
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
                        t("Angekündigt fehlend (Tage)"),
                        min_value=0.0,
                        max_value=float(len(team_workdays(data.team, probe.start, probe.end))),
                        step=0.5,
                    ),
                },
                hide_index=True,
                key=f"vorplanung-expected-{sprint.id}",
                placeholder="",  # leer = Person ist in diesem Sprint nicht im Team
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
    shown_plan = shown.result.plan  # aktuell berechnet (mit Annahme, falls eingetragen)
    frozen_plan = sprint.forecast_plan  # beim Planning eingefroren
    with headline:
        columns = st.columns(4 if frozen_plan is not None else 3)
        plan_col, capacity_col, trend_col = columns[0], columns[-2], columns[-1]
        delta = None
        if assumed and shown_plan is not None and entry.result.plan is not None:
            delta = t(
                "{diff} {unit} (ohne Annahme {old} {unit})",
                diff=_signed(shown_plan - entry.result.plan),
                unit=unit,
                old=fmt(entry.result.plan),
            )
        plan_col.metric(
            t("Prognose aktuell {id}", id=sprint.id),
            f"{fmt(shown_plan)} {unit}",
            delta=delta,
            delta_color="off",
            help=(_formula_help(fc_view, shown, "plan") + "\n\n" if shown_plan is not None else "")
            + t("Aktuell berechnet."),
        )
        if frozen_plan is not None:
            columns[1].metric(
                t("Prognose beim Planning {id}", id=sprint.id),
                f"{fmt(frozen_plan)} {unit}",
                delta=None if shown_plan is None else _signed(shown_plan - frozen_plan),
                delta_color="off",
                help=t(
                    "Beim Planning eingefroren (Basis der verteilbaren Menge). Die Zahl darunter "
                    "ist die Differenz der aktuellen Prognose dazu."
                ),
            )
        # Die Quelle steht unter dem Wert (nicht im Wert): sonst wird die Zahl abgeschnitten.
        capacity_col.metric(
            t("Kapazität (PT)"),
            fmt_capacity(shown.result.plan_capacity, shown.capacity_digits),
            delta=capacity_source_note(shown) or None,
            delta_color="off",
            delta_arrow="off",
            help=_formula_help(fc_view, shown, "capacity"),
        )
        trend_col.metric(t("n. Velocity-Trend"), fmt(shown.result.normalized_velocity.trend, 2))
        if note := band_note(fc_view, shown, without_assumption=bool(assumed)):
            st.caption(note)
    if assumed:
        if shown is not None and (plan_step := formula_step(fc_view, shown, "plan")):
            st.caption(
                t(
                    "Rechnung: {calculation} · Kapazität {capacity} PT",
                    calculation=plan_step.calculation,
                    capacity=capacity_label(shown),
                )
            )
        if sprint.forecast_plan is not None:
            st.caption(
                t(
                    "Die Prognose beim Planning dieses Sprints ist eingefroren – die Annahme "
                    "ändert ihn nicht."
                )
            )
    d = distribution(fc_view, fc_view.entry(sprint.id) or entry)
    rows = _product_editor(d, ["preplanned"], f"vorplanung-{sprint.id}", unit)
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
        t("Verteilbar"), f"{fmt(d.available, 2)} {unit}", help=_available_text(d, data, unit)
    )
    middle.metric(t("Vorgesehen (Σ)"), f"{fmt(total, 2)} {unit}")
    st.caption(_available_text(d, data, unit))
    if total is not None and d.available is not None:
        rest = d.available - total
        right.metric(
            t("Noch frei") if rest >= 0 else t("Zu viel"),
            f"{fmt(abs(rest), 2)} {unit}",
            delta=None,
        )
    comparison = [
        {
            t("Produkt"): r.product.name,
            **({"PO": r.product.po or ""} if data.team.features.po else {}),
            t("Standard"): fmt(r.standard, 2),
            t("PO-Vorplanung"): fmt(r.preplanned, 2),
            t("Differenz"): _signed(r.preplanned - r.standard)
            if r.preplanned is not None and r.standard is not None
            else "–",
        }
        for r in d.rows
        if r.active or r.preplanned is not None
    ]
    st.dataframe(pd.DataFrame(comparison), hide_index=True)
    if po_rows := (by_po(d) if data.team.features.po else []):
        st.markdown(f"**{t('Je PO')}**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "PO": po,
                        t("Standard"): fmt(totals["standard"], 2),
                        t("PO-Vorplanung"): fmt(totals["preplanned"], 2),
                    }
                    for po, totals in po_rows
                ]
            ),
            hide_index=True,
        )
    changed = after.products != base.products or bool(assumed) or expected != saved_expected
    if st.button(t("PO-Vorplanung speichern"), type="primary", disabled=not changed):
        to_save = [after]
        if assumed:
            plan = fc_preview.entry(after.id).result.plan if fc_preview.entry(after.id) else None
            to_save = record_prognoses(data, after, assumed, plan, comment)
        if save(
            with_sprints(data, to_save),
            [f"{s.id}.yaml" for s in to_save],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
            flash=True,
        ):
            st.rerun()  # die Schrittleiste oben zeigt den gespeicherten Stand
    page_link("planning", t("Weiter zum Planning"))


def page_products(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Produktverteilung"))
    unit = data.team.unit.value
    if not data.products:
        st.info(
            t(
                "Noch keine Produkte erfasst. Mit Produkten zeigt diese Seite, wie sich die "
                "Sprint-Menge auf die Produkte verteilt: Standard, PO-Vorplanung, Planning und "
                "Erledigt."
            )
        )
        page_link("produktliste", t("Produkte anlegen"))
        return
    sprint = sprint_select(data, fc, "products-sprint")
    if sprint is None:
        return
    entry = fc.entry(sprint.id)
    if entry is None:
        return
    st.caption(
        t(
            "Reine Auswertung: Die Werte werden nicht hier, sondern im Ablauf erfasst – die "
            "**PO-Vorplanung** vor dem Planning, **Planning** im Sprint Planning, **Erledigt** "
            "im Review."
        )
    )
    links = st.columns(3)
    for col, key in zip(links, BOARDS, strict=True):
        with col:
            page_link(key, t("Ändern: {page}", page=t(PAGE_INFO[key][0])))
    d = distribution(fc, entry)
    if _product_table(d, unit):
        _production_hint(d, data, unit)
        if chart := _product_chart(d, unit):
            st.altair_chart(chart, width="stretch")
        if po_rows := (by_po(d) if data.team.features.po else []):
            st.markdown(f"**{t('Je PO')}**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"PO": po, **{measure_label(m): fmt(v, 2) for m, v in totals.items()}}
                        for po, totals in po_rows
                    ]
                ),
                hide_index=True,
            )

    st.subheader(t("Verlauf"))
    count = st.number_input(
        t("Anzahl Sprints"), min_value=2, max_value=26, value=6, key="products-n"
    )
    entries = [e for e in fc.entries if e.sprint.start <= sprint.start][-int(count) :]
    chosen = st.radio(
        t("Kennzahl"),
        ["done", "planned", "preplanned"],
        format_func=measure_label,
        horizontal=True,
        key="products-measure",
    )
    chart = _history_chart(fc, entries, chosen, unit)
    if chart is None:
        st.info(
            t(
                "In diesen Sprints ist noch kein Wert „{measure}“ erfasst.",
                measure=measure_label(chosen),
            )
        )
    else:
        st.altair_chart(chart, width="stretch")
    st.subheader(t("Saldo gegenüber der Standardverteilung"))
    _balance_section(fc, entries, unit)


def page_product_list(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Produkte"))
    st.markdown(
        t(
            "Produkte, die das Team betreut – mit verantwortlichem PO (optional) und Zeitraum.  \n"
            "**Produkt abgegeben:** **bis** setzen statt löschen – sonst fehlen die Werte "
            "vergangener Sprints in der Auswertung.  \n"
            "**Neues Produkt:** Zeile ergänzen, **ab** = erster betreuter Tag (leer = schon "
            "immer)."
        )
    )
    show_former = st.toggle(t("Ehemalige anzeigen"), value=False, key="show_former_products")
    rows, hidden = product_table(data.products, fc.today, show_former)
    if hidden:
        st.caption(t("{count} ehemalige(s) Produkt(e) ausgeblendet.", count=len(hidden)))
    frame = pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
    for col in ("ab", "bis"):
        frame[col] = pd.to_datetime(frame[col])
    frame["PO"] = frame["PO"].astype("string")
    frame["Anteil"] = frame["Anteil"].astype("float")
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,
            "Name": st.column_config.TextColumn(t("Name"), required=True),
            "PO": st.column_config.TextColumn("PO", help=t("Verantwortlicher Product Owner"))
            if data.team.features.po
            else None,
            "Anteil": st.column_config.NumberColumn(
                t("Anteil (%)"),
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                help=t(
                    "Vereinbarter fester Anteil an der Teamkapazität, z. B. 10. Leer = gleichmäßig "
                    "auf den Rest verteilt."
                ),
            ),
            "ab": st.column_config.DateColumn(
                t("ab"), format="DD.MM.YYYY", help=t("Leer = schon immer")
            ),
            "bis": st.column_config.DateColumn(
                t("bis"), format="DD.MM.YYYY", help=t("Leer = weiterhin betreut")
            ),
        },
        num_rows="dynamic",
        hide_index=True,
        key=f"products-list-{data.team.key}-{show_former}",
        placeholder="",  # „leer = schon immer“ usw.: leere Zellen bleiben leer, nicht „None“
    )
    result = products_from_table(edited.to_dict("records"), data.products, hidden)
    confirmed = True
    if result.deleted:
        st.warning(
            t(
                "Gelöscht: {names}.  \nNur löschen, wenn falsch erfasst. Gibt das Team ein "
                "Produkt ab, stattdessen **bis** setzen.",
                names=", ".join(result.deleted),
            )
        )
        confirmed = st.checkbox(
            t("Ja, die Zeilen waren Fehleingaben"), key="confirm_delete_products"
        )
    if not st.button(t("Produkte speichern"), type="primary", disabled=not confirmed):
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
    st.header(t("Personen"))
    st.markdown(
        t(
            "Eine Zeile je Zeitraum im Team.  \n"
            "**Austritt:** in der Zeile **bis** setzen – nicht löschen, sonst ändern sich "
            "Kapazitäten und Fehltage vergangener Sprints.  \n"
            "**FTE-Änderung:** in der bisherigen Zeile **bis** setzen und eine neue Zeile mit "
            "**gleichem Namen** und neuem FTE-Anteil anlegen."
        )
    )
    show_former = st.toggle(t("Ehemalige anzeigen"), value=False, key="show_former")
    rows, hidden = people_table(data.people, fc.today, show_former)
    if hidden:
        st.caption(t("{count} ehemalige Person(en) ausgeblendet.", count=len(hidden)))
    frame = pd.DataFrame(rows, columns=PEOPLE_COLUMNS)
    for col in ("ab", "bis"):
        frame[col] = pd.to_datetime(frame[col])
    frame["Produktionszugriff"] = frame["Produktionszugriff"].astype(bool)
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,  # interne ID, wird automatisch vergeben
            "Name": st.column_config.TextColumn(t("Name"), required=True),
            "Land": st.column_config.SelectboxColumn(
                t("Land"),
                options=[TEAM_REGION, *countries()],
                default=TEAM_REGION,
                help=t(
                    "(Team) = Einstellung des Teams; abweichendes Land für Feiertage und Wochenende"
                ),
            ),
            "Arbeitswoche": st.column_config.TextColumn(
                t("Arbeitswoche"),
                help=t(
                    "Leer = wie Land/Team. mon-fri, sun-thu, mon-sat oder die Arbeitstage, z. B. "
                    "mon,tue,wed,thu für eine 4-Tage-Woche"
                ),
            ),
            "Bundesland": st.column_config.SelectboxColumn(
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
                help=t("(Team) = Einstellung des Teams; Bundesland, Staat oder Provinz"),
            ),
            "ab": st.column_config.DateColumn(
                t("ab"), format="DD.MM.YYYY", required=True, default=fc.today
            ),
            "bis": st.column_config.DateColumn(
                t("bis"), format="DD.MM.YYYY", help=t("Leer = weiterhin im Team")
            ),
            "FTE": st.column_config.NumberColumn(
                "FTE",
                step=0.05,
                default=1.0,
                help=t(
                    "Anteil im Team, 1 = Vollzeit, 0 = keine Kapazität (z. B. längere Abwesenheit)"
                ),
            ),
            "Produktionszugriff": st.column_config.CheckboxColumn(
                t("Produktionszugriff"),
                default=False,
                help=t(
                    "Darf Tickets bearbeiten, die Produktionszugriff erfordern. Gilt für die "
                    "Person, nicht für den einzelnen Zeitraum."
                ),
            )
            if data.team.features.production
            else None,
        },
        num_rows="dynamic",
        hide_index=True,
        key=f"people-{data.team.key}-{show_former}",
        placeholder="",  # „Leer = weiterhin im Team“ usw.: leere Zellen bleiben leer, nicht „None“
    )
    result = people_from_table(edited.to_dict("records"), data.people, hidden)
    confirmed = True
    if result.deleted:
        st.warning(
            t(
                "Gelöscht: {names}.  \nZeilen nur löschen, wenn sie **falsch erfasst** wurden. "
                "Verlässt jemand das Team, stattdessen **bis** setzen – sonst entstehen "
                "Inkonsistenzen (z. B. Fehltage für unbekannte Personen).",
                names=", ".join(result.deleted),
            )
        )
        confirmed = st.checkbox(t("Ja, die Zeilen waren Fehleingaben"), key="confirm_delete")
    for e in result.errors:
        st.error(e)
    if not st.button(
        t("Personen speichern"), type="primary", disabled=not confirmed or bool(result.errors)
    ):
        return
    save(
        with_people(data, result.people),
        ["people.yaml"],
        lambda: [repo.save_people(data.team.key, result.people)],
        block_on_all_errors=True,
    )


def _setting_widget(setting: Setting, team: Team, key: str) -> str:
    """Zeigt das passende Eingabefeld und liefert den Wert als Text für Setting.parse."""
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
                format_func=lambda k: f"{k} – {choices[k]}" if k else t("(keine Angabe)"),
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
    """Arbeitstage je Sprint (Arbeitswoche des Teams, aus der Sprintlänge) – Umrechnung
    zwischen PT und %."""
    length = st.session_state.get(f"{form_key}-sprint.length_days", team.sprint.length_days)
    return max(float(length) * (7 - len(team_weekend(team))) / 7, 1.0)


def _overhead_widgets(team: Team, form_key: str) -> dict[str, str]:
    share = next(s for s in SETTINGS if s.key == OVERHEAD_KEYS[0])
    days = next(s for s in SETTINGS if s.key == OVERHEAD_KEYS[1])
    share_key, days_key = (f"{form_key}-{k}" for k in OVERHEAD_KEYS)
    if share_key not in st.session_state or days_key not in st.session_state:
        # Nur eines gesetzt (z. B. aus der Datei): das andere daraus ableiten.
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


def _settings_form(team: Team, has_sprints: bool, form_key: str, submit: str) -> Team | None:
    """Formular für alle Einstellungen; liefert das geänderte Team nach dem Absenden."""
    edited = copy.deepcopy(team)
    # Die beiden Scrum-Abzüge sind derselbe Wert: außerhalb des Formulars, damit sie sich
    # sofort abgleichen können (Formularfelder reagieren erst beim Absenden).
    raw = _overhead_widgets(team, form_key)
    with st.form(form_key):
        raw |= {
            s.key: _setting_widget(s, team, f"{form_key}-{s.key}")
            for s in applicable(has_sprints)
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
                raise ValueError(t("Bitte einen Wert eingeben."))
            s.set(edited, value)
        except ValueError as e:
            errors.append(f"{s.title}: {e}")
    for e in errors:
        st.error(e)
    return None if errors else edited


def page_settings(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(t("Einstellungen {team}", team=data.team.name))
    edited = _settings_form(
        data.team, bool(data.sprints), f"settings-{data.team.key}", t("Speichern")
    )
    if edited is None:
        return
    diff = changes(data.team, edited)
    if not diff:
        st.info(t("Keine Änderungen."))
        return
    st.dataframe(
        pd.DataFrame(
            [
                {t("Einstellung"): s.title, t("bisher"): old or "–", t("neu"): new or "–"}
                for s, old, new in diff
            ]
        ),
        hide_index=True,
    )
    if any(s.retroactive for s, _, _ in diff):
        st.warning(t("Mindestens eine Änderung wirkt rückwirkend auf alle berechneten Werte."))
    after = copy.deepcopy(data)
    after.team = edited
    save(
        after,
        ["team.yaml"],
        lambda: [repo.save_team(edited)],
    )


def page_new_team(repo: Repository) -> None:
    st.header(t("Neues Team anlegen"))
    st.markdown(
        t(
            "**Welche Bereiche braucht das Team?** Drei Bereiche sind optional und zunächst "
            "**aus**; sie lassen sich unten jetzt oder später unter **Einstellungen** "
            "zuschalten:  \n"
            "• **Produktverteilung** – das Team betreut mehrere Produkte, die Sprint-Menge wird "
            "darauf verteilt (Produktliste, PO-Vorplanung, Planning und Erledigt je Produkt).  \n"
            "• **Zuordnung PO** – jedes Produkt hat einen Product Owner, Summen je PO "
            "(nur zusammen mit der Produktverteilung sinnvoll).  \n"
            "• **Produktionszugriff** – nur ein Teil der Personen darf bestimmte Tickets "
            "bearbeiten; es wird erfasst, wie viel Menge davon betroffen ist, mit "
            "Engpass-Hinweis."
        )
    )
    key = (
        st.text_input(t("Team-Kürzel (Verzeichnisname)"), help=t("Kleinbuchstaben, z. B. team-a"))
        .strip()
        .lower()
    )
    if not key:
        return
    if clash := repo.clashing_team(key):
        if clash == key:
            st.error(t("Team {team} existiert bereits.", team=repr(key)))
        else:
            st.error(
                t(
                    "Team {team} existiert bereits (als {existing}; Windows und macOS "
                    "unterscheiden Ordner nicht nach Groß- und Kleinschreibung).",
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
    team.sprint.first_id = f"{today().year}.1"
    team.sprint.numbering = Numbering.YEARLY
    edited = _settings_form(team, False, f"new-{key}", t("Team anlegen"))
    if edited is None:
        return
    if save(
        TeamData(team=edited),
        ["team.yaml"],
        lambda: [repo.save_team(edited), repo.save_people(key, [])],
    ):
        st.session_state["selected_team"] = key
        page_link("personen", t("Weiter: Personen erfassen"))


def needs_setup(root: Path) -> bool:
    """Kein Datenordner gefunden: weder Teams noch ein Git-Repository (und nicht ausdrücklich
    „ohne Git“ gewählt)."""
    return teams_dir(root) is None and git_root(root) is None and not is_without_git(root)


# Zustand, der beim Wechsel des Datenordners erhalten bleibt; alles andere (Formulareingaben,
# Teamwahl, vorgemerkte Tags, Git-Meldungen) gehört zum alten Ordner und wird verworfen.
_SWITCH_KEEP = {
    "language", "flash", "restarting", "update-started", "manual-check", "active-data-dir",
    "folder-state",
}  # fmt: skip
# Zustand, der zu einem Ordner gehört und beim Zurückwechseln wieder da ist.
_PER_FOLDER = ("pending_tags", "commit_message", "use_tags")


def _use_data_dir(path: Path) -> str | None:
    """Wechselt den Datenordner: merkt ihn, leert die Zwischenspeicher (Teams, Git-Stand) und
    verwirft alte Formularzustände, damit nichts vom bisherigen Ordner im neuen landet.
    Lassen sich die Einstellungen nicht speichern, unterbleibt der Wechsel ganz; die Meldung
    (mit nächstem Schritt) wird zurückgegeben."""
    try:
        save_data_dir(path)
    except SettingsError as e:
        return _settings_problem(e, t("Der Datenordner wurde nicht gewechselt."))
    folders = st.session_state.setdefault("folder-state", {})
    folders[str(data_dir().resolve())] = {
        name: copy.deepcopy(st.session_state[name])
        for name in _PER_FOLDER
        if name in st.session_state
    }
    clear_team_cache()
    # Nur die Vorgabe für neue Sitzungen; diese Sitzung führt ihren Ordner selbst.
    os.environ[DATA_ENV] = str(path.resolve())
    for name in list(st.session_state.keys()):
        if name not in _SWITCH_KEEP:
            del st.session_state[name]
    st.session_state[DATA_DIR_KEY] = str(path.resolve())
    st.session_state.update(copy.deepcopy(folders.get(str(path.resolve()), {})))
    st.session_state["flash"] = [("success", t("Datenordner: `{path}`", path=path.resolve()))]
    return None


def _switch_clicked(target: Path) -> None:
    if not target.is_dir():  # inzwischen verschwunden (die Anzeige ist kurz zwischengespeichert)
        st.session_state.setdefault("flash", []).append(
            ("error", t("Ordner nicht gefunden: {path}", path=target))
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
            ("error", _settings_problem(e, t("Der Ordner wurde nicht aus der Liste entfernt.")))
        )


# Ob ein zuletzt benutzter Ordner noch da ist, wird kurz gemerkt: Die Liste wird bei jedem
# Durchlauf gezeichnet, und ein toter Netzlaufwerkpfad würde sonst jedes Mal bremsen.
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
    return f"{path.name or path}  ({path})" + ("" if _dir_exists(path) else t(" – nicht gefunden"))


def _open_changes(repo: Repository) -> int | None:
    """Zahl der offenen Änderungen; ``None``, wenn Git sie nicht liefern kann."""
    try:
        return len(cached_pending_changes(repo.root))
    except GitError:
        return None


def _switch_hint(repo: Repository) -> str:
    count = _open_changes(repo)
    head = t(
        "Beim Wechsel werden nicht gespeicherte Eingaben in Formularen verworfen; vorgemerkte "
        "Tags und die Commit-Nachricht bleiben für den Ordner erhalten."
    )
    tail = (
        t("Offene Änderungen im bisherigen Ordner ({count}) bleiben dort erhalten.", count=count)
        if count is not None
        else t("Offene Änderungen im bisherigen Ordner bleiben dort erhalten.")
    )
    return f"{head} {tail}"


def _recent_dirs(repo: Repository) -> list[Path]:
    """Zuletzt benutzte Datenordner ohne den aktiven (gemerkt sind aufgelöste Pfade)."""
    current = resolved_path(repo.root)
    return [p for p in recent_data_dirs() if resolved_path(p) != current]


def _switch_panel(repo: Repository) -> None:
    """Umschalter zwischen den zuletzt benutzten Datenordnern (Seitenleiste)."""
    options = _recent_dirs(repo)
    if not options:
        return
    with st.expander(t("Datenordner wechseln"), icon=":material/folder_open:"):
        target = st.selectbox(
            t("Zuletzt benutzt"), options, format_func=_recent_label, key="switch-target"
        )
        st.caption(_switch_hint(repo))
        st.button(
            t("Wechseln"),
            key="switch-go",
            on_click=_switch_clicked,
            args=(target,),
            disabled=not _dir_exists(target),
        )


def _active_repo_caption(repo: Repository) -> None:
    """Aktives Repository (Ordner und Branch) dauerhaft sichtbar."""
    branch = ""
    if git_available() and git_root(repo.root) is not None:
        try:
            current = cached_sync_state(repo.root)
        except GitError:
            current = None
        if current is not None:
            branch = current.branch or t("kein Branch")
    # Mit dem übergeordneten Ordner: Im empfohlenen Aufbau heißt der Datenordner immer „teams“.
    root = repo.root.resolve()
    shown = "/".join(p for p in (root.parent.name, root.name) if p) or str(root)
    st.markdown(
        f"**{t('Datenordner')}:** `{shown}`" + (f" · {t('Branch')} `{branch}`" if branch else "")
    )


def _browse(key: str) -> None:
    """Ordnerauswahl des Systems (in eigenem Prozess – Tk braucht den Hauptthread)."""
    title = t("Datenordner wählen").replace("'", "")
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


def _path_input(label: str, key: str, default: str) -> Path:
    st.session_state.setdefault(key, default)
    left, right = st.columns([5, 1], vertical_alignment="bottom")
    raw = left.text_input(label, key=key)
    right.button(t("Durchsuchen …"), key=f"{key}-browse", on_click=_browse, args=(key,))
    if st.session_state.pop("browse-error", False):
        st.caption(t("Kein Ordnerdialog verfügbar – bitte den Pfad eintippen."))
    return Path(raw.strip()).expanduser()


# --- Server (Remote) einrichten -------------------------------------------------------------
# Alle Schlüssel beginnen mit ``git-remote-``: Sie überstehen veraltete Eingaben
# (``_discard_stale_inputs``), und ein Wechsel des Datenordners verwirft sie (``_use_data_dir``).

# Fehlerarten zu einer eingegebenen Adresse: Ihre Meldung nennt nur den Grund, die Überschrift
# (``git_title``) liefert die Oberfläche.
ADDRESS_ERRORS = {"bad_url", "secret_in_url", "insecure_url"}


def _remote_url_changed() -> None:
    """Callback des Adressfelds: Eine Adresse mit Zugangsdaten bleibt nie stehen. Das Feld wird
    geleert; die Meldung folgt im nächsten Durchlauf, ohne die Eingabe zu wiederholen."""
    if has_credentials(st.session_state.get("git-remote-url", "")):
        st.session_state["git-remote-url"] = ""
        st.session_state["git-remote-rejected"] = True


def _remote_status(info: RemoteInfo, merge_open: bool) -> None:
    """Der eingerichtete Server (ohne Zugangsdaten) und Gründe, die das Ändern sperren."""
    # Namen und Adressen kommen aus der Konfiguration (Altbestand, fremde Hand): immer als Code.
    if info.name is None:
        st.info(
            t(
                "Zu diesem Datenordner gehört noch kein Server. Solange keiner eingetragen ist, "
                "bleiben alle Änderungen auf diesem Rechner. Wer einem bestehenden Team "
                "beitritt, wählt weiter unten „Repository klonen“, statt hier eine Adresse "
                "einzutragen."
            )
        )
    else:
        st.markdown(t("Server {name}: {url}", name=md_code(info.name), url=md_code(info.url)))
    if info.others:
        st.caption(
            t(
                "Weitere Server (werden nicht verändert): {names}",
                names=", ".join(md_code(name) for name in info.others),
            )
        )
    if info.has_secret:
        st.warning(
            t(
                "In der gespeicherten Adresse stehen Zugangsdaten. Sie werden hier nicht "
                "angezeigt. Beim Speichern einer neuen Adresse werden sie ersetzt; künftig bitte "
                "den Anmeldedienst des Rechners verwenden."
            )
        )
    if info.special:
        st.warning(str(remote_special_error()))
    if merge_open:
        st.warning(
            t(
                "Ein Zusammenführen ist unvollständig. Solange es offen ist, lässt sich der "
                "Server nicht ändern."
            )
        )


def _remote_failed(root: Path, address: RemoteAddress, error: GitError) -> None:
    """Zeigt, warum Prüfen oder Speichern scheiterte, und bietet in zwei Fällen an, trotzdem zu
    speichern: Server nicht erreichbar und Branch fehlt. Das Angebot (Ordner, Adresse, Art) ist
    der einzige Zustand der Maske; es enthält nie die Eingabe, nur die geprüfte Adresse."""
    offer = {"root": str(root), "url": address.url}
    if isinstance(error, NewBranchError):
        st.session_state["git-remote-offer"] = offer | {
            "kind": "new_branch",
            "text": error.render(md_code),  # Branch-Namen vom Server: als Code, nie als Markdown
        }
        return  # das Angebot zeigt die Meldung
    _show_problem(error)
    if error.kind == "offline":
        st.session_state["git-remote-offer"] = offer | {"kind": "offline"}


def _remote_check(root: Path, address: RemoteAddress, insecure: bool) -> None:
    """„Verbindung prüfen“: fragt den Server nach seinen Branches, ändert nichts. Das Netzwerk
    wird nur hier, auf Klick, angesprochen."""
    try:
        with st.spinner(
            t("Prüfe die Verbindung … Falls ein Anmeldefenster erscheint, bitte dort anmelden.")
        ):
            checked = check_remote(root, address.url, allow_insecure=insecure)
    except GitError as e:
        _remote_failed(root, address, e)
        return
    st.success(t("Verbindung hergestellt."))
    if checked.empty:
        st.info(
            t(
                "Der Server ist erreichbar, enthält aber noch keine Branches (neues, leeres "
                "Repository). Beim ersten „Speichern und teilen“ wird der Stand hochgeladen. Bei "
                "einer Webadresse kann es auch bedeuten, dass sie nicht auf ein Git-Repository "
                "zeigt."
            )
        )
        return
    # Die Namen kommen vom Server und können alles Mögliche enthalten (etwa eine Webadresse, die
    # Markdown zum Link machte): als Code ausgeben. Gekürzt wird nur die Anzeige.
    names = ", ".join(md_code(head) for head in checked.heads[:5])
    st.caption(
        t(
            "Branches auf dem Server: {names}",
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
    """„Speichern“: das Backend prüft erneut und speichert nur nach bestandener Prüfung (oder
    mit der ausdrücklichen Bestätigung in ``confirmed``). Bei Erfolg zeichnet der nächste
    Durchlauf alles neu (Seitenleiste, leeres Feld)."""
    try:
        with st.spinner(
            t("Prüfe die Verbindung … Falls ein Anmeldefenster erscheint, bitte dort anmelden.")
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
                "Server gespeichert: {url}. Mit „Speichern und teilen“ wird der Stand abgeglichen.",
                url=md_code(saved.url),
            ),
        )
    else:
        flash = (
            "warning",
            t(
                "Server gespeichert, aber nicht geprüft: {url}. Geprüft wird die Adresse beim "
                "nächsten Teilen.",
                url=md_code(saved.url),
            ),
        )
    st.session_state["flash"] = [flash]
    st.rerun()


def _remote_offer(root: Path, address: RemoteAddress | None, insecure: bool, locked: bool) -> None:
    """Das Angebot nach „Server nicht erreichbar“ bzw. „Branch fehlt“: nur mit ausdrücklicher
    Bestätigung trotzdem speichern. Es gilt nur für denselben Ordner und dieselbe Adresse."""
    offer = st.session_state.get("git-remote-offer")
    if not offer:
        return
    if address is None or offer["root"] != str(root) or offer["url"] != address.url:
        st.session_state.pop("git-remote-offer", None)
        return
    if offer["kind"] == "offline":
        st.warning(
            t(
                "Der Server ist gerade nicht erreichbar. Die Adresse kann trotzdem gespeichert "
                "werden (z. B. wenn das VPN aus ist); geprüft wird sie dann beim nächsten Teilen."
            )
        )
        label, key, confirmed = t("Trotzdem speichern"), "git-remote-offline-save", "allow_offline"
    else:
        st.warning(f"**{git_title('new_branch')}**  \n{offer['text']}")
        label = t("Ja, dies ist das richtige Daten-Repository")
        key, confirmed = "git-remote-branch-save", "accept_new_branch"
    if st.button(label, key=key, disabled=locked):
        st.session_state.pop("git-remote-offer", None)
        _remote_save(root, address, insecure, **{confirmed: True})


def _remote_section(repo: Repository) -> None:
    """Server (Remote) des Datenordners anzeigen, prüfen und ändern. Zeichnet nichts ohne Git,
    ohne Repository oder wenn Git den Stand nicht liefert (die übrigen Hinweise genügen dann).
    Die Wurzel wird in diesem Durchlauf gebunden; Callbacks lesen nie den Datenordner."""
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
    st.subheader(t("Server (Remote)"))
    _remote_status(info, merge_open)
    if st.session_state.pop("git-remote-reset", False):
        st.session_state["git-remote-url"] = ""  # vor dem Feld; danach wäre es nicht erlaubt
    raw = st.text_input(
        t("Neue Server-Adresse") if info.name else t("Server-Adresse"),
        key="git-remote-url",
        on_change=_remote_url_changed,
        placeholder="https://git.example.com/team/sprint-daten.git",
        help=t(
            "Erlaubt sind https://…, ssh://…, git@server:pfad und ein vollständiger "
            "Ordnerpfad. Benutzername, Kennwort und Token gehören nicht in die Adresse; die "
            "Anmeldung übernimmt der Anmeldedienst des Rechners, fehlt sie, erklärt die App den "
            "nächsten Schritt."
        ),
    )
    if st.session_state.pop("git-remote-rejected", False):
        _show_problem(secret_in_url_error())
        st.caption(
            t(
                "Die Eingabe wurde verworfen und das Feld geleert. Bitte die Adresse ohne "
                "Benutzernamen, Kennwort, Token und Parameter (alles ab „?“) neu eintragen."
            )
        )
    insecure = False
    if raw.strip().lower().startswith("http://"):
        insecure = st.checkbox(
            t("Unverschlüsselte Verbindung trotzdem verwenden"), key="git-remote-insecure"
        )
    address = None
    if raw.strip():
        try:
            address = parse_remote_url(raw, allow_insecure=insecure)
        except GitError as e:
            _show_problem(e)
    locked = merge_open or bool(info.special)
    # Beide Knöpfe gehören zusammen: nebeneinander, linksbündig, nur so breit wie ihr Text.
    with st.container(horizontal=True):
        check_clicked = st.button(
            t("Verbindung prüfen"), key="git-remote-check", disabled=address is None
        )
        save_clicked = st.button(
            t("Speichern"),
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


def page_data_dir(repo: Repository, setup: bool = False) -> None:
    st.header(t("Datenordner"))
    if setup:
        st.warning(
            t(
                "Kein Datenordner gefunden. Empfohlen ist ein **Git-Repository**: So sind "
                "Änderungen nachvollziehbar und mit dem Team teilbar. Bitte einen vorhandenen "
                "Ordner wählen (auch ohne Git möglich), ein neues Daten-Repository anlegen oder "
                "ein bestehendes klonen."
            )
        )
    else:
        root = git_root(repo.root)
        st.markdown(t("Aktuell: `{path}`", path=repo.root.resolve()))
        st.caption(
            t("Git-Repository: `{path}`", path=root)
            if root
            else t("Achtung: liegt in keinem Git-Repository.")
        )
        _remote_section(repo)
    if recent := _recent_dirs(repo):
        st.subheader(t("Zuletzt benutzt"))
        for n, folder in enumerate(recent):
            left, switch, forget = st.columns([6, 1.2, 1.2], vertical_alignment="center")
            left.markdown(_recent_label(folder))
            switch.button(
                t("Wechseln"),
                key=f"recent-go-{n}",
                on_click=_switch_clicked,
                args=(folder,),
                disabled=not _dir_exists(folder),
            )
            forget.button(
                t("Entfernen"),
                key=f"recent-forget-{n}",
                on_click=_forget_clicked,
                args=(folder,),
                help=t("Nur aus der Liste entfernen; der Ordner bleibt bestehen."),
            )
        st.caption(_switch_hint(repo))
    choose, create, clone = st.tabs(
        [
            t("Vorhandenen Ordner wählen"),
            t("Neues Daten-Repository anlegen"),
            t("Repository klonen"),
        ]
    )
    home = Path.home()
    with choose:
        path = _path_input(t("Ordner"), "data-path", str(repo.root.resolve()))
        if st.button(t("Übernehmen"), type="primary", key="data-choose"):
            if not path.is_dir():
                st.error(t("Ordner nicht gefunden: {path}", path=path))
            elif git_root(path) is None:
                st.warning(
                    t(
                        "Der Ordner liegt in keinem Git-Repository. Das Programm funktioniert "
                        "auch ohne Git – nur Commit und Verlauf stehen dann nicht zur Verfügung. "
                        "Du kannst hier ein Repository anlegen oder den Ordner ohne Git verwenden."
                    )
                )
                st.session_state["offer-init"] = str(path)
            elif problem := _use_data_dir(teams_dir(path) or path):
                st.error(problem)
            else:
                st.rerun()
        offer = st.session_state.get("offer-init")
        if offer and st.button(
            t("Ohne Git verwenden"), key="data-without-git", disabled=not Path(offer).is_dir()
        ):
            target = teams_dir(Path(offer)) or Path(offer)
            # Bewusste Wahl: Ohne Teams und ohne Git nicht wieder zur Einrichtung, sondern
            # weiter zu „Neues Team“ – dauerhaft je Ordner, auch nach dem Neuladen des Tabs.
            try:
                remember_without_git(target)
            except SettingsError as e:
                st.error(_settings_problem(e, t("Der Ordner wurde nicht übernommen.")))
            else:
                if problem := _use_data_dir(target):
                    # Nicht halb übernehmen: Die Entscheidung gilt nur mit dem Wechsel.
                    with contextlib.suppress(SettingsError):
                        forget_without_git(target)
                    st.error(problem)
                else:
                    st.session_state.pop("offer-init", None)
                    st.rerun()
        if offer and st.button(
            t("Git-Repository in {path} anlegen", path=offer), key="data-init-here"
        ):
            try:
                target = init_data_repository(Path(offer), teams_folder=False)
            except GitError as e:
                st.error(str(e))
            else:
                if problem := _use_data_dir(teams_dir(target) or target):
                    st.error(problem)
                else:
                    st.session_state.pop("offer-init", None)
                    st.rerun()
    with create:
        st.caption(
            t(
                "Legt den Ordner mit `git init`, einer `.gitignore` (keine Tabellenkalkulationen) "
                "und dem Unterordner `teams` an. Danach unter **Neues Team** ein Team anlegen."
            )
        )
        path = _path_input(t("Neuer Ordner"), "data-new", str(home / "sprint-daten"))
        if st.button(t("Anlegen"), type="primary", key="data-create"):
            if path.exists() and any(path.iterdir()) and teams_dir(path) is None:
                st.error(
                    t(
                        "{path} ist nicht leer – bitte einen leeren oder neuen Ordner wählen.",
                        path=path,
                    )
                )
            else:
                try:
                    target = init_data_repository(path)
                except GitError as e:
                    st.error(str(e))
                else:
                    if problem := _use_data_dir(target):
                        st.error(problem)
                    else:
                        st.rerun()
    with clone:
        st.caption(
            t(
                "Für Kolleginnen und Kollegen: das gemeinsame Daten-Repository des Teams klonen. "
                "Je nach Server fragt Git nach der Anmeldung."
            )
        )
        url = st.text_input(
            t("Adresse"), placeholder="https://git.example.com/team/sprint-daten.git"
        )
        path = _path_input(t("Zielordner"), "data-clone", str(home / "sprint-daten"))
        if st.button(t("Klonen"), type="primary", key="data-clone-go", disabled=not url.strip()):
            with st.spinner(t("Klone …")):
                try:
                    clone_repository(url.strip(), path)
                except GitError as e:
                    # Die Meldungen zur Adresse tragen ihre Überschrift nicht mehr selbst.
                    detail = f"{git_title(e.kind)}: {e}" if e.kind in ADDRESS_ERRORS else str(e)
                    st.error(t("Klonen fehlgeschlagen: {error}", error=detail))
                else:
                    if problem := _use_data_dir(teams_dir(path) or path):
                        st.error(problem)
                    else:
                        st.rerun()


def page_check(repo: Repository) -> None:
    st.header(t("Prüfung aller Teams"))
    for key, issues in check_all(repo, today()).items():
        if not issues:
            st.success(t("{team}: keine Befunde", team=key))
            continue
        st.subheader(key)
        for i in issues:
            (st.error if i.level is Level.ERROR else st.warning)(f"{i.where}: {i.message}")


def page_help(repo: Repository) -> None:
    st.header(t("Hilfe"))
    st.markdown(
        t(
            "Die Weboberfläche bearbeitet dieselben Dateien wie die Kommandozeile – beides lässt "
            "sich mischen. Gespeichert wird lokal. Liegen die Daten in einem Git-Repository, "
            "sichert **Änderungen committen** in der Seitenleiste die Änderungen dort; hat das "
            "Team einen Server, sichert **Speichern und teilen** sie und teilt sie mit dem Team. "
            "Mehr im Reiter „Zusammenarbeit (Git)“."
        )
    )
    ablauf, begriffe, felder, team, zusammenarbeit, befehle = st.tabs(
        [
            t("Ablauf"),
            t("Begriffe"),
            t("Eingabefelder"),
            t("Team-Einstellungen"),
            t("Zusammenarbeit (Git)"),
            t("Kommandozeile"),
        ]
    )
    with ablauf:
        for step in WORKFLOW:
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment="center")
                left.caption(t(step.when))
                left.markdown(f"**{t(step.title)}**  \n{t(step.text)}")
                with right:
                    page_link(step.page)
    with begriffe:
        term, meaning = t("Begriff"), t("Bedeutung")
        st.table(
            pd.DataFrame([(t(a), t(b)) for a, b in TERMS], columns=[term, meaning]).set_index(term)
        )
        st.subheader(t("Kapazitätsquelle im Forecast"))
        source = t("Quelle")
        st.table(
            pd.DataFrame(
                [(t(a), t(b)) for a, b in CAPACITY_SOURCES], columns=[source, meaning]
            ).set_index(source)
        )
    with felder:
        for f in FIELDS.values():
            with st.container(border=True):
                st.markdown(f"**{t(f.title)}**  \n{t(f.what)}")
                st.caption(f"{t('Quelle')}: {t(f.source)} · {t('Beispiel')}: {t(f.example)}")
    with team:
        setting, meaning = t("Einstellung"), t("Bedeutung")
        st.table(
            pd.DataFrame(
                [(s.title, s.text) for s in SETTINGS], columns=[setting, meaning]
            ).set_index(setting)
        )
        page_link("einstellungen", t("Einstellungen ändern"))
    with zusammenarbeit:
        for title, text in GIT_HELP:
            with st.container(border=True):
                st.markdown(f"**{t(title)}**  \n{t(text)}")
    with befehle:
        command, purpose = t("Befehl"), t("Zweck")
        st.table(
            pd.DataFrame(
                [(command_text(a), t(b)) for a, b in COMMANDS], columns=[command, purpose]
            ).set_index(command)
        )
        st.caption(t("Ausführen mit `uv run …` im Ordner des Tools."))


# --- Seitenleiste und Seitenaufruf ----------------------------------------------------


def sidebar(repo: Repository) -> None:
    """Sprach- und Teamauswahl in der Seitenleiste (vor der Seite, damit diese sie kennt)."""
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
            st.info(t("Noch kein Team vorhanden."))
            return
        wanted = st.session_state.get("selected_team")
        team = st.selectbox("Team", teams, index=teams.index(wanted) if wanted in teams else 0)
        st.session_state["selected_team"] = team


@st.cache_resource
def _update_check() -> updater.AutoUpdate:
    """Einmal je Serverstart im Hintergrund auf eine neue Version prüfen."""
    return updater.AutoUpdate().start()


def _shutdown_soon() -> None:
    """Beendet den Server kurz nach dem Zeichnen der Meldung (Neustart übernimmt der
    Aktualisierungsprozess)."""
    import threading

    threading.Timer(1.5, lambda: os._exit(0)).start()


def _manual_update_check(check: updater.Check | None) -> None:
    """Knopf „Nach Updates suchen“ (die automatische Prüfung läuft nur einmal je Tag)."""
    manual = st.session_state.get("manual-check")
    if manual is not None:
        if manual.error:
            st.caption(t("Suche nicht möglich: {error}", error=manual.error))
        else:
            st.caption(t("Version {current} ist aktuell.", current=manual.current))
    if check is not None and check.installation is None:
        return  # nicht mit uv installiert – hier gibt es nichts zu aktualisieren
    if st.button(t("Nach Updates suchen"), icon=":material/refresh:", key="manual-check-button"):
        with st.spinner(t("Suche …")):
            st.session_state["manual-check"] = updater.check(force=True, timeout=8.0)
        st.rerun()


def _update_panel() -> None:
    # Nicht auf den Hintergrundthread warten: Das Ergebnis erscheint beim nächsten Durchlauf.
    check = st.session_state.get("manual-check") or _update_check().result()
    if check is None or not check.available:
        _manual_update_check(check)
        return
    restarting = t("Wird aktualisiert und neu gestartet … Das Fenster öffnet sich gleich neu.")
    if st.session_state.get("restarting"):
        st.info(restarting)
        return
    if (
        updater.load_state().get("attempted") == check.latest
        and st.session_state.get("update-started") is None
    ):
        st.warning(
            t(
                "Version {latest} ist verfügbar, die Aktualisierung hat aber nicht gegriffen "
                "(Protokoll: `{log}`). Notfalls das Installationsskript erneut ausführen.",
                latest=check.latest,
                log=updater.log_file(),
            )
        )
        return
    with st.container(border=True):
        st.markdown(
            t(
                "**Neue Version {latest}** verfügbar (installiert: {current}).",
                latest=check.latest,
                current=check.current,
            )
        )
        if updater.mode() is updater.Mode.ON:
            st.caption(t("Wird beim Schließen automatisch installiert."))
        if st.button(t("Jetzt aktualisieren und neu starten"), icon=":material/system_update:"):
            if error := updater.restart_with_update():
                st.error(error)
                return
            st.session_state["restarting"] = True
            st.session_state["update-started"] = True
            st.info(restarting)
            _shutdown_soon()


def sidebar_footer(repo: Repository) -> None:
    """Git-Bereich und Hinweise – nach der Seite gezeichnet, damit gerade Gespeichertes
    bereits als offene Änderung erscheint."""
    _update_panel()
    _git_panel(repo)
    st.caption(
        t(
            "Daten: `{path}`  \nStichtag: {day}  \n{version}",
            path=repo.root.resolve(),
            day=f"{today():%d.%m.%Y}",
            version=status_line(),
        )
    )


COMMIT_DEFAULT = "Sprint-Daten aktualisiert"


def _commit_default() -> str:
    return t(COMMIT_DEFAULT)


def _commit_clicked(root: Path, tags: list[str]) -> None:
    """Callback des Commit-Knopfs; läuft vor dem nächsten Durchlauf des Skripts."""
    message = st.session_state.get("commit_message", "").strip() or _commit_default()
    use_tags = tags and st.session_state.get("use_tags", True)
    try:
        rev = commit_directory(root, message, tags if use_tags else None)
    except GitError as e:
        st.session_state["commit_error"] = e
        return
    st.session_state["pending_tags"] = []
    st.session_state["last_commit"] = rev
    st.session_state["commit_message"] = _commit_default()


# „Speichern und teilen“ läuft im Rückruf des Knopfs, im Skript-Thread. Kommt währenddessen eine
# weitere Anforderung des Browsers (zweiter Klick, Eingabe, ein nachlaufender Durchlauf nach dem
# Speichern), startet Streamlit sofort einen neuen Durchlauf und stoppt den alten bei dessen
# nächster Berührung von ``st.session_state``. Der alte Rückruf bricht dann nach dem Abgleich ab,
# bevor er das Ergebnis ablegt: Der Abgleich ist gelaufen, die Meldung fehlt für immer, und der
# neue Durchlauf zeigt die Seitenleiste mitten im Abgleich (Commit gemacht, Zusammenführen und
# Hochladen scheinbar nicht). Darum liegt das Ergebnis zuerst in ``_SYNC_DONE`` (ein einfaches
# Wörterbuch ohne Haltepunkt), jeder Durchlauf wartet zu Beginn auf einen noch laufenden Abgleich
# (``_SYNC_LOCK``) und holt ein dort liegendes Ergebnis nach (``collect_sync_result``), und ein
# zweiter Klick startet keinen zweiten Abgleich.
_SYNC_LOCK = threading.Lock()
_SYNC_DONE: dict[str, SyncResult] = {}


def _session_key() -> str:
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx is not None else ""


def _remember_sync_result(result: SyncResult) -> None:
    """Legt das Ergebnis eines Abgleichs im Sitzungszustand ab und bereinigt den Zustand, der
    davon abhängt. Darf mehrfach laufen (auch nach einem abgebrochenen ersten Versuch)."""
    if result.committed:
        st.session_state["pending_tags"] = []
        st.session_state["commit_message"] = _commit_default()
    st.session_state["sync_result"] = result
    st.session_state.pop("tags-server", None)  # der Abgleich der Tags ist nicht mehr aktuell
    st.session_state.pop("tags-server-failed", None)
    st.session_state.pop("unrelated-confirm", None)  # eine Bestätigung gilt nur einmal
    # Die Rückfrage zur fremden Historie bleibt über Durchläufe stehen (Ankreuzen, Knopf).
    if result.error is not None and result.error.kind == "unrelated_histories":
        st.session_state["unrelated"] = result.error
    else:
        st.session_state.pop("unrelated", None)
    if result.pulled_files:
        clear_team_cache()  # Dateien haben sich geändert: neu laden


def collect_sync_result() -> None:
    """Am Anfang jedes Durchlaufs, vor jeder Git-Abfrage: auf einen noch laufenden Abgleich
    warten (er gehört zu einem gestoppten, älteren Durchlauf) und sein Ergebnis übernehmen,
    falls jener Durchlauf es nicht mehr ablegen konnte."""
    key = _session_key()
    with _SYNC_LOCK:
        result = _SYNC_DONE.get(key)
    if result is not None:
        _remember_sync_result(result)
        _SYNC_DONE.pop(key, None)  # erst jetzt: Bricht auch dieser Durchlauf ab, bleibt es liegen


def _sync_clicked(
    root: Path, tags: list[str], allow_invalid: bool = False, allow_unrelated: bool = False
) -> None:
    """„Speichern und teilen“: eigene Änderungen sichern, die der anderen holen, hochladen."""
    if not _SYNC_LOCK.acquire(blocking=False):
        return  # ein Abgleich läuft schon (zweiter Klick); er meldet sein Ergebnis selbst
    key = _session_key()
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
        )
        _SYNC_DONE[key] = result
    finally:
        _SYNC_LOCK.release()
    _remember_sync_result(result)
    _SYNC_DONE.pop(key, None)


def _unrelated_cancel() -> None:
    st.session_state.pop("unrelated", None)
    st.session_state.pop("unrelated-confirm", None)


def _unrelated_go(root: Path, tags: list[str]) -> None:
    _unrelated_cancel()
    _sync_clicked(root, tags, allow_unrelated=True)


def _unrelated_dialog(root: Path, tags: list[str], error: GitError) -> None:
    """Der Server hat eine fremde Historie: erklären und nur nach ausdrücklicher Bestätigung
    zusammenführen. Vorgabe ist Abbrechen (Knopf gesperrt, bis das Kästchen gesetzt ist)."""
    with st.container(border=True):
        st.error(f"**{git_title(error.kind)}**  \n{error.hint}")
        st.markdown(str(error))  # nennt Server-Adresse und Branch
        page_link("datenordner", t("Server-Adresse ändern"))  # meist ist die Adresse das Problem
        sure = st.checkbox(t("Ja, beide Historien zusammenführen"), key="unrelated-confirm")
        st.button(
            t("Beide Historien zusammenführen"),
            key="unrelated-go",
            type="primary",
            disabled=not sure,
            on_click=_unrelated_go,
            args=(root, tags),
        )
        st.button(t("Abbrechen"), key="unrelated-cancel", on_click=_unrelated_cancel)


def _fetch_clicked(root: Path) -> None:
    fetch_remote(root)


def _abort_clicked(root: Path) -> None:
    try:
        abort_unfinished(root)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        st.session_state["flash"] = [("success", t("Zusammenführen abgebrochen."))]


def _reattach_clicked(root: Path) -> None:
    try:
        branch = reattach(root)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        st.session_state["flash"] = [
            ("success", t("Zurück auf den Branch {branch}.", branch=branch))
        ]


def _identity_clicked() -> None:
    try:
        set_identity(st.session_state.get("git-name", ""), st.session_state.get("git-email", ""))
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        st.session_state["flash"] = [
            ("success", t("Name und E-Mail-Adresse gespeichert. Bitte noch einmal versuchen."))
        ]


def _show_problem(error: GitError) -> None:
    """Fehler mit Überschrift, nächstem Schritt und (aufklappbar) der Meldung von Git."""
    st.error(f"**{git_title(error.kind)}**  \n{error.hint or error}")
    if error.hint and str(error):
        with st.expander(t("Technische Meldung")):
            st.code(str(error), language=None)
    if error.kind == "identity":
        st.text_input(t("Name"), key="git-name")
        st.text_input(t("E-Mail-Adresse"), key="git-email")
        st.button(t("Speichern"), key="git-identity", on_click=_identity_clicked)


def _show_sync_result(result: SyncResult, root: Path, tags: list[str]) -> None:
    done = []
    if result.committed:
        done.append(t("Eigene Änderungen gesichert ({rev})", rev=result.committed))
    if result.pulled:
        done.append(t("{count} Änderung(en) von anderen übernommen", count=len(result.pulled)))
    if result.pushed:
        done.append(t("Hochgeladen"))
    if result.error is None:
        st.success(" · ".join(done) if done else t("Alles ist auf dem aktuellen Stand."))
    else:
        if done:
            st.info(t("Bis hierhin erledigt:") + " " + " · ".join(done))
        if result.error.kind != "unrelated_histories":  # die Rückfrage steht darunter
            _show_problem(result.error)
        if result.error.kind == "not_found":  # meist stimmt die Adresse nicht
            page_link("datenordner", t("Server-Adresse ändern"))
        if result.validation:
            st.markdown("\n".join(f"- {line}" for line in result.validation))
            st.button(
                t("Trotzdem teilen"),
                key="git-force",
                on_click=_sync_clicked,
                args=(root, tags, True),
                help=t("Lädt die Daten hoch, obwohl die Prüfung neue Fehler meldet."),
            )
    for note in result.notes:  # Hinweise, auch wenn alles gelang
        st.warning(note)
    if result.pulled:
        with st.expander(t("Neu von anderen"), expanded=True):
            _show_incoming(result.pulled, result.pulled_files)


def _show_incoming(commits: list[Commit], files: list[tuple[str, str]]) -> None:
    for c in commits:
        st.markdown(f"`{c.rev}` {c.day} **{c.author}**: {c.subject}")
    if files:
        st.code("\n".join(f"{status:>2} {file}" for status, file in files), language=None)


def _status_text(state: SyncState) -> str:
    """Eine Zeile zum Stand gegenüber dem Server."""
    if state.unfinished or state.conflicts:
        return t("Zusammenführen unvollständig")
    if state.detached:
        return t("Kein Branch ausgewählt")
    if state.remote is None:
        return t("Kein Server eingerichtet – Änderungen bleiben lokal.")
    parts = []
    if state.ahead:
        parts.append(t("{count} noch nicht geteilt", count=state.ahead))
    if state.behind:
        parts.append(t("{count} neu von anderen", count=state.behind))
    if not parts and state.unborn:
        parts.append(t("noch keine Daten gespeichert"))
    elif not parts and state.upstream is None:
        # Server eingetragen, aber der Branch ist noch nie hochgeladen (frisch gesetzter, meist
        # leerer Server): „synchron“ wäre falsch, es liegt noch nichts dort.
        parts.append(t("noch nicht auf dem Server – „Speichern und teilen“ lädt hoch"))
    elif not parts:
        parts.append(t("synchron mit {upstream}", upstream=state.upstream))
    if state.fetch_error is not None:
        parts.append(
            t("Server nicht erreichbar")
            if state.offline
            else t("Server meldet: {kind}", kind=git_title(state.fetch_error.kind))
        )
    elif state.fetched_at is None:
        parts.append(t("Serverstand noch nicht geprüft"))
    else:
        minutes = int((time.time() - state.fetched_at) // 60)
        parts.append(
            t("Serverstand geprüft vor {minutes} Min.", minutes=minutes)
            if minutes
            else t("Serverstand gerade geprüft")
        )
    return " · ".join(parts)


def _git_panel(repo: Repository) -> None:
    if not git_available():
        _show_problem(classify("", missing=True))
        return
    if git_root(repo.root) is None:
        st.caption(t("Datenverzeichnis liegt in keinem Git-Repository – Commit nicht möglich."))
        return
    if last := st.session_state.pop("last_commit", None):
        st.success(t("Committet ({rev}). Geteilt wird erst mit „Speichern und teilen“.", rev=last))
    if error := st.session_state.pop("commit_error", None):
        if isinstance(error, GitError):
            _show_problem(error)
        else:
            st.error(error)
    if result := st.session_state.pop("sync_result", None):
        _show_sync_result(result, repo.root, list(st.session_state.get("pending_tags", [])))
    if unrelated := st.session_state.get("unrelated"):
        _unrelated_dialog(repo.root, list(st.session_state.get("pending_tags", [])), unrelated)
    try:
        changes = cached_pending_changes(repo.root)
        state = cached_sync_state(repo.root)
    except GitError as e:
        st.warning(
            t(
                "Git meldet ein Problem mit dem Datenordner. Bitte im Datei-Manager prüfen, ob "
                "der Ordner noch da und beschreibbar ist (bei Netzlaufwerken: verbunden), und "
                "die Seite neu laden. Hilfe: Seite „Hilfe“, Reiter „Zusammenarbeit (Git)“."
            )
        )
        with st.expander(t("Technische Meldung")):
            st.code(str(e), language=None)
        return
    tags = st.session_state.get("pending_tags", [])
    st.caption(_status_text(state))
    if state.remote is None:
        page_link("datenordner", t("Server einrichten"))
    with st.expander(
        t("Git: {count} offene Änderung(en)", count=len(changes))
        if changes
        else t("Git: alles committet"),
        expanded=bool(changes) or state.behind > 0 or state.unfinished is not None,
        icon=":material/commit:",
    ):
        if state.unfinished or state.conflicts:
            st.warning(hint_for("conflict"))
            st.button(
                t("Zusammenführen abbrechen"),
                key="git-abort",
                on_click=_abort_clicked,
                args=(repo.root,),
            )
            return
        if state.detached:
            st.warning(hint_for("detached"))
            st.button(
                t("Zurück auf den Branch"),
                key="git-reattach",
                on_click=_reattach_clicked,
                args=(repo.root,),
            )
            return
        if state.behind:
            commits, files = incoming(repo.root)
            st.markdown(t("**Neu von anderen** (noch nicht übernommen)"))
            _show_incoming(commits, files)
        if changes:
            st.code("\n".join(f"{status:>2} {file}" for status, file in changes), language=None)
            st.session_state.setdefault("commit_message", _commit_default())
            st.text_input(t("Commit-Nachricht"), key="commit_message")
            if tags:
                st.checkbox(
                    t("Tags setzen: {tags}", tags=", ".join(tags)), value=True, key="use_tags"
                )
        else:
            st.caption(t("Keine offenen Änderungen im Datenverzeichnis."))
        if state.remote is not None:
            st.button(
                t("Speichern und teilen"),
                type="primary",
                icon=":material/sync:",
                key="git-sync",
                on_click=_sync_clicked,
                args=(repo.root, list(tags)),
                help=t(
                    "Sichert deine Änderungen, holt die der anderen, führt beides zusammen und "
                    "lädt es hoch."
                ),
            )
            st.button(
                t("Stand prüfen"),
                icon=":material/refresh:",
                key="git-fetch",
                on_click=_fetch_clicked,
                args=(repo.root,),
                help=t("Fragt den Server, ob es Neues gibt (ändert nichts)."),
            )
        if changes:
            st.button(
                t("Änderungen committen"),
                type="secondary" if state.remote is not None else "primary",
                icon=":material/save:",
                on_click=_commit_clicked,
                args=(repo.root, list(tags)),
                help=t("Nur lokal sichern, ohne zu teilen."),
            )


# --- Änderungen verwerfen, Verlauf, Tags -----------------------------------------------------

# Statuswerte von ``git status --porcelain`` (ohne Leerzeichen), auch kombiniert.
_STATUS_NAMES = {
    "M": "geändert", "MM": "geändert", "T": "geändert", "TM": "geändert",
    "D": "gelöscht", "MD": "gelöscht",
    "A": "neu", "??": "neu", "AM": "neu", "AD": "neu, danach gelöscht",
    "R": "umbenannt", "RM": "umbenannt und geändert", "RD": "umbenannt, danach gelöscht",
    "C": "kopiert", "CM": "kopiert und geändert",
    "DD": "Konflikt", "UU": "Konflikt", "AA": "Konflikt", "UD": "Konflikt", "DU": "Konflikt",
    "AU": "Konflikt", "UA": "Konflikt",
}  # fmt: skip


def status_name(status: str) -> str:
    """Verständlicher Name eines Git-Status (unbekannte gelten als „geändert“)."""
    return t(_STATUS_NAMES.get(status, "geändert"))


def _lost_status(item: Lost) -> str:
    """Status einer verlorenen Änderung; bei Umbenennungen mit altem und neuem Pfad."""
    name = status_name(item.status)
    if item.orig:
        # Als Code: Pfade können Zeichen enthalten, die Markdown sonst deutet.
        return t(
            "{name}: {orig} → {file}", name=name, orig=md_code(item.orig), file=md_code(item.file)
        )
    return name


def _git_action(action: Callable[[], object], ok: Callable[[object], str]) -> None:
    """Führt einen Git-Vorgang im Callback aus; Meldung oder Fehler erscheinen im nächsten
    Durchlauf."""
    try:
        result = action()
    except GitError as e:
        st.session_state["commit_error"] = e
        return
    clear_team_cache()
    kind = "success"
    if isinstance(result, GitError):  # Warnung, z. B. Tag nur lokal gesetzt
        kind, text = "warning", t("Nur lokal erledigt: {error}", error=result.full())
    else:
        text = ok(result)
    st.session_state["flash"] = [(kind, text)]


def _tags_check_clicked(root: Path) -> None:
    """Fragt den Server nach den Tags (Netzwerk, nur auf Klick) und merkt das Ergebnis."""
    try:
        tags = list_tags(root, check_server=True)
        # Ohne lokale Tags verrät die Liste nicht, ob der Abgleich gelang.
        st.session_state["tags-server-failed"] = not tags and not server_reachable(root)
        st.session_state["tags-server"] = tags
    except GitError as e:
        st.session_state["commit_error"] = e


def _tags_recheck(root: Path) -> None:
    """Nach einer Tag-Aktion den bereits abgefragten Serverstand erneuern."""
    if "tags-server" in st.session_state:
        _tags_check_clicked(root)


def _tag_delete_go(root: Path, name: str) -> None:
    st.session_state.pop(f"tag-confirm-{name}", None)  # die Bestätigung gilt nur einmal
    _git_action(
        lambda: delete_tag(root, name),
        lambda _: t("Tag {name} gelöscht.", name=name),
    )
    _tags_recheck(root)


def _tag_upload_go(root: Path, name: str) -> None:
    _git_action(
        lambda: upload_tag(root, name),
        lambda _: t("Tag {name} zum Server übertragen.", name=name),
    )
    _tags_recheck(root)


def _tag_state(tag: Tag) -> str:
    """Wo es den Tag gibt (leer, solange der Server nicht abgefragt wurde)."""
    if not tag.local:
        return t("nur auf dem Server")
    if tag.on_server is None:
        return ""
    if not tag.on_server:
        return t("nur lokal")
    return t("unterschiedlich") if tag.differs else t("auf dem Server")


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
            t("Änderungen verworfen. Sicherungskopie: {path}", path=trash)
            if trash
            else t("Änderungen verworfen.")
        ),
    )


def _tab_changes(repo: Repository, locked: bool = False) -> None:
    lost = discard_preview(repo.root)
    if not lost:
        st.success(t("Keine offenen Änderungen im Datenverzeichnis."))
        return
    st.caption(
        t(
            "Verwerfen setzt Dateien auf den letzten gespeicherten (committeten) Stand zurück. "
            "Vorher wird eine Sicherungskopie im Papierkorb unter `.git` angelegt."
        )
    )
    for i, item in enumerate(lost):
        st.checkbox(
            t(
                "{file} – {status} (+{added} −{removed} Zeilen)",
                file=item.file,
                status=_lost_status(item),
                added=item.added,
                removed=item.removed,
            ),
            key=f"disc-{i}",
        )
    left, right = st.columns(2)
    left.button(
        t("Ausgewählte verwerfen …"), on_click=_discard_selected, args=(lost,), disabled=locked
    )
    right.button(t("Alles verwerfen …"), on_click=_discard_request, args=(None,), disabled=locked)
    request = st.session_state.get("discard-request")
    if request is None:
        return
    files = None if request == "ALL" else request
    shown = [item for item in lost if files is None or item.file in files]
    with st.container(border=True):
        st.warning(
            t(
                "Das geht verloren ({count} Datei(en)):  \n{list}",
                count=len(shown),
                list="  \n".join(
                    f"`{i.file}` – {_lost_status(i)}, +{i.added} −{i.removed}" for i in shown
                ),
            )
        )
        sure = st.checkbox(t("Ja, diese Änderungen verwerfen"), key="discard-confirm")
        ok, cancel = st.columns(2)
        ok.button(
            t("Jetzt verwerfen"),
            type="primary",
            disabled=not sure or locked,
            on_click=_discard_go,
            args=(repo.root, files),
        )
        cancel.button(t("Abbrechen"), on_click=_discard_cancel)


def _entry_label(e: HistoryEntry) -> str:
    return f"{e.day} · {e.author} · {e.subject} ({e.short})"


def _tab_history(repo: Repository, locked: bool = False) -> None:
    team = st.session_state.get("selected_team")
    scopes = [t("Datenordner")]
    if team and repo.exists(team):
        scopes = [t("Team"), t("Sprint"), t("Datei"), *scopes]
    kind = st.radio(t("Anzeigen für"), scopes, horizontal=True, key="history-scope")
    scope = repo.root
    if team and repo.exists(team) and kind != t("Datenordner"):
        base = repo.team_dir(team)
        scope = base
        if kind == t("Sprint"):
            ids = sorted(p.stem for p in (base / "sprints").glob("*.yaml"))
            if ids:
                scope = base / "sprints" / f"{st.selectbox(t('Sprint'), ids[::-1])}.yaml"
        elif kind == t("Datei"):
            files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*.yaml"))
            scope = base / st.selectbox(t("Datei"), files)
    entries = history(repo.root, scope)
    if not entries:
        st.info(t("Noch keine gespeicherten Änderungen für diese Auswahl."))
        return
    chosen = st.selectbox(
        t("Stand"), entries, format_func=_entry_label, key=f"history-entry-{scope}"
    )
    if chosen.files:
        st.code("\n".join(chosen.files), language=None)
    rel = scope.resolve().relative_to(git_root(repo.root) or repo.root.resolve()).as_posix()
    left, right = st.columns(2)
    left.button(
        t("Diesen Stand wiederherstellen"),
        type="primary",
        key="history-restore",
        disabled=locked,
        on_click=_git_action,
        args=(
            lambda: restore_version(repo.root, scope, chosen.rev),
            lambda rev: t("Wiederhergestellt als neue Änderung ({rev}).", rev=rev),
        ),
        help=t(
            "Setzt {scope} auf den Stand nach dieser Änderung zurück. Das ist selbst eine "
            "Änderung und kann hier wieder zurückgenommen werden.",
            scope=rel,
        ),
    )
    right.button(
        t("Diese Änderung zurücknehmen"),
        key="history-revert",
        disabled=chosen.merge or locked,
        on_click=_git_action,
        args=(
            lambda: revert_commit(repo.root, chosen.rev),
            lambda rev: t("Zurückgenommen als neue Änderung ({rev}).", rev=rev),
        ),
        help=t("Macht genau diese Änderung rückgängig (z. B. eine Wiederherstellung)."),
    )


def _tab_tags(repo: Repository, locked: bool = False) -> None:
    checked = st.session_state.get("tags-server")
    tags = checked if checked is not None else list_tags(repo.root)
    st.button(
        t("Mit dem Server abgleichen"),
        key="tags-check",
        icon=":material/refresh:",
        on_click=_tags_check_clicked,
        args=(repo.root,),
        help=t("Fragt den Server nach seinen Tags (Netzwerk) und zeigt, wo es welchen gibt."),
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
                "Der Server konnte nicht abgefragt werden (nicht erreichbar oder nicht "
                "eingerichtet). Angezeigt sind nur die Tags auf diesem Rechner."
            )
        )
    if tags:
        st.table(
            pd.DataFrame(
                [(tag.name, _tag_state(tag), tag.target, tag.day, tag.subject) for tag in tags],
                columns=[t("Tag"), t("Server"), t("Stand"), t("Datum"), t("Nachricht")],
            ).set_index(t("Tag"))
        )
    else:
        st.caption(t("Noch keine Tags."))
    local_only = [tag.name for tag in tags if tag.local and tag.on_server is False]
    if local_only:
        st.selectbox(t("Tag zum Server übertragen"), local_only, key="tag-upload")
        st.button(
            t("Zum Server übertragen"),
            key="tag-upload-go",
            disabled=locked,
            on_click=_tag_upload_go,
            args=(repo.root, st.session_state.get("tag-upload", local_only[0])),
        )
    entries = history(repo.root, limit=60)
    with st.form("tag-set"):
        name = st.text_input(t("Neuer Tag"), placeholder="team/2026.21")
        target = st.selectbox(
            t("Am Stand"), entries or [None], format_func=lambda e: _entry_label(e) if e else "HEAD"
        )
        message = st.text_input(t("Nachricht (optional)"))
        if st.form_submit_button(t("Tag setzen"), disabled=locked):
            _git_action(
                lambda: set_tag(repo.root, name, target.rev if target else "HEAD", message or None),
                lambda _: t("Tag {name} gesetzt und geteilt.", name=name),
            )
            _tags_recheck(repo.root)
            st.rerun()
    if tags:
        doomed = st.selectbox(t("Tag löschen"), [tag.name for tag in tags])
        # Die Bestätigung gehört zum gewählten Tag: Ein Wechsel der Auswahl verlangt eine neue.
        sure = st.checkbox(
            t("Ja, den Tag lokal und auf dem Server löschen"), key=f"tag-confirm-{doomed}"
        )
        st.button(
            t("Tag löschen"),
            disabled=not sure or locked,
            on_click=_tag_delete_go,
            args=(repo.root, doomed),
        )


def page_history(repo: Repository) -> None:
    st.header(t("Änderungen und Verlauf"))
    if problem := st.session_state.pop("commit_error", None):
        if isinstance(problem, GitError):
            _show_problem(problem)
        else:
            st.error(problem)
    if not git_available():
        _show_problem(classify("", missing=True))
        return
    if git_root(repo.root) is None:
        st.info(t("Datenverzeichnis liegt in keinem Git-Repository – Commit nicht möglich."))
        return
    locked = _merge_open(repo)
    if locked:
        st.warning(
            t(
                "Ein Zusammenführen ist noch offen. Solange es nicht abgeschlossen oder "
                "abgebrochen ist, sind Wiederherstellen, Zurücknehmen, Verwerfen und Tags "
                "gesperrt (Git würde sie ablehnen). Bitte zuerst den Konflikt lösen oder "
                "„Zusammenführen abbrechen“ wählen – beides geht auf jeder Teamseite."
            )
        )
    changes, history_tab, tags = st.tabs([t("Offene Änderungen"), t("Verlauf"), t("Tags")])
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
    "analyse": page_analysis,
    "personen": page_people,
    "produktliste": page_product_list,
    "einstellungen": page_settings,
}
# Seiten, die keine Prognose anzeigen und daher nur den Stichtag aus ``fc`` lesen.
NO_FORECAST = {"personen", "produktliste", "einstellungen"}
GLOBAL_PAGES = {
    "datenordner": page_data_dir,
    "verlauf": page_history,
    "neues_team": page_new_team,
    "pruefung": page_check,
    "hilfe": page_help,
}


# --- Konflikte lösen und veraltete Eingaben -------------------------------------------------

# Zustand, der bei geänderten Dateien erhalten bleibt (alles andere sind Formulareingaben).
_KEEP_STATE = {
    "selected_team", "flash", "pending_tags", "commit_message", "use_tags", "language",
    "enabled-pages", "sync_result", "last_commit", "commit_error", "restarting", "update-started",
    "manual-check", "offer-init", "browse-error", "seen-versions", "planning-step",
    "planning-goto", "planning-last-sprint", "board-sprint", "formula-sprint",
    "active-data-dir", "folder-state",
}  # fmt: skip


def _discard_stale_inputs(repo: Repository, team: str) -> None:
    """Haben sich die Dateien des Teams seit dem letzten Zeichnen geändert (Teilen, andere
    Programme), sind offene Formulare veraltet: Ein Speichern würde fremde Änderungen
    überschreiben. Die Eingaben werden dann verworfen und neu aus den Dateien gelesen."""
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
            "Die Daten haben sich geändert, seit diese Seite geöffnet wurde (z. B. durch Teilen "
            "oder eine andere Person). Nicht gespeicherte Eingaben wurden verworfen und die "
            "Seite neu geladen – bitte prüfen und noch einmal speichern."
        )
    )


def _remember_version(repo: Repository, team: str) -> None:
    seen = st.session_state.setdefault("seen-versions", {})
    seen[f"{repo.root.resolve()}|{team}"] = team_version(repo.team_dir(team))


def _show_value(value: object) -> str:
    if value is MISSING:
        return t("(entfernt)")
    text = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, width=1000).strip()
    return text.removesuffix("\n...").strip()[:200]


def _conf_key(i: int, j: int | None) -> str:
    return f"conf-{i}-{'file' if j is None else j}"


def _resolve_clicked(root: Path, pending: list[ConflictFile], tags: list[str]) -> None:
    """Übernimmt die Entscheidungen und setzt „Speichern und teilen“ fort."""
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
    _sync_clicked(root, tags)


def _restore_clicked(root: Path, file: Path) -> None:
    try:
        restore_file(root, file)
    except GitError as e:
        st.session_state["commit_error"] = e
    else:
        clear_team_cache()
        st.session_state["flash"] = [
            ("success", t("{file} auf den letzten gespeicherten Stand zurückgesetzt.", file=file))
        ]


def page_conflicts(repo: Repository, error: ConflictError | None = None) -> None:
    """Geführte Wiederherstellung: Solange Konflikte offen sind, ist die Bearbeitung gesperrt."""
    st.header(t("Konflikte lösen"))
    st.warning(
        t(
            "Zwei Personen haben dieselben Daten geändert. Bis der Konflikt gelöst ist, ist die "
            "Bearbeitung gesperrt, damit nichts überschrieben wird. Nichts ist verloren: "
            "Beide Fassungen sind gesichert."
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
                "Pro Eintrag gilt: **Meine Änderung** behält, was du eingetragen hast, "
                "**Andere Änderung** übernimmt, was die andere Person eingetragen hat. Danach "
                "wird alles zusammengeführt, geprüft und geteilt."
            )
        )
        ready = True
        for i, cf in enumerate(pending):
            if not cf.open:
                st.caption(t("{file}: wird automatisch zusammengeführt", file=cf.file))
                continue
            with st.container(border=True):
                st.markdown(f"**{cf.file}**")
                if cf.whole:
                    mine = t("(von mir gelöscht)") if cf.ours_deleted else t("meine Fassung")
                    theirs = (
                        t("(von anderen gelöscht)") if cf.theirs_deleted else t("andere Fassung")
                    )
                    st.caption(t("Die Datei lässt sich nur als Ganzes entscheiden."))
                    options = {"ours": t("Meine Änderung: {v}", v=mine),
                               "theirs": t("Andere Änderung: {v}", v=theirs)}  # fmt: skip
                    pick = st.radio(
                        cf.file, list(options), format_func=options.get, index=None,
                        key=_conf_key(i, None), label_visibility="collapsed",
                    )  # fmt: skip
                    ready = ready and pick is not None
                for j, kc in enumerate(cf.keys):
                    options = {
                        "ours": t("Meine Änderung: {v}", v=_show_value(kc.ours)),
                        "theirs": t("Andere Änderung: {v}", v=_show_value(kc.theirs)),
                    }
                    pick = st.radio(
                        f"`{kc.label}`", list(options), format_func=options.get, index=None,
                        key=_conf_key(i, j),
                    )  # fmt: skip
                    ready = ready and pick is not None
        left, right = st.columns(2)
        left.button(
            t("Entscheidungen übernehmen und teilen"),
            type="primary",
            disabled=not ready,
            on_click=_resolve_clicked,
            args=(repo.root, pending, list(tags)),
            key="conf-apply",
        )
        right.button(
            t("Zusammenführen abbrechen"),
            on_click=_abort_clicked,
            args=(repo.root,),
            key="conf-abort",
            help=t("Verwirft das Zusammenführen; deine eigenen Änderungen bleiben erhalten."),
        )
        return
    # Konfliktmarkierungen ohne offenes Zusammenführen (z. B. von einem anderen Programm).
    files = error.files if error else []
    st.error(
        t(
            "In diesen Dateien stehen Konfliktmarkierungen (`<<<<<<<`), aber es läuft kein "
            "Zusammenführen mehr. Die Datei kann auf den letzten gespeicherten Stand "
            "zurückgesetzt werden; Änderungen darin, die nicht committet sind, gehen verloren."
        )
    )
    for n, file in enumerate(files):
        left, right = st.columns([4, 2], vertical_alignment="center")
        left.code(str(file), language=None)
        right.button(
            t("Letzten Stand wiederherstellen"),
            key=f"conf-restore-{n}",
            on_click=_restore_clicked,
            args=(repo.root, file),
        )


def _merge_open(repo: Repository) -> bool:
    """Läuft ein Zusammenführen (oder Rebase) noch bzw. gibt es Konflikte? Dann ist jede
    schreibende Seite gesperrt."""
    if not git_available() or git_root(repo.root) is None:
        return False
    try:
        current = cached_sync_state(repo.root)
    except GitError:
        return False
    return current.unfinished in ("merge", "rebase") or bool(current.conflicts)


# Globale Seiten, die Dateien anlegen oder ändern (die übrigen lesen nur oder prüfen selbst).
LOCKED_PAGES = {"neues_team"}


def run_page(key: str) -> None:
    """Wird von den Seitendateien unter web/seiten aufgerufen."""
    repo = repository()
    show_flash()  # einmal zentral: Hinweise erscheinen auf jeder Seite, nie später woanders
    if needs_setup(repo.root):
        page_data_dir(repo, setup=True)
        return
    team = st.session_state.get("selected_team")
    # Offenes Zusammenführen: Die Bearbeitung ist gesperrt, bis es gelöst ist.
    if (key in LOCKED_PAGES or key not in GLOBAL_PAGES) and _merge_open(repo):
        page_conflicts(repo)
        return
    if key in GLOBAL_PAGES:
        GLOBAL_PAGES[key](repo)
        return
    if team is None or not repo.exists(team):
        st.header(t(PAGE_INFO[key][0]))
        st.info(
            t("Noch kein Team vorhanden – ein Team anlegen oder über ein Import-Plugin übernehmen.")
        )
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
    # Die Seiten Personen, Produkte und Einstellungen brauchen nur den Stichtag.
    fc = Forecast(data, today(), []) if key in NO_FORECAST else build_forecast(data, today())
    try:
        TEAM_PAGES[key](repo, data, fc)
    except FileAccessError as e:  # Schreib- oder Löschfehler außerhalb von save()
        st.error(str(e))
    finally:
        # Auch nach ``st.rerun()`` (eine Ausnahme): Der eigene Speicherstand gilt als gesehen,
        # sonst hielte der nächste Durchlauf ihn für eine fremde Änderung.
        _remember_version(repo, team)


def run_plugin_page(page: WebPage) -> None:
    """Seite eines Plugins (siehe sprintforecast.plugins)."""
    repo = repository()
    show_flash()
    if _merge_open(repo):
        page_conflicts(repo)
        return
    try:
        page.render(repo)
    except FileAccessError as e:  # Schreib- oder Lesefehler im Plugin
        st.error(str(e))
