# SPDX-License-Identifier: EUPL-1.2
"""Markdown-Bericht (wird von GitHub/GitLab inkl. Mermaid-Diagramm gerendert)."""

from __future__ import annotations

from sprintforecast.analysis import average_focus_factor, band, buffer_hint
from sprintforecast.engine import UNSURE_SOURCES, CapacitySource
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import is_english, t
from sprintforecast.model import AbsenceState, Sprint, absence_status


def fmt(value: float | None, digits: int = 1, suffix: str = "") -> str:
    """Zahl mit Tausender- und Dezimaltrennzeichen der Sprache (1.234,5 bzw. 1,234.5)."""
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}"
    if not is_english():
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text + suffix


def pct(value: float | None) -> str:
    return "–" if value is None else fmt(value * 100, 0, " %")


def period(e: TimelineEntry) -> str:
    return f"{e.sprint.start:%d.%m.} – {e.sprint.end:%d.%m.%Y}"


def source_label(source: CapacitySource | None) -> str:
    return t(source.value) if source else ""


def capacity_label(e: TimelineEntry) -> str:
    source = e.result.plan_capacity_source
    value = fmt(e.result.plan_capacity)
    if source in UNSURE_SOURCES:
        return f"{value} ⚠️ {source_label(source)}"
    return f"{value} ({source_label(source)})" if source else value


def absence_status_label(sprint: Sprint) -> str:
    """Stand der Fehltage eines Sprints in Worten."""
    return {
        AbsenceState.CONFIRMED: t("bestätigt"),
        AbsenceState.EXPECTED: t("voraussichtlich"),
        AbsenceState.UNKNOWN: t("unbekannt"),
    }[absence_status(sprint)]


def reliability_notes(fc: Forecast) -> list[str]:
    """Hinweise zur Belastbarkeit der Prognose (Kommandozeile und Bericht)."""
    from sprintforecast.analysis import MIN_SAMPLES, sample_count
    from sprintforecast.model import TrendMode

    notes = []
    samples = sample_count(fc)
    if samples and samples < MIN_SAMPLES:
        notes.append(
            t(
                "Wenig Daten: bisher nur {samples} Sprints mit Velocity (ab {min} ist die Spanne "
                "belastbarer). Plan und Spanne sind grobe Hinweise.",
                samples=samples,
                min=MIN_SAMPLES,
            )
        )
    mode = fc.data.team.forecast.trend_mode
    if any(e.result.trend_fallback for e in fc.upcoming()):
        notes.append(
            t(
                "Historie dünn: Für den Trend-Modus {mode} reicht die Historie nicht, es gilt "
                "„konstant“ (letzter Durchschnitt).",
                mode=mode.value,
            )
        )
    if mode is not TrendMode.FLAT:
        notes.append(
            t(
                "Trend-Modus {mode}: schreibt Schwankungen fort und kann steigen oder fallen "
                "(Vorsicht bei langen Horizonten). Robust ist „konstant“ (flat) – einstellbar mit "
                "`sprintforecast einstellungen`.",
                mode=mode.value,
            )
        )
    return notes


def status(fc: Forecast, e: TimelineEntry) -> str:
    if e.sprint.end <= fc.today:
        return t("abgeschlossen")
    if e.sprint.start <= fc.today:
        return f"**{t('laufend')}**"
    return t("geplant")


