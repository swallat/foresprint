# SPDX-License-Identifier: EUPL-1.2
"""Seiten und Seitenleiste der Weboberfläche. Einstieg: web/app.py, Seiten: web/seiten/*.py.

Liest und schreibt dieselben YAML-Dateien wie die Kommandozeile. Konfiguration über
Umgebungsvariablen: SPRINTFORECAST_DATEN (Datenverzeichnis), SPRINTFORECAST_STICHTAG.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

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
)
from sprintforecast.git import GitError, commit_directory, pending_changes
from sprintforecast.git import repo_root as git_root
from sprintforecast.guide import CAPACITY_SOURCES, COMMANDS, FIELDS, TERMS, WORKFLOW
from sprintforecast.model import Numbering, Planning, Sprint, Team
from sprintforecast.plugins import WebPage
from sprintforecast.products import MEASURES, Distribution, balance, by_po, distribution
from sprintforecast.report import capacity_label, fmt, pct, period, render, status
from sprintforecast.settings import REGIONS, SETTINGS, Kind, Setting, applicable, changes
from sprintforecast.storage import (
    STICHTAG_ENV,
    DataError,
    Repository,
    TeamData,
    default_data_dir,
)
from sprintforecast.updater import status_line
from sprintforecast.validate import Level, check_all, check_team
from sprintforecast.web.logic import (
    CALENDAR_COLUMNS,
    PEOPLE_COLUMNS,
    PRODUCT_COLUMNS,
    TEAM_REGION,
    absence_matrix,
    absence_sprints,
    apply_calendar,
    apply_product_values,
    calendar_table,
    edit_absences,
    parse_numbers,
    people_from_table,
    people_table,
    product_table,
    product_values_table,
    products_from_table,
    sprints_to_save,
    with_people,
    with_sprints,
)

# Seiten: Dateiname unter web/seiten → (Titel, Material-Icon). Gruppen für die Navigation.
PAGES: dict[str, dict[str, tuple[str, str]]] = {
    "Sprint": {
        "forecast": ("Forecast", ":material/trending_up:"),
        "fehltage": ("Fehltage", ":material/event_busy:"),
        "sprints": ("Sprintkalender", ":material/calendar_month:"),
        "planning": ("Planning", ":material/edit_note:"),
        "review": ("Review", ":material/task_alt:"),
        "produkte": ("Produktverteilung", ":material/pie_chart:"),
        "analyse": ("Analyse", ":material/insights:"),
    },
    "Team": {
        "personen": ("Personen", ":material/group:"),
        "produktliste": ("Produkte", ":material/category:"),
        "einstellungen": ("Einstellungen", ":material/tune:"),
        "neues_team": ("Neues Team", ":material/group_add:"),
    },
    "Daten & Hilfe": {
        "pruefung": ("Prüfung", ":material/fact_check:"),
        "hilfe": ("Hilfe", ":material/help:"),
    },
}
PAGE_INFO = {key: info for group in PAGES.values() for key, info in group.items()}


def page_path(key: str) -> str:
    return f"seiten/{key}.py"


def page_link(key: str, label: str | None = None) -> None:
    title, icon = PAGE_INFO[key]
    st.page_link(page_path(key), label=label or title, icon=icon)


def today() -> date:
    raw = os.environ.get(STICHTAG_ENV)
    return date.fromisoformat(raw) if raw else date.today()


def repository() -> Repository:
    return Repository(default_data_dir())


def help_text(key: str) -> str:
    f = FIELDS[key]
    return f"{f.what}\n\nQuelle: {f.source}\n\nBeispiel: {f.example}"


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
        st.error("Nicht gespeichert – bitte die Fehler beheben.")
        return False
    paths = write()
    for i in relevant:
        if i.level is Level.WARNING:
            notify("warning", f"{i.where}: {i.message}")
    if tag:
        tags = st.session_state.setdefault("pending_tags", [])
        if tag not in tags:
            tags.append(tag)
    names = ", ".join(p.name for p in paths)
    notify(
        "success",
        f"Gespeichert: {names}. In Git übernehmen mit **Änderungen committen** in der "
        "Seitenleiste.",
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
    return (
        f"**{s.id}**: {s.start:%d.%m.} – {last} (letzter Arbeitstag; der nächste Sprint beginnt "
        f"am {s.end:%d.%m.}), {len(days)} Arbeitstage Mo–Fr"
        + (f" · davon Feiertage: {', '.join(hol)}" if hol else "")
        + ("" if data.sprint(s.id) else " · noch keine Sprintdatei")
    )


# --- Seiten ---------------------------------------------------------------------------


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
            help=f"Kapazität {capacity_label(e)} PT · Roadmap {fmt(e.result.roadmap, 2)} · "
            f"Kleinkram {fmt(e.result.small_stuff, 2)}",
        )

    rows = [
        {
            "Sprint": e.sprint.id,
            "Zeitraum": period(e),
            "Status": status(fc, e).replace("*", ""),
            "Kapazität (PT)": capacity_label(e),
            "n. Velocity-Trend": fmt(e.result.normalized_velocity.trend, 2),
            f"Forecast PLAN ({unit})": fmt(e.result.plan),
            "Roadmap": fmt(e.result.roadmap, 2),
            "Kleinkram": fmt(e.result.small_stuff, 2),
        }
        for e in upcoming
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    trend = [e.sprint.id for e in upcoming if e.result.plan_capacity_source is CapacitySource.TREND]
    if trend:
        st.warning(
            f"Für {', '.join(trend)} sind noch keine Fehltage erfasst – die Kapazität ist nur "
            "geschätzt (Trend). Auf der Seite **Fehltage** eintragen."
        )
    current = fc.current
    if current and current.result.planning_total is not None:
        st.info(
            f"Planning {current.sprint.id}: Summe {fmt(current.result.planning_total, 2)} {unit}, "
            f"Delta zum Forecast PLAN {fmt(current.result.planning_delta, 2)} {unit}"
        )

    st.subheader("Verlauf")
    history = fc.history(10)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Sprint": e.sprint.id,
                    "Kapazität (PT)": fmt(e.result.capacity.value),
                    "Forecast IST": fmt(e.result.forecast_ist.value, 2),
                    "Velocity": fmt(e.result.velocity.value, 2),
                    "n. Velocity": fmt(e.result.normalized_velocity.value, 2),
                    "Ø n. Velocity": fmt(e.result.normalized_velocity.average, 2),
                    "Fulfillment": pct(e.result.fulfillment.value),
                    "Scope Creep": pct(e.result.scope_creep.value),
                }
                for e in history
            ]
        ),
        hide_index=True,
    )
    chart = _chart(fc, history + [e for e in upcoming if e not in history], unit)
    if chart is None:
        st.info(
            "Noch keine Werte für ein Diagramm – nach den ersten Sprints Planning und Review "
            "erfassen (oder die Historie über ein Import-Plugin übernehmen)."
        )
    else:
        st.altair_chart(chart, width="stretch")

    if st.button("Bericht FORECAST.md schreiben"):
        path = repo.team_dir(team.key) / "FORECAST.md"
        path.write_text(render(fc), encoding="utf-8")
        st.success(f"Geschrieben: {path}")


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
                "erfasst ✓" if done else "Velocity und Erledigt je Produkt erfassen",
                "review",
            )
        )
    if planning is not None:
        missing = fc.data.sprint(planning.sprint.id) is None
        items.append(
            (
                f"Planning {planning.sprint.id}",
                day_label(planning.sprint.start),
                "Fehltage → Forecast PLAN → Forecast IST"
                + (" (Fehltage noch nicht erfasst)" if missing else ""),
                "planning",
            )
        )
    if not items:
        return
    with st.container(border=True):
        st.caption("Nächste Termine")
        for title, when, todo, page in items:
            left, middle, right = st.columns([2, 4, 2], vertical_alignment="center")
            left.markdown(f"**{title}**  \n{when}")
            middle.markdown(todo)
            with right:
                page_link(page, "Öffnen")


def _chart(fc: Forecast, entries: list[TimelineEntry], unit: str) -> alt.Chart | None:
    """Liniendiagramm; None, solange es keine Werte gibt (leere Daten lässt Altair scheitern)."""
    records = []
    for e in entries:
        r = e.result
        future = e.sprint.end > fc.today
        values = {
            "Forecast IST / PLAN": r.plan if future else r.forecast_ist.value,
            "Velocity": r.velocity.trend if future else r.velocity.value,
            "n. Velocity": r.normalized_velocity.trend if future else r.normalized_velocity.value,
        }
        for name, value in values.items():
            if value is not None:
                records.append(
                    {"Sprint": e.sprint.id, "Kennzahl": name, unit: value, "Prognose": future}
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
            color="Kennzahl:N",
            strokeDash=alt.StrokeDash("Prognose:N", legend=None),
            tooltip=[
                alt.Tooltip("Sprint:N"),
                alt.Tooltip("Kennzahl:N"),
                alt.Tooltip(f"{unit}:Q", format=".2f"),
            ],
        )
    )


def page_absences(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Planbare Fehltage")
    st.markdown(help_text("absences").replace("\n\n", "  \n"))
    if not data.people:
        st.warning("Noch keine Personen erfasst – zuerst auf der Seite **Personen** anlegen.")
        return
    count = st.number_input(
        "Anzahl Sprints", min_value=1, max_value=26, value=data.team.forecast.horizon + 1
    )
    sprints = absence_sprints(data, fc, int(count))
    if not sprints:
        st.info("Keine Sprints gefunden.")
        return
    for s in sprints:
        st.caption(sprint_caption(data, s))
    rows = absence_matrix(data.people, sprints)
    column_config: dict[str, Any] = {
        "id": None,
        "Person": st.column_config.TextColumn(disabled=True),
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
    st.caption("Leere Zellen: Person ist in diesem Sprint nicht im Team.")
    edited_sprints = edit_absences(data.people, sprints, edited.to_dict("records"))
    to_save = sprints_to_save(data, sprints, edited_sprints)
    preview = with_sprints(data, to_save)
    fc_preview = build_forecast(preview, fc.today)
    if new := [s.id for s in to_save if data.sprint(s.id) is None]:
        st.caption(
            f"Beim Speichern werden die Sprintdateien {', '.join(new)} angelegt. Ab dann gilt "
            "dort die Kapazität laut Personenliste statt des Trends."
        )
    st.subheader(
        "Kapazität und Prognose" + (" (Vorschau, noch nicht gespeichert)" if to_save else "")
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Sprint": s.id,
                    "Kapazität (PT)": fmt(sprint_capacity(data.team, data.people, s).capacity),
                    f"Forecast PLAN ({data.team.unit.value})": fmt(e.result.plan)
                    if (e := fc_preview.entry(s.id))
                    else "–",
                }
                for s in edited_sprints
            ]
        ),
        hide_index=True,
    )
    if st.button("Fehltage speichern", type="primary", disabled=not to_save):
        save(
            preview,
            [f"{s.id}.yaml" for s in to_save],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )


def page_calendar(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprintkalender")
    st.markdown(
        "Künftige Sprints entstehen automatisch aus dem Kalender: Jeder Sprint beginnt am Tag "
        f"nach dem letzten Tag des vorherigen und dauert {data.team.sprint.length_days} "
        "Kalendertage (Einstellung *Sprintlänge*). Eine Sprintdatei wird angelegt, sobald "
        "etwas für den Sprint gespeichert wird – oder hier mit **Sprints anlegen**.  \n"
        "Weicht ein Sprint ab (z. B. drei Wochen über Weihnachten), den **letzten Tag** ändern; "
        "die folgenden Sprints verschieben sich mit. Arbeitstage zählen Mo–Fr vom Start bis "
        "einschließlich zum letzten Tag, Feiertage werden erst bei der Kapazität abgezogen."
    )
    count = st.number_input("Anzahl Sprints", min_value=1, max_value=26, value=6, key="cal-n")
    sprints = absence_sprints(data, fc, int(count))
    if not sprints:
        st.info("Keine Sprints gefunden.")
        return
    frame = pd.DataFrame(calendar_table(data, sprints, fc.today), columns=CALENDAR_COLUMNS)
    for col in ("Start", "Letzter Tag"):
        frame[col] = pd.to_datetime(frame[col])
    edited = st.data_editor(
        frame,
        column_config={
            "Sprint": st.column_config.TextColumn(disabled=True),
            "Start": st.column_config.DateColumn(format="DD.MM.YYYY", disabled=True),
            "Letzter Tag": st.column_config.DateColumn(
                format="DD.MM.YYYY", help="Der nächste Sprint beginnt am Tag danach."
            ),
            "Arbeitstage": st.column_config.NumberColumn(
                disabled=True, help="Mo–Fr vom Start bis einschließlich zum letzten Tag"
            ),
            "Status": st.column_config.TextColumn(disabled=True),
        },
        hide_index=True,
        key=f"calendar-{data.team.key}-{len(sprints)}",
    )
    after, errors = apply_calendar(data, sprints, edited.to_dict("records"))
    for e in errors:
        st.error(e)
    to_save = [
        new
        for old, new in zip(sprints, after, strict=True)
        if data.sprint(new.id) is None or (old.start, old.end) != (new.start, new.end)
    ]
    if to_save:
        st.caption(
            "Beim Speichern: "
            + ", ".join(
                f"{s.id} ({'neu' if data.sprint(s.id) is None else 'geändert'})" for s in to_save
            )
        )
    if st.button(
        "Sprints anlegen bzw. speichern", type="primary", disabled=bool(errors) or not to_save
    ):
        save(
            with_sprints(data, to_save),
            [f"{s.id}.yaml" for s in to_save],
            lambda: [repo.save_sprint(data.team.key, s) for s in to_save],
        )


def _sprint_choice(
    data: TeamData, fc: Forecast, purpose: str, label: str, key: str | None = None
) -> Sprint | None:
    options = [e.sprint.id for e in fc.history(6)] + [e.sprint.id for e in fc.upcoming()]
    default = fc.default_entry(purpose)
    index = options.index(default.sprint.id) if default and default.sprint.id in options else 0
    if not options:
        return None
    chosen = st.selectbox(label, options, index=index, key=key or f"{purpose}-sprint")
    return copy.deepcopy(find_sprint(data, chosen))


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
OTHERS = "Weitere"


def _distribution_caption(d: Distribution, unit: str) -> str:
    basis = "Roadmap-Anteil des Forecast PLAN" if d.basis.value == "roadmap" else "Forecast PLAN"
    if d.available is None or not d.active_count:
        return f"Standard: {basis} / Anzahl betreuter Produkte – noch nicht berechenbar."
    frozen = " (beim Planning eingefroren)" if d.plan_frozen else ""
    return (
        f"Standard = {basis}{frozen} {fmt(d.available, 2)} {unit} / {d.active_count} betreute "
        f"Produkte = **{fmt(d.available / d.active_count, 2)} {unit}** je Produkt."
    )


def _product_editor(
    d: Distribution, editable: list[str], key: str, unit: str
) -> list[dict[str, Any]] | None:
    """Tabelle Produkt × Standard/Vorplanung/Planning/Erledigt; ``editable`` sind bearbeitbar."""
    if not d.rows:
        st.info(
            "Für diesen Sprint sind keine Produkte hinterlegt – Produkte unter **Team → "
            "Produkte** anlegen (optional)."
        )
        return None
    column_config: dict[str, Any] = {
        "_id": None,
        "Produkt": st.column_config.TextColumn(disabled=True),
        "PO": st.column_config.TextColumn(disabled=True),
    }
    for m, label in MEASURES.items():
        column_config[label] = st.column_config.NumberColumn(
            f"{label} ({unit})",
            min_value=0.0,
            step=0.25,
            format="%.2f",
            disabled=m not in editable,
            help=FIELDS[m].what if m in FIELDS else "Verfügbare Menge / Anzahl betreuter Produkte",
        )
    frame = pd.DataFrame(product_values_table(d))
    for label in MEASURES.values():
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
    records = [
        {"Produkt": r.product.name, "Kennzahl": label, unit: value}
        for r in d.rows
        for m, label in MEASURES.items()
        if (value := r.value(m)) is not None
    ]
    if not records:
        return None
    labels = list(MEASURES.values())
    return (
        alt.Chart(pd.DataFrame(records))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "Produkt:N",
                sort=[r.product.name for r in d.rows],
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            xOffset=alt.XOffset("Kennzahl:N", sort=labels),
            y=alt.Y(f"{unit}:Q"),
            color=alt.Color(
                "Kennzahl:N",
                sort=labels,
                scale=alt.Scale(domain=labels, range=[STANDARD_COLOR, *SERIES_COLORS[:3]]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=["Produkt:N", "Kennzahl:N", alt.Tooltip(f"{unit}:Q", format=".2f")],
        )
    )


def _product_colors(names: list[str]) -> alt.Scale:
    """Farbe folgt dem Produkt (Position in der Produktliste), nicht seinem Rang."""
    domain = [n for n in names if n != OTHERS]
    rng = [SERIES_COLORS[i % MAX_PRODUCT_COLORS] for i in range(len(domain))]
    if OTHERS in names:
        domain.append(OTHERS)
        rng.append(STANDARD_COLOR)
    return alt.Scale(domain=domain, range=rng)


def _product_name(fc: Forecast, product_id: str, name: str) -> str:
    """Bei mehr als acht Produkten werden die hinteren als „Weitere“ zusammengefasst."""
    products = fc.data.products
    if len(products) <= MAX_PRODUCT_COLORS:
        return name
    index = next((i for i, p in enumerate(products) if p.id == product_id), None)
    return name if index is not None and index < MAX_PRODUCT_COLORS - 1 else OTHERS


def _product_rank(fc: Forecast, product_id: str) -> int:
    """Position in der Produktliste – bestimmt die Stapelreihenfolge."""
    ids = [p.id for p in fc.data.products]
    return ids.index(product_id) if product_id in ids else len(ids)


def _history_chart(
    fc: Forecast, entries: list[TimelineEntry], measure: str, unit: str
) -> alt.Chart | None:
    records = []
    for e in entries:
        for r in distribution(fc, e).rows:
            value = r.value(measure)
            if value is not None:
                records.append(
                    {
                        "Sprint": e.sprint.id,
                        "Produkt": _product_name(fc, r.product.id, r.product.name),
                        "Rang": _product_rank(fc, r.product.id),
                        unit: value,
                    }
                )
    if not records:
        return None
    frame = (
        pd.DataFrame(records)
        .groupby(["Sprint", "Produkt"], as_index=False)
        .agg({"Rang": "min", unit: "sum"})
    )
    names = [p.name for p in fc.data.products]
    present = list(dict.fromkeys(frame["Produkt"]))
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
                "Produkt:N",
                sort=ordered,
                scale=_product_colors(ordered),
                legend=alt.Legend(orient="top", title=None),
            ),
            order=alt.Order("Rang:Q"),
            tooltip=["Sprint:N", "Produkt:N", alt.Tooltip(f"{unit}:Q", format=".2f")],
        )
    )


def _balance_section(fc: Forecast, entries: list[TimelineEntry], unit: str) -> None:
    rows = balance(fc, entries)
    if not rows:
        st.info("Noch kein **Erledigt je Produkt** erfasst – im Review eintragen.")
        return
    frame = pd.DataFrame(
        [
            {
                "Produkt": b.product.name,
                "Sprints": b.sprints,
                f"Σ Standard ({unit})": round(b.standard, 2),
                f"Σ Erledigt ({unit})": round(b.done, 2),
                f"Saldo ({unit})": round(b.difference, 2),
                "Richtung": "mehr als Standard" if b.difference >= 0 else "weniger als Standard",
            }
            for b in rows
        ]
    )
    st.altair_chart(
        alt.Chart(frame)
        .mark_bar(cornerRadius=4)
        .encode(
            y=alt.Y("Produkt:N", sort=[b.product.name for b in rows], title=None),
            x=alt.X(f"Saldo ({unit}):Q"),
            color=alt.Color(
                "Richtung:N",
                scale=alt.Scale(
                    domain=["mehr als Standard", "weniger als Standard"],
                    range=["#2a78d6", "#e34948"],
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=list(frame.columns[:-1]),
        ),
        width="stretch",
    )
    st.dataframe(frame.drop(columns="Richtung"), hide_index=True)
    st.caption(
        "Saldo = Σ Erledigt − Σ Standard über die Sprints mit erfasstem Erledigt. Positiv: Das "
        "Produkt hat mehr bekommen als den gleichmäßigen Anteil."
    )


def _base_sprint(data: TeamData, sprint: Sprint) -> Sprint:
    return copy.deepcopy(data.sprint(sprint.id) or sprint)


# --- Planning (geführter Ablauf zum Sprintstart) --------------------------------------

PLANNING_STEPS = ["1 · Fehltage", "2 · Forecast PLAN & Einplanung", "3 · Forecast IST"]
STEP_KEY = "planning-step"


def _goto(step: int) -> None:
    st.session_state["planning-goto"] = PLANNING_STEPS[step]


def page_planning(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprint Planning")
    show_flash()
    sprint = _sprint_choice(data, fc, "planning", "Sprint")
    if sprint is None:
        return
    # Neuer Sprint gewählt → beim ersten Schritt beginnen.
    if st.session_state.get("planning-last-sprint") != sprint.id:
        st.session_state["planning-last-sprint"] = sprint.id
        st.session_state["planning-goto"] = PLANNING_STEPS[0]
    if goto := st.session_state.pop("planning-goto", None):
        st.session_state[STEP_KEY] = goto
    st.caption(
        f"Planning am **{day_label(sprint.start)}** · Ablauf: zuerst die bekannten Fehltage, "
        "dann mit dem Forecast PLAN die Tickets einplanen, vor dem Sprintstart den Forecast IST "
        "eintragen."
    )
    step = st.radio(
        "Schritt", PLANNING_STEPS, horizontal=True, key=STEP_KEY, label_visibility="collapsed"
    )
    recorded = data.sprint(sprint.id)
    done = [
        recorded is not None,
        recorded is not None and any(v.planned is not None for v in recorded.products.values()),
        recorded is not None and recorded.forecast_ist is not None,
    ]
    marks = [f"{'✅' if ok else '⬜'} {s[4:]}" for s, ok in zip(PLANNING_STEPS, done, strict=True)]
    st.caption(" · ".join(marks))
    if step == PLANNING_STEPS[0]:
        _planning_absences(repo, data, fc, sprint)
    elif step == PLANNING_STEPS[1]:
        _planning_plan(repo, data, fc, sprint)
    else:
        _planning_ist(repo, data, fc, sprint)


def _planning_absences(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    st.subheader("Bekannte Fehltage")
    st.caption(sprint_caption(data, sprint))
    if not data.people:
        st.warning(
            "Noch keine Personen erfasst – Kapazität nur geschätzt. Personen unter "
            "**Team → Personen** anlegen."
        )
        st.button("Weiter", on_click=_goto, args=(1,), type="primary")
        return
    base = _base_sprint(data, sprint)
    days = len(workdays(base.start, base.end))
    edited = st.data_editor(
        pd.DataFrame(absence_matrix(data.people, [base])),
        column_config={
            "id": None,
            "Person": st.column_config.TextColumn(disabled=True),
            base.id: st.column_config.NumberColumn(
                "Fehltage",
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
    entry = build_forecast(preview, fc.today).entry(after.id)
    left, right = st.columns(2)
    left.metric("Kapazität (PT)", fmt(breakdown.capacity))
    right.metric(
        f"Forecast PLAN ({data.team.unit.value})", fmt(entry.result.plan) if entry else "–"
    )
    if after.capacity is not None:
        st.info(
            f"In der Sprintdatei ist eine feste Kapazität ({fmt(after.capacity)} PT) "
            "eingetragen – sie gilt statt der Berechnung aus den Fehltagen."
        )
    if to_save:
        if st.button("Fehltage speichern und weiter", type="primary"):
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
        st.button("Weiter", on_click=_goto, args=(1,), type="primary")


def _planning_plan(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    entry = fc.entry(sprint.id)
    st.subheader("Forecast PLAN – so viel einplanen")
    if entry is None:
        st.info("Für diesen Sprint gibt es keine Prognose.")
        return
    r = entry.result
    cols = st.columns(4)
    cols[0].metric(
        "Kapazität (PT)",
        fmt(r.plan_capacity),
        help=f"Quelle: {r.plan_capacity_source or '–'}",
    )
    cols[1].metric(f"Forecast PLAN ({unit})", fmt(r.plan))
    cols[2].metric(f"Roadmap ({pct(data.team.forecast.roadmap_share)})", fmt(r.roadmap, 2))
    cols[3].metric("Kleinkram", fmt(r.small_stuff, 2))
    if r.plan_capacity_source is CapacitySource.TREND:
        st.warning("Noch keine Fehltage erfasst – die Kapazität ist nur geschätzt.")
        st.button("Zurück zu den Fehltagen", on_click=_goto, args=(0,))
    if data.products:
        st.subheader("Einplanung je Produkt")
        d = distribution(fc, entry)
        rows = _product_editor(d, ["preplanned", "planned"], f"planning-products-{sprint.id}", unit)
        if rows is not None:
            base = _base_sprint(data, sprint)
            after = apply_product_values(base, rows, ["preplanned", "planned"])
            preview = with_sprints(data, [after])
            fc_preview = build_forecast(preview, fc.today)
            d_preview = distribution(fc_preview, fc_preview.entry(after.id) or entry)
            planned = d_preview.total("planned")
            if planned is not None and r.plan is not None:
                rest = r.plan - planned
                (st.success if rest >= 0 else st.warning)(
                    f"Eingeplant je Produkt: **{fmt(planned, 2)} {unit}** von "
                    f"{fmt(r.plan)} {unit} – "
                    + (f"noch {fmt(rest, 2)} frei." if rest >= 0 else f"{fmt(-rest, 2)} zu viel.")
                )
            if chart := _product_chart(d_preview, unit):
                st.altair_chart(chart, width="stretch")
            if after.products != base.products or data.sprint(after.id) is None:
                if st.button("Produktwerte speichern und weiter", type="primary"):
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
            "Optional: Mit Produkten unter **Team → Produkte** lässt sich hier die "
            "Verteilung auf die Produkte planen und auswerten."
        )
    st.button("Weiter", on_click=_goto, args=(2,), type="primary")


def _planning_ist(repo: Repository, data: TeamData, fc: Forecast, sprint: Sprint) -> None:
    unit = data.team.unit.value
    sprint = _base_sprint(data, sprint)
    entry = fc.entry(sprint.id)
    st.subheader("Forecast IST – vor dem Sprintstart")
    if entry:
        st.caption(
            f"Forecast PLAN {fmt(entry.result.plan)} {unit} · Kapazität {capacity_label(entry)} PT"
        )
    planned = [v.planned for v in sprint.products.values() if v.planned is not None]
    if planned:
        st.caption(f"Summe Planning je Produkt: {fmt(sum(planned), 2)} {unit}")
    with st.form(f"planning-{sprint.id}"):
        forecast_ist = _number(
            f"Forecast IST ({unit})",
            sprint.forecast_ist,
            f"fist-{sprint.id}",
            help_text("forecast_ist"),
        )
        p = sprint.planning or Planning()
        with st.expander("Kontrollrechnung (optional)", expanded=sprint.planning is not None):
            st.caption(
                "Prüft, ob die Planung in den Forecast PLAN passt: Delta = Forecast PLAN − "
                "(Überkipper + Backlog − Korrekturen). Wirkt sich auf keine andere Kennzahl aus. "
                "Ist der Forecast IST leer, wird er mit Überkipper + Backlog vorbelegt; weicht er "
                "davon ab, erscheint ein Hinweis."
            )
            carryover = _number(
                f"Überkipper ({unit})",
                p.carryover or None,
                f"carry-{sprint.id}",
                help_text("carryover"),
            )
            backlog = _number(
                f"Backlog ({unit})", p.backlog or None, f"backlog-{sprint.id}", help_text("backlog")
            )
            corrections_raw = st.text_input(
                f"Korrekturen Restaufwände ({unit})",
                " ".join(f"{c:g}" for c in p.corrections),
                help=help_text("corrections"),
            )
        submitted = st.form_submit_button("Planning speichern", type="primary")
    if not submitted:
        return
    try:
        corrections = parse_numbers(corrections_raw)
    except ValueError:
        st.error("Korrekturen: bitte Zahlen mit Leerzeichen getrennt eingeben.")
        return
    prefilled = apply_planning(
        sprint,
        forecast_ist,
        Planning(carryover=carryover or 0.0, backlog=backlog or 0.0, corrections=corrections),
    )
    freeze_plan(sprint, entry, fc.today)
    if prefilled:
        st.info(
            "Forecast IST aus Überkipper + Backlog übernommen: "
            f"{fmt(sprint.forecast_ist, 2)} {unit}"
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
                f"Planning-Summe {fmt(e.result.planning_total, 2)} {unit} · Forecast PLAN "
                f"{fmt(e.result.plan)} {unit} · Delta {fmt(e.result.planning_delta, 2)} {unit}"
            )
        if sprint.forecast_ist is not None:
            st.success(f"Planning {sprint.id} vollständig – der Sprint kann starten.")


def page_review(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Sprint Review")
    sprint = _sprint_choice(data, fc, "review", "Sprint")
    if sprint is None:
        return
    unit = data.team.unit.value
    computed = sprint_capacity(data.team, data.people, sprint).capacity if data.people else None
    with st.form(f"review-{sprint.id}"):
        capacity = _number(
            "Kapazität (PT) – wird eingefroren",
            sprint.capacity if sprint.capacity is not None else computed,
            f"capacity-{sprint.id}",
            help_text("capacity")
            + (f"\n\nLaut Personenliste und Fehltagen: {fmt(computed)} PT" if computed else ""),
        )
        velocity = _number(
            f"Velocity ({unit})", sprint.velocity, f"velocity-{sprint.id}", help_text("velocity")
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
            st.markdown("**Erledigt je Produkt**")
            product_rows = _product_editor(
                distribution(fc, entry), ["done"], f"review-products-{sprint.id}", unit
            )
        tag = st.checkbox(
            f"Beim Commit Tag {data.team.key}/{sprint.id} setzen",
            value=True,
            key=f"review-tag-{sprint.id}",
        )
        submitted = st.form_submit_button("Review speichern", type="primary")
    if not submitted:
        return
    if capacity is None:
        st.error("Bitte die Kapazität angeben.")
        return
    sprint.capacity = capacity
    sprint.velocity = velocity
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
    st.header("Analyse")
    st.caption(
        "Ergänzt den Forecast. Die Werte auf der Seite **Forecast** (Forecast PLAN, Roadmap, "
        "Kleinkram) bleiben unverändert."
    )
    unit = data.team.unit.value
    window = data.team.forecast.window

    st.subheader("Bandbreite")
    rows = []
    for e in fc.upcoming():
        b = band(fc, e)
        rows.append(
            {
                "Sprint": e.sprint.id,
                f"Forecast PLAN ({unit})": fmt(e.result.plan),
                "konservativ": fmt(b.low if b else None),
                "mittel": fmt(b.mid if b else None),
                "optimistisch": fmt(b.high if b else None),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(
        f"Forecast mit der niedrigsten, mittleren (Median) und höchsten normierten Velocity der "
        f"letzten {window} Sprints statt des Trends – zeigt, wie stark die Planung schwanken kann."
    )

    st.subheader("Wann ist es fertig?")
    share = data.team.forecast.roadmap_share
    with st.form("completion"):
        rest = st.number_input(
            f"Restmenge ({unit})", min_value=0.0, value=None, step=1.0, key="rest",
            help="Noch offene Arbeit, z. B. die Summe eines Roadmap-Themas.",
        )  # fmt: skip
        basis = st.radio(
            "Verfügbar je Sprint",
            [f"Roadmap-Anteil ({pct(share)})", "gesamter Forecast"],
            horizontal=True,
            key="basis",
        )
        project = st.number_input(
            "Projektanteil (%)",
            min_value=1.0,
            max_value=100.0,
            value=100.0,
            step=5.0,
            key="project_share",
            help="Welcher Teil der oben gewählten Kapazität in dieses Projekt fließt – z. B. 50, "
            "wenn parallel ein zweites Roadmap-Thema gleich stark bearbeitet wird.",
        )
        submitted = st.form_submit_button("Berechnen", type="primary")
    if submitted and rest:
        basis_share = share if basis.startswith("Roadmap") else 1.0
        used_share = basis_share * project / 100
        result = completion(data, fc.today, rest, used_share)
        if result is None:
            st.warning("Zu wenig Historie für eine Fertigstellungsprognose.")
        else:
            left, middle, right = st.columns(3)
            left.metric(
                f"je Sprint für das Projekt ({pct(used_share)} des Forecasts)",
                f"≈ {fmt(result.per_sprint, 1)} {unit}",
                help="Median der normierten Velocity × typische Kapazität × Anteil.",
            )
            middle.metric("wahrscheinlich (50 %)", result.p50 or "nach dem Zeitraum")
            right.metric("mit 85 % Sicherheit", result.p85 or "nach dem Zeitraum")
            chart = pd.DataFrame({"Sprint": result.sprints, "fertig bis dahin": result.cumulative})
            # vom ersten Sprint mit Chance bis zum ersten mit (fast) 100 %
            done = chart.index[chart["fertig bis dahin"] >= 0.999]
            chart = chart[chart["fertig bis dahin"] > 0]
            if len(done):
                chart = chart.loc[: done[0]]
            st.altair_chart(
                alt.Chart(chart)
                .mark_bar()
                .encode(
                    x=alt.X("Sprint:N", sort=list(chart["Sprint"])),
                    y=alt.Y(
                        "fertig bis dahin:Q", axis=alt.Axis(format="%"), title="Wahrscheinlichkeit"
                    ),
                    tooltip=["Sprint:N", alt.Tooltip("fertig bis dahin:Q", format=".0%")],
                ),
                width="stretch",
            )
            st.caption(
                f"Monte-Carlo-Simulation ({result.runs:,} Durchläufe) ab dem nächsten Sprint: je "
                "Sprint eine zufällige normierte Velocity der letzten Sprints × Kapazität."
                + (
                    f" Ohne erfasste Fehltage mit Ø Kapazität gerechnet: "
                    f"{', '.join(result.trend_capacity_sprints[:4])}"
                    f"{' …' if len(result.trend_capacity_sprints) > 4 else ''}."
                    if result.trend_capacity_sprints
                    else ""
                )
            )

    st.subheader("Fokusfaktor")
    st.metric(
        f"Ø Fokusfaktor (letzte {window} Sprints)",
        fmt(average_focus_factor(fc), 2),
        help="Velocity / Kapazität. Anders als die normierte Velocity unabhängig von der "
        "Referenzkapazität – damit zwischen Teams vergleichbar. Literaturwerte (0,6–0,8) "
        "beziehen sich meist auf reine Arbeitszeit; zählt die Kapazität alle Anwesenheitstage, "
        "liegen die Werte niedriger.",
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"Sprint": e.sprint.id, "Fokusfaktor": fmt(focus_factor(e), 2)}
                for e in fc.history(window)
            ]
        ),
        hide_index=True,
    )

    st.subheader("Puffer für Ungeplantes")
    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        st.info("Scope Creep wurde zuletzt nicht erfasst – keine Empfehlung möglich.")
    else:
        text = (
            f"Ø Scope Creep der letzten {hint.samples} Sprints: "
            f"**{pct(hint.average_scope_creep)}** · eingestellter Kleinkram-Anteil: "
            f"**{pct(hint.configured_small_stuff)}**"
        )
        if hint.buffer_too_small:
            st.warning(text + " – der Puffer ist kleiner als der ungeplante Anteil.")
        elif hint.sufficient_data:
            st.success(text + " – passt.")
        else:
            st.info(text + " – zu wenige Werte für eine Empfehlung.")


def page_products(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Produktverteilung")
    unit = data.team.unit.value
    if not data.products:
        st.info(
            "Noch keine Produkte erfasst. Mit Produkten zeigt diese Seite, wie sich die "
            "Sprint-Menge auf die Produkte verteilt: Standard, PO-Vorplanung, Planning und "
            "Erledigt."
        )
        page_link("produktliste", "Produkte anlegen")
        return
    sprint = _sprint_choice(data, fc, "planning", "Sprint", key="products-sprint")
    if sprint is None:
        return
    entry = fc.entry(sprint.id)
    if entry is None:
        return
    st.caption(
        "Die **PO-Vorplanung** tragen die POs vor dem Planning ein, **Planning** wird im Sprint "
        "Planning gefüllt, **Erledigt** im Review. Alles lässt sich auch hier pflegen."
    )
    d = distribution(fc, entry)
    rows = _product_editor(d, ["preplanned", "planned", "done"], f"products-{sprint.id}", unit)
    if rows is not None:
        base = _base_sprint(data, sprint)
        after = apply_product_values(base, rows, ["preplanned", "planned", "done"])
        preview = with_sprints(data, [after])
        fc_preview = build_forecast(preview, fc.today)
        d = distribution(fc_preview, fc_preview.entry(after.id) or entry)
        changed = after.products != base.products
        if st.button("Produktwerte speichern", type="primary", disabled=not changed):
            save(preview, [f"{after.id}.yaml"], lambda: [repo.save_sprint(data.team.key, after)])
        if chart := _product_chart(d, unit):
            st.altair_chart(chart, width="stretch")
        if po_rows := by_po(d):
            st.markdown("**Je PO**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"PO": po, **{MEASURES[m]: fmt(v, 2) for m, v in totals.items()}}
                        for po, totals in po_rows
                    ]
                ),
                hide_index=True,
            )

    st.subheader("Verlauf")
    count = st.number_input("Anzahl Sprints", min_value=2, max_value=26, value=6, key="products-n")
    entries = [e for e in fc.entries if e.sprint.start <= sprint.start][-int(count) :]
    labels = {MEASURES[m]: m for m in ("done", "planned", "preplanned")}
    chosen = st.radio("Kennzahl", list(labels), horizontal=True, key="products-measure")
    chart = _history_chart(fc, entries, labels[chosen], unit)
    if chart is None:
        st.info(f"In diesen Sprints ist noch kein Wert „{chosen}“ erfasst.")
    else:
        st.altair_chart(chart, width="stretch")
    st.subheader("Saldo gegenüber der Standardverteilung")
    _balance_section(fc, entries, unit)


def page_product_list(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header("Produkte")
    st.markdown(
        "Produkte, die das Team betreut – mit verantwortlichem PO (optional) und Zeitraum.  \n"
        "**Produkt abgegeben:** **bis** setzen statt löschen – sonst fehlen die Werte "
        "vergangener Sprints in der Auswertung.  \n"
        "**Neues Produkt:** Zeile ergänzen, **ab** = erster betreuter Tag (leer = schon immer)."
    )
    show_former = st.toggle("Ehemalige anzeigen", value=False, key="show_former_products")
    rows, hidden = product_table(data.products, fc.today, show_former)
    if hidden:
        st.caption(f"{len(hidden)} ehemalige(s) Produkt(e) ausgeblendet.")
    frame = pd.DataFrame(rows, columns=PRODUCT_COLUMNS)
    for col in ("ab", "bis"):
        frame[col] = pd.to_datetime(frame[col])
    frame["PO"] = frame["PO"].astype("string")
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,
            "Name": st.column_config.TextColumn("Name", required=True),
            "PO": st.column_config.TextColumn("PO", help="Verantwortlicher Product Owner"),
            "ab": st.column_config.DateColumn("ab", format="DD.MM.YYYY", help="Leer = schon immer"),
            "bis": st.column_config.DateColumn(
                "bis", format="DD.MM.YYYY", help="Leer = weiterhin betreut"
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
            f"Gelöscht: {', '.join(result.deleted)}.  \nNur löschen, wenn falsch erfasst. "
            "Gibt das Team ein Produkt ab, stattdessen **bis** setzen."
        )
        confirmed = st.checkbox("Ja, die Zeilen waren Fehleingaben", key="confirm_delete_products")
    if not st.button("Produkte speichern", type="primary", disabled=not confirmed):
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
    st.header("Personen")
    st.markdown(
        "Eine Zeile je Zeitraum im Team.  \n"
        "**Austritt:** in der Zeile **bis** setzen – nicht löschen, sonst ändern sich "
        "Kapazitäten und Fehltage vergangener Sprints.  \n"
        "**FTE-Änderung:** in der bisherigen Zeile **bis** setzen und eine neue Zeile mit "
        "**gleichem Namen** und neuem FTE-Anteil anlegen."
    )
    show_former = st.toggle("Ehemalige anzeigen", value=False, key="show_former")
    rows, hidden = people_table(data.people, fc.today, show_former)
    if hidden:
        st.caption(f"{len(hidden)} ehemalige Person(en) ausgeblendet.")
    frame = pd.DataFrame(rows, columns=PEOPLE_COLUMNS)
    for col in ("ab", "bis"):
        frame[col] = pd.to_datetime(frame[col])
    edited = st.data_editor(
        frame,
        column_config={
            "_id": None,  # interne ID, wird automatisch vergeben
            "Name": st.column_config.TextColumn("Name", required=True),
            "Bundesland": st.column_config.SelectboxColumn(
                "Bundesland",
                options=[TEAM_REGION, *REGIONS],
                default=TEAM_REGION,
                help="(Team) = Einstellung des Teams",
            ),
            "ab": st.column_config.DateColumn(
                "ab", format="DD.MM.YYYY", required=True, default=fc.today
            ),
            "bis": st.column_config.DateColumn(
                "bis", format="DD.MM.YYYY", help="Leer = weiterhin im Team"
            ),
            "FTE": st.column_config.NumberColumn(
                "FTE",
                min_value=0.05,
                max_value=1.0,
                step=0.05,
                default=1.0,
                help="Anteil im Team, 1 = Vollzeit",
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
            f"Gelöscht: {', '.join(result.deleted)}.  \nZeilen nur löschen, wenn sie "
            "**falsch erfasst** wurden. Verlässt jemand das Team, stattdessen **bis** setzen – "
            "sonst entstehen Inkonsistenzen (z. B. Fehltage für unbekannte Personen)."
        )
        confirmed = st.checkbox("Ja, die Zeilen waren Fehleingaben", key="confirm_delete")
    if not st.button("Personen speichern", type="primary", disabled=not confirmed):
        return
    if result.errors:
        for e in result.errors:
            st.error(e)
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
    label = setting.label
    match setting.kind:
        case Kind.TEXT:
            return st.text_input(label, shown, help=setting.help, key=key)
        case Kind.CHOICE:
            assert setting.choices is not None
            options = ([""] if setting.optional else []) + list(setting.choices)
            return st.selectbox(
                label,
                options,
                index=options.index(shown) if shown in options else 0,
                format_func=lambda k: f"{k} – {setting.choices[k]}" if k else "(keine Angabe)",
                help=setting.help,
                key=key,
            )
        case Kind.DATE:
            value = st.date_input(
                label, setting.get(team), help=setting.help, key=key, format="DD.MM.YYYY"
            )
            return value.isoformat() if isinstance(value, date) else ""
        case Kind.INT:
            value = st.number_input(
                label,
                min_value=int(setting.minimum) if setting.minimum is not None else None,
                max_value=int(setting.maximum) if setting.maximum is not None else None,
                value=int(shown),
                step=1,
                help=setting.help,
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
                help=setting.help,
                key=key,
            )
            return str(value)
    raise AssertionError(setting.kind)


def _settings_form(team: Team, has_sprints: bool, form_key: str, submit: str) -> Team | None:
    """Formular für alle Einstellungen; liefert das geänderte Team nach dem Absenden."""
    edited = copy.deepcopy(team)
    with st.form(form_key):
        raw = {
            s.key: _setting_widget(s, team, f"{form_key}-{s.key}") for s in applicable(has_sprints)
        }
        submitted = st.form_submit_button(submit, type="primary")
    if not submitted:
        return None
    errors = []
    for s in applicable(has_sprints):
        try:
            value = s.parse(raw[s.key])
            if value is None and s.only_without_sprints:
                raise ValueError("Bitte einen Wert eingeben.")
            s.set(edited, value)
        except ValueError as e:
            errors.append(f"{s.label}: {e}")
    for e in errors:
        st.error(e)
    return None if errors else edited


def page_settings(repo: Repository, data: TeamData, fc: Forecast) -> None:
    st.header(f"Einstellungen {data.team.name}")
    edited = _settings_form(data.team, bool(data.sprints), f"settings-{data.team.key}", "Speichern")
    if edited is None:
        return
    diff = changes(data.team, edited)
    if not diff:
        st.info("Keine Änderungen.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {"Einstellung": s.label, "bisher": old or "–", "neu": new or "–"}
                for s, old, new in diff
            ]
        ),
        hide_index=True,
    )
    if any(s.retroactive for s, _, _ in diff):
        st.warning("Mindestens eine Änderung wirkt rückwirkend auf alle berechneten Werte.")
    after = copy.deepcopy(data)
    after.team = edited
    save(
        after,
        ["team.yaml"],
        lambda: [repo.save_team(edited)],
    )


def page_new_team(repo: Repository) -> None:
    st.header("Neues Team anlegen")
    key = (
        st.text_input("Team-Kürzel (Verzeichnisname)", help="Kleinbuchstaben, z. B. team-a")
        .strip()
        .lower()
    )
    if not key:
        return
    if repo.exists(key):
        st.error(f"Team '{key}' existiert bereits.")
        return
    team = Team(key=key, name=key.upper())
    team.sprint.first_start = today()
    team.sprint.first_id = f"{today().year}.1"
    team.sprint.numbering = Numbering.YEARLY
    edited = _settings_form(team, False, f"new-{key}", "Team anlegen")
    if edited is None:
        return
    if save(
        TeamData(team=edited),
        ["team.yaml"],
        lambda: [repo.save_team(edited), repo.save_people(key, [])],
    ):
        st.session_state["selected_team"] = key
        page_link("personen", "Weiter: Personen erfassen")


def page_check(repo: Repository) -> None:
    st.header("Prüfung aller Teams")
    for key, issues in check_all(repo, today()).items():
        if not issues:
            st.success(f"{key}: keine Befunde")
            continue
        st.subheader(key)
        for i in issues:
            (st.error if i.level is Level.ERROR else st.warning)(f"{i.where}: {i.message}")


def page_help(repo: Repository) -> None:
    st.header("Hilfe")
    st.markdown(
        "Die Weboberfläche bearbeitet dieselben Dateien wie die Kommandozeile – beides lässt "
        "sich mischen. Gespeichert wird lokal; mit **Änderungen committen** in der Seitenleiste "
        "landen die Änderungen im Git-Repository der Daten."
    )
    ablauf, begriffe, felder, team, befehle = st.tabs(
        ["Ablauf", "Begriffe", "Eingabefelder", "Team-Einstellungen", "Kommandozeile"]
    )
    with ablauf:
        for step in WORKFLOW:
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment="center")
                left.caption(step.when)
                left.markdown(f"**{step.title}**  \n{step.text}")
                with right:
                    page_link(step.page)
    with begriffe:
        st.table(pd.DataFrame(TERMS, columns=["Begriff", "Bedeutung"]).set_index("Begriff"))
        st.subheader("Kapazitätsquelle im Forecast")
        st.table(
            pd.DataFrame(CAPACITY_SOURCES, columns=["Quelle", "Bedeutung"]).set_index("Quelle")
        )
    with felder:
        for f in FIELDS.values():
            with st.container(border=True):
                st.markdown(f"**{f.title}**  \n{f.what}")
                st.caption(f"Quelle: {f.source} · Beispiel: {f.example}")
    with team:
        st.table(
            pd.DataFrame(
                [(s.label, s.help) for s in SETTINGS], columns=["Einstellung", "Bedeutung"]
            ).set_index("Einstellung")
        )
        page_link("einstellungen", "Einstellungen ändern")
    with befehle:
        st.table(pd.DataFrame(COMMANDS, columns=["Befehl", "Zweck"]).set_index("Befehl"))
        st.caption("Ausführen mit `uv run …` im Ordner des Tools.")


# --- Seitenleiste und Seitenaufruf ----------------------------------------------------


def sidebar(repo: Repository) -> None:
    """Teamauswahl in der Seitenleiste (vor der Seite, damit diese das Team kennt)."""
    teams = repo.teams()
    with st.sidebar:
        if not teams:
            st.info("Noch kein Team vorhanden.")
            return
        wanted = st.session_state.get("selected_team")
        team = st.selectbox("Team", teams, index=teams.index(wanted) if wanted in teams else 0)
        st.session_state["selected_team"] = team


def sidebar_footer(repo: Repository) -> None:
    """Git-Bereich und Hinweise – nach der Seite gezeichnet, damit gerade Gespeichertes
    bereits als offene Änderung erscheint."""
    _git_panel(repo)
    st.caption(f"Daten: `{repo.root.resolve()}`  \nStichtag: {today():%d.%m.%Y}  \n{status_line()}")


COMMIT_DEFAULT = "Sprint-Daten aktualisiert"


def _commit_clicked(root: Path, tags: list[str]) -> None:
    """Callback des Commit-Knopfs; läuft vor dem nächsten Durchlauf des Skripts."""
    message = st.session_state.get("commit_message", "").strip() or COMMIT_DEFAULT
    use_tags = tags and st.session_state.get("use_tags", True)
    try:
        rev = commit_directory(root, message, tags if use_tags else None)
    except GitError as e:
        st.session_state["commit_error"] = str(e)
        return
    st.session_state["pending_tags"] = []
    st.session_state["last_commit"] = rev
    st.session_state["commit_message"] = COMMIT_DEFAULT


def _git_panel(repo: Repository) -> None:
    if git_root(repo.root) is None:
        st.caption("Datenverzeichnis liegt in keinem Git-Repository – Commit nicht möglich.")
        return
    if last := st.session_state.pop("last_commit", None):
        st.success(f"Committet ({last}). Pushen nicht vergessen.")
    if error := st.session_state.pop("commit_error", None):
        st.error(error)
    try:
        changes = pending_changes(repo.root)
    except GitError as e:
        st.caption(f"Git: {e}")
        return
    tags = st.session_state.get("pending_tags", [])
    with st.expander(
        f"Git: {len(changes)} offene Änderung(en)" if changes else "Git: alles committet",
        expanded=bool(changes),
        icon=":material/commit:",
    ):
        if not changes:
            st.caption("Keine offenen Änderungen im Datenverzeichnis.")
            return
        st.code("\n".join(f"{status:>2} {file}" for status, file in changes), language=None)
        st.session_state.setdefault("commit_message", COMMIT_DEFAULT)
        st.text_input("Commit-Nachricht", key="commit_message")
        if tags:
            st.checkbox(f"Tags setzen: {', '.join(tags)}", value=True, key="use_tags")
        st.button(
            "Änderungen committen",
            type="primary",
            icon=":material/save:",
            on_click=_commit_clicked,
            args=(repo.root, list(tags)),
        )


TEAM_PAGES = {
    "forecast": page_forecast,
    "fehltage": page_absences,
    "sprints": page_calendar,
    "planning": page_planning,
    "review": page_review,
    "produkte": page_products,
    "analyse": page_analysis,
    "personen": page_people,
    "produktliste": page_product_list,
    "einstellungen": page_settings,
}
GLOBAL_PAGES = {
    "neues_team": page_new_team,
    "pruefung": page_check,
    "hilfe": page_help,
}


def run_page(key: str) -> None:
    """Wird von den Seitendateien unter web/seiten aufgerufen."""
    repo = repository()
    team = st.session_state.get("selected_team")
    if key in GLOBAL_PAGES:
        GLOBAL_PAGES[key](repo)
        return
    if team is None or not repo.exists(team):
        st.header(PAGE_INFO[key][0])
        st.info(
            "Noch kein Team vorhanden – ein Team anlegen oder über ein Import-Plugin übernehmen."
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
