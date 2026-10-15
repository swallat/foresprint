# SPDX-License-Identifier: EUPL-1.2
"""Markdown-Bericht (wird von GitHub/GitLab inkl. Mermaid-Diagramm gerendert)."""

from __future__ import annotations

from sprintforecast.engine import CapacitySource
from sprintforecast.forecast import Forecast, TimelineEntry


def fmt(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text + suffix


def pct(value: float | None) -> str:
    return "–" if value is None else fmt(value * 100, 0, " %")


def period(e: TimelineEntry) -> str:
    return f"{e.sprint.start:%d.%m.} – {e.sprint.end:%d.%m.%Y}"


def capacity_label(e: TimelineEntry) -> str:
    source = e.result.plan_capacity_source
    value = fmt(e.result.plan_capacity)
    if source is CapacitySource.TREND:
        return f"{value} ⚠️ Trend"
    return f"{value} ({source})" if source else value


def status(fc: Forecast, e: TimelineEntry) -> str:
    if e.sprint.end <= fc.today:
        return "abgeschlossen"
    if e.sprint.start <= fc.today:
        return "**laufend**"
    return "geplant"


def render(fc: Forecast, history: int = 10) -> str:
    team = fc.data.team
    unit = team.unit.value
    f = team.forecast
    lines = [
        f"# Sprint-Forecast {team.name}",
        "",
        f"Stand: {fc.today:%d.%m.%Y} · Einheit: {unit} · "
        f"Referenzkapazität: {fmt(f.reference_capacity, 0)} PT · "
        f"Ø über {f.window} Sprints · Trend: `{f.trend_mode.value}`",
        "",
        "> Automatisch erzeugt mit `sprintforecast bericht`. Nicht von Hand bearbeiten.",
        "",
        "## Prognose",
        "",
        "| Sprint | Zeitraum | Status | Kapazität (PT) | n. Velocity-Trend "
        f"| **Forecast PLAN** ({unit}) | Roadmap ({pct(f.roadmap_share)}) | Kleinkram |",
        "|---|---|---|---|---|---|---|---|",
    ]
    upcoming = fc.upcoming()
    for e in upcoming:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {period(e)} | {status(fc, e)} | {capacity_label(e)} "
            f"| {fmt(r.normalized_velocity.trend, 2)} | **{fmt(r.plan)}** "
            f"| {fmt(r.roadmap, 2)} | {fmt(r.small_stuff, 2)} |"
        )
    if any(e.result.plan_capacity_source is CapacitySource.TREND for e in upcoming):
        lines += [
            "",
            "⚠️ *Trend*: Für diesen Sprint sind noch keine Fehltage erfasst, die Kapazität ist "
            "geschätzt. Mit `sprintforecast fehltage "
            f"{team.key} <SPRINT>` wird die Prognose belastbar.",
        ]

    current = fc.current
    if current and current.result.planning_total is not None:
        r = current.result
        lines += [
            "",
            f"**Planning {current.sprint.id}:** Summe {fmt(r.planning_total, 2)} {unit}, "
            f"Delta zum Forecast PLAN {fmt(r.planning_delta, 2)} {unit}",
        ]

    past = fc.history(history)
    lines += [
        "",
        f"## Verlauf (letzte {len(past)} Sprints)",
        "",
        "| Sprint | Kapazität (PT) | Forecast IST | Velocity | n. Velocity | Ø n. Velocity "
        "| Fulfillment | Scope Creep |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in past:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {fmt(r.capacity.value)} | {fmt(r.forecast_ist.value, 2)} "
            f"| {fmt(r.velocity.value, 2)} | {fmt(r.normalized_velocity.value, 2)} "
            f"| {fmt(r.normalized_velocity.average, 2)} | {pct(r.fulfillment.value)} "
            f"| {pct(r.scope_creep.value)} |"
        )

    chart = past + [e for e in upcoming if e not in past]
    if len(chart) >= 2:

        def series(values: list[float | None]) -> str:
            return "[" + ", ".join("0" if v is None else f"{v:.2f}" for v in values) + "]"

        lines += [
            "",
            "## Diagramm",
            "",
            "Linien: Forecast IST (Vergangenheit) bzw. Forecast PLAN (Zukunft), Velocity und "
            "normierte Velocity (Vergangenheit: Ist-Wert, Zukunft: Trend).",
            "",
            "```mermaid",
            "xychart-beta",
            f"    x-axis [{', '.join(f'"{e.sprint.id}"' for e in chart)}]",
            f'    y-axis "{unit}"',
            "    line " + series([e.result.forecast_ist.value or e.result.plan for e in chart]),
            "    line "
            + series([e.result.velocity.value or e.result.velocity.trend for e in chart]),
            "    line "
            + series(
                [
                    e.result.normalized_velocity.value or e.result.normalized_velocity.trend
                    for e in chart
                ]
            ),
            "```",
        ]
    return "\n".join(lines) + "\n"