def render(fc: Forecast, history: int = 10) -> str:
    team = fc.data.team
    unit = team.unit.value
    f = team.forecast
    lines = [
        f"# Sprint-Forecast {team.name}",
        "",
        t(
            "Stand: {today} · Einheit: {unit} · Referenzkapazität: {ref} PT · Ø über {window} "
            "Sprints · Trend: `{mode}`",
            today=f"{fc.today:%d.%m.%Y}",
            unit=unit,
            ref=fmt(f.reference_capacity, 0),
            window=f.window,
            mode=f.trend_mode.value,
        ),
        "",
        t("> Automatisch erzeugt mit `sprintforecast bericht`. Nicht von Hand bearbeiten."),
        "",
        f"## {t('Prognose')}",
        "",
        "| Sprint | "
        + t(
            "Zeitraum | Status | Kapazität (PT) | n. Velocity-Trend | **Forecast PLAN** ({unit}) "
            "| Roadmap ({share}) | Kleinkram |",
            unit=unit,
            share=pct(f.roadmap_share),
        ),
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
    if any(e.result.plan_capacity_source in UNSURE_SOURCES for e in upcoming):
        lines += [
            "",
            t(
                "⚠️ *Trend/Kalender*: Für diesen Sprint sind noch keine Fehltage erfasst, die "
                "Kapazität ist geschätzt. Mit `sprintforecast fehltage {team} <SPRINT>` wird die "
                "Prognose belastbar.",
                team=team.key,
            ),
        ]

    for note in reliability_notes(fc):
        lines += ["", f"⚠️ {note}"]

    current = fc.current
    if current and current.result.planning_total is not None:
        r = current.result
        lines += [
            "",
            t(
                "**Planning {id}:** Summe {total} {unit}, Delta zum Forecast PLAN {delta} {unit}",
                id=current.sprint.id,
                total=fmt(r.planning_total, 2),
                delta=fmt(r.planning_delta, 2),
                unit=unit,
            ),
        ]

    past = fc.history(history)
    lines += [
        "",
        t("## Verlauf (letzte {count} Sprints)", count=len(past)),
        "",
        "| Sprint | "
        + t(
            "Kapazität (PT) | Forecast IST | Velocity | n. Velocity | Ø n. Velocity "
            "| Fulfillment | Scope Creep |"
        ),
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
            f"## {t('Diagramm')}",
            "",
            t(
                "Linien: Forecast IST (Vergangenheit) bzw. Forecast PLAN (Zukunft), Velocity und "
                "normierte Velocity (Vergangenheit: Ist-Wert, Zukunft: Trend)."
            ),
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
    lines += _products_section(fc)
    lines += _analysis_section(fc)
    return "\n".join(lines) + "\n"


def _analysis_section(fc: Forecast) -> list[str]:
    """Ergänzende Analysen (Bandbreite, Fokusfaktor, Puffer) – am Ende des Berichts."""
    unit = fc.data.team.unit.value
    rows = [(e, b) for e in fc.upcoming() if (b := band(fc, e)) is not None]
    lines: list[str] = []
    if rows:
        lines += [
            "",
            t("## Ergänzend: Bandbreite"),
            "",
            t(
                "Forecast mit der niedrigsten, mittleren und höchsten normierten Velocity der "
                "letzten {count} Sprints (statt des Trends).",
                count=rows[0][1].samples,
            ),
            "",
            t(
                "| Sprint | Forecast PLAN ({unit}) | konservativ | mittel | optimistisch |",
                unit=unit,
            ),
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {e.sprint.id} | {fmt(e.result.plan)} | {fmt(b.low)} | {fmt(b.mid)} "
            f"| {fmt(b.high)} |"
            for e, b in rows
        ]
    focus = average_focus_factor(fc)
    hint = buffer_hint(fc)
    facts = []
    if focus is not None:
        facts.append(t("Ø Fokusfaktor (Velocity / Kapazität): {value}", value=fmt(focus, 2)))
    if hint.average_scope_creep is not None:
        facts.append(
            t(
                "Ø Scope Creep ({count} Sprints): {scope} · Kleinkram-Anteil: {small}",
                count=hint.samples,
                scope=pct(hint.average_scope_creep),
                small=pct(hint.configured_small_stuff),
            )
            + (t(" ⚠️ Puffer kleiner als der ungeplante Anteil") if hint.buffer_too_small else "")
        )
    if facts:
        lines += ["", *[f"- {f}" for f in facts]]
    return lines


def _products_section(fc: Forecast, history: int = 6) -> list[str]:
    """Verteilung je Produkt: laufender und nächster Sprint, Saldo der letzten Sprints."""
    from sprintforecast.products import MEASURES, balance, distribution, measure_label

    if not fc.data.products:
        return []
    unit = fc.data.team.unit.value
    lines = ["", f"## {t('Produkte')}"]
    shown = []
    for e in (fc.current, fc.default_entry("planning")):
        if e is not None and e not in shown:
            shown.append(e)
    for e in shown:
        d = distribution(fc, e)
        if not d.rows:
            continue
        lines += [
            "",
            f"**Sprint {e.sprint.id}** ({status(fc, e).replace('*', '')})",
            "",
            f"| {t('Produkt')} | PO | "
            + " | ".join(f"{measure_label(m)} ({unit})" for m in MEASURES)
            + " |",
            "|---|---|" + "---|" * len(MEASURES),
        ]
        lines += [
            f"| {r.product.name} | {r.product.po or ''} | "
            + " | ".join(fmt(r.value(m), 2) for m in MEASURES)
            + " |"
            for r in d.rows
        ]
    rows = balance(fc, fc.history(history))
    if rows:
        lines += [
            "",
            t("**Saldo** (Σ Erledigt − Σ Standard, letzte {count} Sprints)", count=history),
            "",
            t("| Produkt | Sprints | Σ Standard | Σ Erledigt | Saldo ({unit}) |", unit=unit),
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {b.product.name} | {b.sprints} | {fmt(b.standard, 2)} | {fmt(b.done, 2)} "
            f"| {fmt(b.difference, 2)} |"
            for b in rows
        ]
    return lines
