# SPDX-License-Identifier: EUPL-1.2
"""Seiten und Seitenleiste der Weboberfläche. Einstieg: web/app.py, Seiten: web/seiten/*.py.

Liest und schreibt dieselben YAML-Dateien wie die Kommandozeile. Konfiguration über
Umgebungsvariablen: SPRINTFORECAST_DATEN (Datenverzeichnis), SPRINTFORECAST_STICHTAG.
Texte sind über i18n.t übersetzbar; interne Spaltenschlüssel der Tabellen bleiben deutsch,
angezeigt werden die übersetzten Beschriftungen.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from sprintforecast import updater
from sprintforecast.analysis import (
    average_focus_factor,
    band,
    buffer_hint,
    completion,
    focus_factor,
)
from sprintforecast.calendar import day_label, holiday_name, workdays
from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource
from sprintforecast.forecast import (
    Forecast,
    TimelineEntry,
    apply_planning,
    build_forecast,
    find_sprint,
    freeze_plan,
    refreeze_offer,
)
from sprintforecast.formulas import general, steps
from sprintforecast.formulas import step as formula_step
from sprintforecast.git import (
    NO_WINDOW,
    GitError,
    clone_repository,
    commit_directory,
    init_data_repository,
    pending_changes,
)
from sprintforecast.git import repo_root as git_root
from sprintforecast.guide import CAPACITY_SOURCES, COMMANDS, FIELDS, TERMS, WORKFLOW, command_text
from sprintforecast.i18n import LANGUAGES, language, save_language, set_language, t
from sprintforecast.model import Numbering, Planning, Sprint, Team
from sprintforecast.plugins import WebPage
from sprintforecast.products import (
    MEASURES,
    PRODUCTION_MEASURES,
    Distribution,
    balance,
    by_po,
    distribution,
    measure_label,
)
from sprintforecast.report import capacity_label, fmt, pct, period, render, source_label, status
from sprintforecast.settings import REGIONS, SETTINGS, Kind, Setting, applicable, changes
from sprintforecast.storage import (
    DATA_ENV,
    STICHTAG_ENV,
    DataError,
    Repository,
    TeamData,
    default_data_dir,
    save_data_dir,
    teams_dir,
)
from sprintforecast.updater import status_line
from sprintforecast.validate import Level, check_all, check_team
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
    calendar_table,
    calendar_to_save,
    default_forecast_ist,
    edit_absences,
    open_velocity_sprints,
    parse_numbers,
    people_from_table,
    people_table,
    product_table,
    product_values_table,
    products_from_table,
    record_prognoses,
    resettable_sprints,
    sprints_to_save,
    whatif_forecast,
    with_people,
    with_sprints,
)

# Seiten: Dateiname unter web/seiten → (Titel, Material-Icon). Gruppen für die Navigation.
# Titel und Gruppen sind deutsche Quelltexte und werden bei der Anzeige übersetzt.
PAGES: dict[str, dict[str, tuple[str, str]]] = {
    "Sprint": {
        "forecast": ("Forecast", ":material/trending_up:"),
        "fehltage": ("Fehltage", ":material/event_busy:"),
        "sprints": ("Sprintkalender", ":material/calendar_month:"),
        "produkte": ("Produktverteilung", ":material/pie_chart:"),
        "analyse": ("Analyse", ":material/insights:"),
    },
    # Die drei Boards in zeitlicher Reihenfolge: vor dem Planning, Planning, Review.
    "Boards": {
        "vorplanung": ("PO-Vorplanung", ":material/groups:"),
        "planning": ("Planning", ":material/edit_note:"),
        "review": ("Review", ":material/task_alt:"),
    },
    "Team": {
        "personen": ("Personen", ":material/group:"),
        "produktliste": ("Produkte", ":material/category:"),
        "einstellungen": ("Einstellungen", ":material/tune:"),
        "neues_team": ("Neues Team", ":material/group_add:"),
    },
    "Daten & Hilfe": {
        "datenordner": ("Datenordner", ":material/folder_open:"),
        "pruefung": ("Prüfung", ":material/fact_check:"),
        "hilfe": ("Hilfe", ":material/help:"),
    },
}
PAGE_INFO = {key: info for group in PAGES.values() for key, info in group.items()}


def page_path(key: str) -> str:
    return f"seiten/{key}.py"


def page_link(key: str, label: str | None = None) -> None:
    title, icon = PAGE_INFO[key]
    st.page_link(page_path(key), label=label or t(title), icon=icon)


def today() -> date:
    raw = os.environ.get(STICHTAG_ENV)
    return date.fromisoformat(raw) if raw else date.today()


def repository() -> Repository:
    return Repository(default_data_dir())


def apply_language() -> None:
    """Sprache für diesen Durchlauf festlegen (aus Einstellung bzw. Umgebung)."""
    set_language(None)
    set_language(language())


def _language_changed() -> None:
    code = st.session_state["language"]
    save_language(code)
    set_language(code)


def help_text(key: str) -> str:
    f = FIELDS[key]
    return f"{t(f.what)}\n\n{t('Quelle')}: {t(f.source)}\n\n{t('Beispiel')}: {t(f.example)}"


def _steps_frame(fc: Forecast, entry: TimelineEntry) -> pd.DataFrame:
    return pd.DataFrame([{t("Kennzahl"): s.name, t("Formel"): s.formula} for s in steps(fc, entry)])


# --- Speichern mit Prüfung -----------------------------------------------------------


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
    paths = write()
    for i in relevant:
        if i.level is Level.WARNING:
            notify("warning", f"{i.where}: {i.message}")
    if tag:
        tags = st.session_state.setdefault("pending_tags", [])
        if tag not in tags:
            tags.append(tag)
    notify(
        "success",
        t(
            "Gespeichert: {names}. In Git übernehmen mit **Änderungen committen** in der "
            "Seitenleiste.",
            names=", ".join(p.name for p in paths),
        ),
    )
    return True


def show_flash() -> None:
    for kind, text in st.session_state.pop("flash", []):
        getattr(st, kind)(text)


def sprint_caption(data: TeamData, s: Sprint) -> str:
    """Zeitraum, Arbeitstage und Feiertage eines Sprints."""
    days = workdays(s.start, s.end)
    region = data.team.capacity.region
    hol = [f"{d:%d.%m.} {name}" for d in days if (name := holiday_name(d, region))]
    last = f"{days[-1]:%d.%m.%Y}" if days else f"{s.end:%d.%m.%Y}"
    text = t(
        "**{id}**: {start} – {last} (letzter Arbeitstag; der nächste Sprint beginnt am {next}), "
        "{days} Arbeitstage Mo–Fr",
        id=s.id,
        start=f"{s.start:%d.%m.}",
        last=last,
        next=f"{s.end:%d.%m.}",
        days=len(days),
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
    """Prognose des Teams für offene Sprints: Forecast IST − voraussichtlich nicht erledigt +
    zusätzlich erledigt = erwartete Velocity. Nichts wird gespeichert."""
    assumed: dict[str, Assumption] = {}
    for sprint in open_velocity_sprints(fc):
        st.markdown(f"**{t('Sprint {id}', id=sprint.id)}**")
        default_ist = default_forecast_ist(fc, sprint)
        ist_col, open_col, extra_col, result_col = st.columns(4)
        ist = ist_col.number_input(
            t("Forecast IST ({unit})", unit=unit),
            min_value=0.0,
            value=default_ist,
            step=0.25,
            format="%.2f",
            key=f"{prefix}-{sprint.id}-ist",
            help=t(
                "Eingeplante Menge des Sprints. Vorbelegt mit dem erfassten Forecast IST, "
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
            help=t("Menge, die laut Prognose zusätzlich zum Forecast IST geschafft wird."),
        )
        changed = not_done is not None or extra is not None or ist != default_ist
        if ist is None or not changed:
            result_col.metric(t("Erwartet erledigt"), "–")
            continue
        assumed[sprint.id] = Assumption(ist, not_done, extra)
        result_col.metric(t("Erwartet erledigt"), f"{fmt(assumed[sprint.id].expected, 2)} {unit}")
    return assumed


def _whatif_panel(fc: Forecast, upcoming: list[TimelineEntry], unit: str) -> None:
    """Was-wäre-wenn: erwartete erledigte Menge offener Sprints → Forecast PLAN der nächsten."""
    sprints = open_velocity_sprints(fc)
    if not sprints:
        return
    with st.expander(
        t("Was-wäre-wenn: mit erwarteter Velocity rechnen"), icon=":material/science:"
    ):
        st.caption(
            t(
                "Prognose des Teams für einen noch nicht abgeschlossenen Sprint eintragen: "
                "Forecast IST, was voraussichtlich nicht fertig wird und was zusätzlich geschafft "
                "wird. "
                "Der Forecast PLAN der nächsten Sprints wird damit neu berechnet. Nichts wird "
                "gespeichert.",
                unit=unit,
            )
        )
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


def page_forecast(repo: Repository, data: TeamData, fc: Forecast) -> None:
    team = data.team
    unit = team.unit.value
    st.header(f"Forecast {team.name}")
    _next_dates(fc)
    upcoming = fc.upcoming()
    cols = st.columns(min(len(upcoming), 4) or 1)
    for col, e in zip(cols, upcoming, strict=False):
        col.metric(
            f"{e.sprint.id} ({status(fc, e).replace('*', '')})",
            f"{fmt(e.result.plan)} {unit}",
            help=_formula_help(fc, e, "plan")
            + "\n\n"
            + t(
                "Kapazität {capacity} PT · Roadmap {roadmap} · Kleinkram {small}",
                capacity=capacity_label(e),
                roadmap=fmt(e.result.roadmap, 2),
                small=fmt(e.result.small_stuff, 2),
            ),
        )

    capacity_col, trend_col, plan_col = (
        t("Kapazität (PT)"),
        t("n. Velocity-Trend"),
        f"Forecast PLAN ({unit})",
    )
    small_col = t("Kleinkram")
    rows = [
        {
            "Sprint": e.sprint.id,
            t("Zeitraum"): period(e),
            "Status": status(fc, e).replace("*", ""),
            capacity_col: capacity_label(e),
            trend_col: fmt(e.result.normalized_velocity.trend, 2),
            plan_col: fmt(e.result.plan),
            "Roadmap": fmt(e.result.roadmap, 2),
            small_col: fmt(e.result.small_stuff, 2),
        }
        for e in upcoming
    ]
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
    trend = [e.sprint.id for e in upcoming if e.result.plan_capacity_source is CapacitySource.TREND]
    if trend:
        st.warning(
            t(
                "Für {sprints} sind noch keine Fehltage erfasst – die Kapazität ist nur "
                "geschätzt (Trend). Auf der Seite **Fehltage** eintragen.",
                sprints=", ".join(trend),
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
                    capacity_col: fmt(e.result.capacity.value),
                    t("Forecast IST"): fmt(e.result.forecast_ist.value, 2),
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
    _formula_expander(fc, history + [e for e in upcoming if e not in history])
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
        path.write_text(render(fc), encoding="utf-8")
        st.success(t("Geschrieben: {path}", path=path))


def _formula_help(fc: Forecast, e: TimelineEntry | None, key: str) -> str:
    """Tooltip-Text: symbolische Formel einer Kennzahl."""
    if e is None or (s := formula_step(fc, e, key)) is None:
        return ""
    return s.formula


def _formula_expander(fc: Forecast, entries: list[TimelineEntry]) -> None:
    """Ausklappbarer Rechenweg mit allen Kennzahlen eines Sprints."""
    if not entries:
        return
    with st.expander(t("Rechenweg: Formeln"), icon=":material/function:"):
        ids = [e.sprint.id for e in entries]
        default = fc.default_entry("planning")
        index = ids.index(default.sprint.id) if default and default.sprint.id in ids else 0
        chosen = st.selectbox("Sprint", ids, index=index, key="formula-sprint")
        entry = next(e for e in entries if e.sprint.id == chosen)
        st.dataframe(_steps_frame(fc, entry), hide_index=True, width="stretch")


def _next_dates(fc: Forecast) -> None:
    """Die nächsten Sprint-Termine mit dem, was dort zu tun ist."""
    current, planning = fc.current, fc.default_entry("planning")
    items = []
    if current is not None:
        days = workdays(current.sprint.start, current.sprint.end)
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
                t("Fehltage → Forecast PLAN → Forecast IST")
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
            t("Forecast IST / PLAN"): r.plan if future else r.forecast_ist.value,
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
    st.markdown(help_text("absences").replace("\n\n", "  \n"))
    if not data.people:
        st.warning(t("Noch keine Personen erfasst – zuerst auf der Seite **Personen** anlegen."))
        return
    count = st.number_input(
        t("Anzahl Sprints"), min_value=1, max_value=26, value=data.team.forecast.horizon + 1
    )
    sprints = absence_sprints(data, fc, int(count))
    if not sprints:
        st.info(t("Keine Sprints gefunden."))
        return
    for s in sprints:
        st.caption(sprint_caption(data, s))
    rows = absence_matrix(data.people, sprints)
    column_config: dict[str, Any] = {
        "id": None,
        "Person": st.column_config.TextColumn(t("Person"), disabled=True),
    }
    for s in sprints:
        column_config[s.id] = st.column_config.NumberColumn(
            s.id, min_value=0.0, max_value=float(len(workdays(s.start, s.end))), step=0.5
        )
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config=column_config,
        hide_index=True,
        key=f"absences-{data.team.key}-{sprints[0].id}-{len(sprints)}",
    )
    st.caption(t("Leere Zellen: Person ist in diesem Sprint nicht im Team."))
    edited_sprints = edit_absences(data.people, sprints, edited.to_dict("records"))
    to_save = sprints_to_save(data, sprints, edited_sprints)
    preview = with_sprints(data, to_save)
    fc_preview = build_forecast(preview, fc.today)
    if new := [s.id for s in to_save if data.sprint(s.id) is None]:
        st.caption(
            t(
                "Beim Speichern werden die Sprintdateien {sprints} angelegt. Ab dann gilt dort "
                "die Kapazität laut Personenliste statt des Trends.",
                sprints=", ".join(new),
            )
        )
    st.subheader(
        t("Kapazität und Prognose") + (t(" (Vorschau, noch nicht gespeichert)") if to_save else "")
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Sprint": s.id,
                    t("Kapazität (PT)"): fmt(sprint_capacity(data.team, data.people, s).capacity),
                    f"Forecast PLAN ({data.team.unit.value})": fmt(e.result.plan)
                    if (e := fc_preview.entry(s.id))
                    else "–",
                }
                for s in edited_sprints
            ]
        ),
        hide_index=True,
    )
    if st.button(t("Fehltage speichern"), type="primary", disabled=not to_save):
        save(
            preview,
            [f"{s.id}.yaml" for s in to_save],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )
    _reset_absences(repo, data, fc.today)


def _reset_absences(repo: Repository, data: TeamData, today: date) -> None:
    """Künftige Sprints ohne Informationen zu Fehltagen zurück auf „unbekannt“ (Trend)."""
    resettable = resettable_sprints(data, today)
    if not resettable:
        return
    st.subheader(t("Fehltage zurücksetzen"))
    st.caption(
        t(
            "Für diese Sprints wurden Fehltage bestätigt, sonst ist nichts erfasst. Zurücksetzen "
            "löscht die Sprintdatei: Es liegen dann keine Informationen vor, die Kapazität wird "
            "wieder aus dem Trend geschätzt."
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
            "ändern; die folgenden Sprints verschieben sich mit. Arbeitstage zählen Mo–Fr vom "
            "Start bis einschließlich zum letzten Tag, Feiertage werden erst bei der Kapazität "
            "abgezogen.",
            days=data.team.sprint.length_days,
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
                help=t("Mo–Fr vom Start bis einschließlich zum letzten Tag"),
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


# Der auf einem der Boards bewusst gewählte Sprint gilt auch auf den anderen Boards.
BOARD_SPRINT = "board-sprint"


def _sprint_choice(
    data: TeamData,
    fc: Forecast,
    purpose: str,
    label: str,
    key: str | None = None,
    shared: bool = False,
) -> Sprint | None:
    options = [e.sprint.id for e in fc.history(6)] + [e.sprint.id for e in fc.upcoming()]
    if not options:
        return None
    widget_key = key or f"{purpose}-sprint"
    wanted = st.session_state.get(BOARD_SPRINT) if shared else None
    kwargs: dict[str, Any] = {}
    if wanted in options:
        st.session_state[widget_key] = wanted
    else:
        default = fc.default_entry(purpose)
        kwargs["index"] = (
            options.index(default.sprint.id) if default and default.sprint.id in options else 0
        )

    def remember() -> None:
        st.session_state[BOARD_SPRINT] = st.session_state[widget_key]

    chosen = st.selectbox(
        label, options, key=widget_key, on_change=remember if shared else None, **kwargs
    )
    return copy.deepcopy(find_sprint(data, chosen))


BOARDS = ("vorplanung", "planning", "review")


def _board_nav(data: TeamData, sprint: Sprint, current: str) -> None:
    """Die drei Boards mit dem Stand für den gewählten Sprint – Wechsel mit einem Klick."""
    recorded = data.sprint(sprint.id)
    done = {
        "vorplanung": recorded is not None
        and any(v.preplanned is not None for v in recorded.products.values()),
        "planning": recorded is not None and recorded.forecast_ist is not None,
        "review": recorded is not None and recorded.velocity is not None,
    }
    for col, key in zip(st.columns(len(BOARDS)), BOARDS, strict=True):
        title, icon = PAGE_INFO[key]
        with col:
            st.page_link(
                page_path(key),
                label=f"{'✅' if done[key] else '⬜'} {t(title)}",
                icon=icon,
                disabled=key == current,
            )


def _number(label: str, value: float | None, key: str, help: str | None = None) -> float | None:
    return st.number_input(
        label, min_value=0.0, value=value, step=0.25, format="%.2f", key=key, help=help
    )


# --- Produkte: Tabelle und Diagramm ---------------------------------------------------

# Kategorische Farben in fester Reihenfolge (Produkt = Katalogposition); Standard neutral.
SERIES_COLORS = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
]  # fmt: skip
STANDARD_COLOR = "#9a9a94"
MAX_PRODUCT_COLORS = len(SERIES_COLORS)


def _others() -> str:
    return t("Weitere")


def _distribution_caption(d: Distribution, unit: str) -> str:
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
            frozen=t(" (beim Planning eingefroren)") if d.plan_frozen else "",
            available=fmt(d.available, 2),
            unit=unit,
        )
    return t(
        "Standard = {basis}{frozen} {available} {unit} / {count} betreute Produkte = "
        "**{share} {unit}** je Produkt.",
        basis=basis,
        frozen=t(" (beim Planning eingefroren)") if d.plan_frozen else "",
        available=fmt(d.available, 2),
        unit=unit,
        count=d.active_count,
        share=fmt(d.available / d.active_count, 2),
    )


def _production_hint(d: Distribution, data: TeamData, unit: str) -> None:
    """Kapazität der Personen mit Produktionszugriff und Warnung bei Überplanung."""
    if d.production_share is None or d.production_available is None:
        return
    people = sum(1 for p in data.people if p.production_access)
    planned = d.total("production_planned")
    st.caption(
        t(
            "Produktionszugriff: {count} Person(en) = {share} der Kapazität → bis zu "
            "**{available} {unit}** möglich, eingeplant {planned} {unit}.",
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
                "Für diesen Sprint sind keine Produkte hinterlegt – Produkte unter **Team → "
                "Produkte** anlegen (optional)."
            )
        )
        return None
    column_config: dict[str, Any] = {
        "_id": None,
        "Produkt": st.column_config.TextColumn(t("Produkt"), disabled=True),
        "PO": st.column_config.TextColumn(disabled=True),
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
    show_production = d.production_share is not None or any(d.has(m) for m in PRODUCTION_MEASURES)
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
    )
    st.caption(_distribution_caption(d, unit))
    return edited.to_dict("records")


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
    rows = balance(fc, entries)
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
            }
            for b in rows
        ]
    )
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
            tooltip=list(frame.columns[:-1]),
        ),
        width="stretch",
    )
    st.dataframe(frame.drop(columns=direction), hide_index=True)
    st.caption(
        t(
            "Saldo = Σ Erledigt − Σ Standard über die Sprints mit erfasstem Erledigt. Positiv: "
            "Das Produkt hat mehr bekommen als den gleichmäßigen Anteil."
        )
    )


def _base_sprint(data: TeamData, sprint: Sprint) -> Sprint:
    return copy.deepcopy(data.sprint(sprint.id) or sprint)


# --- Planning (geführter Ablauf zum Sprintstart) --------------------------------------

PLANNING_STEPS = ["1 · Fehltage", "2 · Forecast PLAN & Einplanung", "3 · Forecast IST"]
STEP_KEY = "planning-step"


def _goto(step: int) -> None:
    st.session_state["planning-goto"] = step


def page_planning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprint Planning")
    show_flash()
    sprint = _sprint_choice(data, fc, "planning", "Sprint", shared=True)
    if sprint is None:
        return
    _board_nav(data, sprint, "planning")
    # Neuer Sprint gewählt → beim ersten Schritt beginnen.
    if st.session_state.get("planning-last-sprint") != sprint.id:
        st.session_state["planning-last-sprint"] = sprint.id
        st.session_state["planning-goto"] = 0
    if (goto := st.session_state.pop("planning-goto", None)) is not None:
        st.session_state[STEP_KEY] = goto
    st.caption(
        t(
            "Planning am **{day}** · Ablauf: zuerst die bekannten Fehltage, dann mit dem Forecast "
            "PLAN die Tickets einplanen, vor dem Sprintstart den Forecast IST eintragen.",
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
        recorded is not None,
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
                "**Team → Personen** anlegen."
            )
        )
        st.button(t("Weiter"), on_click=_goto, args=(1,), type="primary")
        return
    base = _base_sprint(data, sprint)
    days = len(workdays(base.start, base.end))
    edited = st.data_editor(
        pd.DataFrame(absence_matrix(data.people, [base])),
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
    )
    [after] = edit_absences(data.people, [base], edited.to_dict("records"))
    to_save = sprints_to_save(data, [base], [after])
    preview = with_sprints(data, [after])
    breakdown = sprint_capacity(data.team, data.people, after)
    fc_after = build_forecast(preview, fc.today)
    entry = fc_after.entry(after.id)
    left, right = st.columns(2)
    left.metric(
        t("Kapazität (PT)"),
        fmt(breakdown.capacity),
        help=_formula_help(fc_after, entry, "capacity"),
    )
    right.metric(
        f"Forecast PLAN ({data.team.unit.value})",
        fmt(entry.result.plan) if entry else "–",
        help=_formula_help(fc_after, entry, "plan"),
    )
    if after.capacity is not None:
        st.info(
            t(
                "In der Sprintdatei ist eine feste Kapazität ({capacity} PT) eingetragen – sie "
                "gilt statt der Berechnung aus den Fehltagen.",
                capacity=fmt(after.capacity),
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
    cols = st.columns(4)
    cols[0].metric(
        t("Kapazität (PT)"),
        fmt(r.plan_capacity),
        help=t("Quelle: {source}", source=source_label(r.plan_capacity_source) or "–")
        + "\n\n"
        + _formula_help(fc, entry, "capacity"),
    )
    cols[1].metric(f"Forecast PLAN ({unit})", fmt(r.plan), help=_formula_help(fc, entry, "plan"))
    cols[2].metric(
        f"Roadmap ({pct(data.team.forecast.roadmap_share)})",
        fmt(r.roadmap, 2),
        help=_formula_help(fc, entry, "roadmap"),
    )
    cols[3].metric(
        t("Kleinkram"), fmt(r.small_stuff, 2), help=_formula_help(fc, entry, "small_stuff")
    )
    with st.expander(t("Rechenweg"), icon=":material/function:"):
        st.dataframe(_steps_frame(fc, entry), hide_index=True, width="stretch")
    if r.plan_capacity_source is CapacitySource.TREND:
        st.warning(t("Noch keine Fehltage erfasst – die Kapazität ist nur geschätzt."))
        st.button(t("Zurück zu den Fehltagen"), on_click=_goto, args=(0,))
    if data.products:
        st.subheader(t("Einplanung je Produkt"))
        d = distribution(fc, entry)
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
            fc_preview = build_forecast(preview, fc.today)
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
    else:
        st.caption(
            t(
                "Optional: Mit Produkten unter **Team → Produkte** lässt sich hier die "
                "Verteilung auf die Produkte planen und auswerten."
            )
        )
    st.button(t("Weiter"), on_click=_goto, args=(2,), type="primary")


def _planning_ist(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    sprint = _base_sprint(data, sprint)
    entry = fc.entry(sprint.id)
    st.subheader(t("Forecast IST – vor dem Sprintstart"))
    if entry:
        st.caption(
            t(
                "Forecast PLAN {plan} {unit} · Kapazität {capacity} PT",
                plan=fmt(entry.result.plan),
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
            t("Forecast IST ({unit})", unit=unit),
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
                    "aus. Ist der Forecast IST leer, wird er mit Überkipper + Backlog vorbelegt; "
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
        st.error(t("Korrekturen: bitte Zahlen mit Leerzeichen getrennt eingeben."))
        return
    prefilled = apply_planning(
        sprint,
        forecast_ist,
        Planning(carryover=carryover or 0.0, backlog=backlog or 0.0, corrections=corrections),
    )
    freeze_plan(sprint, entry, fc.today, refreeze=refreeze)
    if prefilled:
        st.info(
            t(
                "Forecast IST aus Überkipper + Backlog übernommen: {value} {unit}",
                value=fmt(sprint.forecast_ist, 2),
                unit=unit,
            )
        )
    after = with_sprints(data, [sprint])
    if save(
        after,
        [f"{sprint.id}.yaml"],
        lambda: [repo.save_sprint(data.team.key, sprint)],
    ):
        e = build_forecast(after, fc.today).entry(sprint.id)
        if e and e.result.planning_total is not None:
            st.info(
                t(
                    "Planning-Summe {total} {unit} · Forecast PLAN {plan} {unit} · Delta "
                    "{delta} {unit}",
                    total=fmt(e.result.planning_total, 2),
                    plan=fmt(e.result.plan),
                    delta=fmt(e.result.planning_delta, 2),
                    unit=unit,
                )
            )
        if sprint.forecast_ist is not None:
            st.success(t("Planning {id} vollständig – der Sprint kann starten.", id=sprint.id))


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
    sprint = _sprint_choice(data, fc, "review", "Sprint", shared=True)
    if sprint is None:
        return
    _board_nav(data, sprint, "review")
    unit = data.team.unit.value
    computed = sprint_capacity(data.team, data.people, sprint).capacity if data.people else None
    st.caption(
        t(
            "Im Review wird festgehalten, was der Sprint geschafft hat: erledigte Menge, was "
            "nicht fertig wurde und was zusätzlich erledigt wurde."
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
                "Menge des Forecast IST, die im Sprint nicht fertig wurde. Optional – "
                "Velocity = Forecast IST − nicht erledigt + zusätzlich erledigt."
            ),
        )
        additional = extra_col.number_input(
            t("Zusätzlich erledigt ({unit})", unit=unit),
            key=f"additional-done-{sprint.id}",
            min_value=0.0,
            value=sprint.additional_done,
            step=0.25,
            format="%.2f",
            help=t("Menge, die zusätzlich zum Forecast IST geschafft wurde. Optional."),
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
        if data.products and entry is not None:
            st.markdown(f"**{t('Erledigt je Produkt')}**")
            product_rows = _product_editor(
                distribution(fc, entry), ["done"], f"review-products-{sprint.id}", unit
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
                + t("Laut Personenliste und Fehltagen: {capacity} PT", capacity=fmt(computed))
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
    if product_rows is not None:
        sprint = apply_product_values(sprint, product_rows, ["done"])
    save(
        with_sprints(data, [sprint]),
        [f"{sprint.id}.yaml"],
        lambda: [repo.save_sprint(data.team.key, sprint)],
        tag=f"{data.team.key}/{sprint.id}" if tag else None,
    )


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
            later = t("nach dem Zeitraum")
            left, middle, right = st.columns(3)
            left.metric(
                t("je Sprint für das Projekt ({share} des Forecasts)", share=pct(used_share)),
                f"≈ {fmt(result.per_sprint, 1)} {unit}",
                help=t("Median der normierten Velocity × typische Kapazität × Anteil."),
            )
            middle.metric(t("wahrscheinlich (50 %)"), result.p50 or later)
            right.metric(t("mit 85 % Sicherheit"), result.p85 or later)
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
                "Monte-Carlo-Simulation ({runs} Durchläufe) ab dem nächsten Sprint: je Sprint "
                "eine zufällige normierte Velocity der letzten Sprints × Kapazität.",
                runs=f"{result.runs:,}",
            )
            if result.trend_capacity_sprints:
                listed = ", ".join(result.trend_capacity_sprints[:4])
                if len(result.trend_capacity_sprints) > 4:
                    listed += " …"
                caption += t(
                    " Ohne erfasste Fehltage mit Ø Kapazität gerechnet: {sprints}.", sprints=listed
                )
            st.caption(caption)

    st.subheader(t("Fokusfaktor"))
    st.metric(
        t("Ø Fokusfaktor (letzte {window} Sprints)", window=window),
        fmt(average_focus_factor(fc), 2),
        help=t(
            "Velocity / Kapazität. Anders als die normierte Velocity unabhängig von der "
            "Referenzkapazität – damit zwischen Teams vergleichbar. Literaturwerte (0,6–0,8) "
            "beziehen sich meist auf reine Arbeitszeit; zählt die Kapazität alle "
            "Anwesenheitstage, liegen die Werte niedriger."
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
            "Ø Scope Creep der letzten {count} Sprints: **{scope}** · eingestellter "
            "Kleinkram-Anteil: **{small}**",
            count=hint.samples,
            scope=pct(hint.average_scope_creep),
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
    rows = []
    for sprint in sprints:
        recorded = data.sprint(sprint.id)
        for p in recorded.prognoses if recorded else []:
            rows.append(
                {
                    t("Zeitpunkt"): f"{p.at:%d.%m.%Y %H:%M}",
                    "Sprint": sprint.id,
                    t("Kommentar"): p.comment or "",
                    f"Forecast IST ({unit})": fmt(p.forecast_ist, 2),
                    t("nicht erledigt"): fmt(p.not_done, 2),
                    t("zusätzlich erledigt"): fmt(p.additional_done, 2),
                    t("erwartet erledigt"): fmt(p.expected_done, 2),
                    t("Forecast PLAN {id}", id=p.target or "–"): fmt(p.plan),
                }
            )
    if rows:
        st.markdown(f"**{t('Bisherige Prognosen')}**")
        st.dataframe(pd.DataFrame(rows[::-1]), hide_index=True)


def page_preplanning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    """Board der POs vor dem Planning: je Produkt vorsehen, was in den Sprint soll."""
    st.header(t("PO-Vorplanung"))
    show_flash()
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
    sprint = _sprint_choice(data, fc, "planning", "Sprint", key="vorplanung-sprint", shared=True)
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
    assumed: dict[str, Assumption] = {}
    comment = ""
    if open_velocity_sprints(fc):
        with st.expander(
            t("Was-wäre-wenn: Prognose des Teams für den letzten Sprint"),
            icon=":material/science:",
        ):
            st.caption(
                t(
                    "Prognose des Teams für den letzten Sprint eintragen: Forecast IST, was "
                    "voraussichtlich nicht fertig wird und was zusätzlich geschafft wird. Der "
                    "Forecast PLAN und damit die verteilbare Menge werden neu berechnet. Das gilt "
                    "nur für diese Ansicht; mit **Vorplanung speichern** wird die Annahme samt "
                    "Kommentar als Prognose festgehalten. Die Velocity selbst wird erst im Review "
                    "erfasst.",
                    unit=unit,
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
    fc_view = whatif_forecast(fc, assumed) if assumed else fc
    if assumed:
        shown = fc_view.entry(sprint.id)
        before = entry.result.plan
        st.info(
            t(
                "Rechnung mit angenommener Velocity – Forecast PLAN {id}: **{new} {unit}** "
                "(ohne Annahme {old} {unit}).",
                id=sprint.id,
                new=fmt(shown.result.plan) if shown else "–",
                old=fmt(before),
                unit=unit,
            )
        )
        if sprint.forecast_plan is not None:
            st.caption(
                t(
                    "Der Forecast PLAN dieses Sprints ist beim Planning eingefroren – die Annahme "
                    "ändert ihn nicht."
                )
            )
    d = distribution(fc_view, fc_view.entry(sprint.id) or entry)
    rows = _product_editor(d, ["preplanned"], f"vorplanung-{sprint.id}", unit)
    if rows is None:
        return
    base = _base_sprint(data, sprint)
    after = apply_product_values(base, rows, ["preplanned"])
    preview = with_sprints(data, [after])  # nur die Vorplanung – die Annahme wird nie gespeichert
    fc_preview = build_forecast(preview, fc.today)
    if assumed:
        fc_preview = whatif_forecast(fc_preview, assumed)
    d = distribution(fc_preview, fc_preview.entry(after.id) or entry)
    total = d.total("preplanned")
    left, middle, right = st.columns(3)
    left.metric(t("Verteilbar"), f"{fmt(d.available, 2)} {unit}")
    middle.metric(t("Vorgesehen (Σ)"), f"{fmt(total, 2)} {unit}")
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
            "PO": r.product.po or "",
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
    if po_rows := by_po(d):
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
    changed = after.products != base.products or bool(assumed)
    if st.button(t("PO-Vorplanung speichern"), type="primary", disabled=not changed):
        to_save = [after]
        if assumed:
            plan = fc_preview.entry(after.id).result.plan if fc_preview.entry(after.id) else None
            to_save = record_prognoses(data, after, assumed, plan, comment)
        save(
            with_sprints(data, to_save),
            [f"{s.id}.yaml" for s in to_save],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )
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
    sprint = _sprint_choice(data, fc, "planning", "Sprint", key="products-sprint")
    if sprint is None:
        return
    entry = fc.entry(sprint.id)
    if entry is None:
        return
    st.caption(
        t(
            "Die **PO-Vorplanung** tragen die POs vor dem Planning ein, **Planning** wird im "
            "Sprint Planning gefüllt, **Erledigt** im Review – jeweils auf den Seiten der "
            "**Boards**. Alles lässt sich auch hier pflegen."
        )
    )
    d = distribution(fc, entry)
    editable = list(MEASURES.keys() - {"standard"}) + list(PRODUCTION_MEASURES)
    rows = _product_editor(d, editable, f"products-{sprint.id}", unit)
    if rows is not None:
        base = _base_sprint(data, sprint)
        after = apply_product_values(base, rows, editable)
        preview = with_sprints(data, [after])
        fc_preview = build_forecast(preview, fc.today)
        d = distribution(fc_preview, fc_preview.entry(after.id) or entry)
        _production_hint(d, data, unit)
        changed = after.products != base.products
        if st.button(t("Produktwerte speichern"), type="primary", disabled=not changed):
            save(preview, [f"{after.id}.yaml"], lambda: [repo.save_sprint(data.team.key, after)])
        if chart := _product_chart(d, unit):
            st.altair_chart(chart, width="stretch")
        if po_rows := by_po(d):
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
            "PO": st.column_config.TextColumn("PO", help=t("Verantwortlicher Product Owner")),
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
            "Bundesland": st.column_config.SelectboxColumn(
                t("Bundesland"),
                options=[TEAM_REGION, *REGIONS],
                default=TEAM_REGION,
                help=t("(Team) = Einstellung des Teams"),
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
            ),
        },
        num_rows="dynamic",
        hide_index=True,
        key=f"people-{data.team.key}-{show_former}",
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
    """Arbeitstage je Sprint (Mo–Fr aus der Sprintlänge) – Umrechnung zwischen PT und %."""
    length = st.session_state.get(f"{form_key}-sprint.length_days", team.sprint.length_days)
    return max(float(length) * 5 / 7, 1.0)


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
    key = (
        st.text_input(t("Team-Kürzel (Verzeichnisname)"), help=t("Kleinbuchstaben, z. B. team-a"))
        .strip()
        .lower()
    )
    if not key:
        return
    if repo.exists(key):
        st.error(t("Team {team} existiert bereits.", team=repr(key)))
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
    """Kein Datenordner gefunden: weder Teams noch ein Git-Repository."""
    return teams_dir(root) is None and git_root(root) is None


def _use_data_dir(path: Path) -> None:
    save_data_dir(path)
    os.environ[DATA_ENV] = str(path.resolve())
    st.session_state.pop("selected_team", None)
    st.session_state["flash"] = [("success", t("Datenordner: `{path}`", path=path.resolve()))]


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


def page_data_dir(repo: Repository, setup: bool = False) -> None:
    st.header(t("Datenordner"))
    show_flash()
    if setup:
        st.warning(
            t(
                "Kein Datenordner gefunden. Die Team-Daten liegen in einem **Git-Repository** – "
                "so sind Änderungen nachvollziehbar und mit dem Team teilbar. Bitte einen "
                "vorhandenen Ordner wählen, ein neues Daten-Repository anlegen oder ein "
                "bestehendes klonen."
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
                st.error(
                    t(
                        "Der Ordner liegt in keinem Git-Repository. Entweder hier eines anlegen "
                        "oder einen anderen Ordner wählen."
                    )
                )
                st.session_state["offer-init"] = str(path)
            else:
                _use_data_dir(teams_dir(path) or path)
                st.rerun()
        offer = st.session_state.get("offer-init")
        if offer and st.button(
            t("Git-Repository in {path} anlegen", path=offer), key="data-init-here"
        ):
            try:
                target = init_data_repository(Path(offer), teams_folder=False)
            except GitError as e:
                st.error(str(e))
            else:
                st.session_state.pop("offer-init", None)
                _use_data_dir(teams_dir(target) or target)
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
                    _use_data_dir(target)
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
                    st.error(t("Klonen fehlgeschlagen: {error}", error=e))
                else:
                    _use_data_dir(teams_dir(path) or path)
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
            "sich mischen. Gespeichert wird lokal; mit **Änderungen committen** in der "
            "Seitenleiste landen die Änderungen im Git-Repository der Daten."
        )
    )
    ablauf, begriffe, felder, team, befehle = st.tabs(
        [
            t("Ablauf"),
            t("Begriffe"),
            t("Eingabefelder"),
            t("Team-Einstellungen"),
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
    check = st.session_state.get("manual-check") or _update_check().result(wait=4.0)
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
        st.session_state["commit_error"] = str(e)
        return
    st.session_state["pending_tags"] = []
    st.session_state["last_commit"] = rev
    st.session_state["commit_message"] = _commit_default()


def _git_panel(repo: Repository) -> None:
    if git_root(repo.root) is None:
        st.caption(t("Datenverzeichnis liegt in keinem Git-Repository – Commit nicht möglich."))
        return
    if last := st.session_state.pop("last_commit", None):
        st.success(t("Committet ({rev}). Pushen nicht vergessen.", rev=last))
    if error := st.session_state.pop("commit_error", None):
        st.error(error)
    try:
        changes = pending_changes(repo.root)
    except GitError as e:
        st.caption(f"Git: {e}")
        return
    tags = st.session_state.get("pending_tags", [])
    with st.expander(
        t("Git: {count} offene Änderung(en)", count=len(changes))
        if changes
        else t("Git: alles committet"),
        expanded=bool(changes),
        icon=":material/commit:",
    ):
        if not changes:
            st.caption(t("Keine offenen Änderungen im Datenverzeichnis."))
            return
        st.code("\n".join(f"{status:>2} {file}" for status, file in changes), language=None)
        st.session_state.setdefault("commit_message", _commit_default())
        st.text_input(t("Commit-Nachricht"), key="commit_message")
        if tags:
            st.checkbox(t("Tags setzen: {tags}", tags=", ".join(tags)), value=True, key="use_tags")
        st.button(
            t("Änderungen committen"),
            type="primary",
            icon=":material/save:",
            on_click=_commit_clicked,
            args=(repo.root, list(tags)),
        )


TEAM_PAGES = {
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
GLOBAL_PAGES = {
    "datenordner": page_data_dir,
    "neues_team": page_new_team,
    "pruefung": page_check,
    "hilfe": page_help,
}


def run_page(key: str) -> None:
    """Wird von den Seitendateien unter web/seiten aufgerufen."""
    repo = repository()
    if needs_setup(repo.root):
        page_data_dir(repo, setup=True)
        return
    team = st.session_state.get("selected_team")
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
        data = repo.load(team)
    except DataError as e:
        st.error(str(e))
        return
    TEAM_PAGES[key](repo, data, build_forecast(data, today()))


def run_plugin_page(page: WebPage) -> None:
    """Seite eines Plugins (siehe sprintforecast.plugins)."""
    page.render(repository())
