# SPDX-License-Identifier: EUPL-1.2
"""Markdown-Bericht (wird von GitHub/GitLab inkl. Mermaid-Diagramm gerendert)."""

from __future__ import annotations

from sprintforecast.analysis import MIN_SAMPLES, average_focus_factor, band, buffer_hint
from sprintforecast.engine import UNSURE_SOURCES, CapacitySource, round_half_up
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


def fmt_capacity(value: float | None, digits: int = 1) -> str:
    """Kapazität für die Anzeige, kaufmännisch gerundet (ab ,5 auf) wie ``rounded`` und der
    eingefrorene Wert. Pythons Formatierung rundet bei exakter Hälfte zur geraden Ziffer
    (25,25 → „25,2“) und darf für Kapazitäten nicht direkt benutzt werden. Die Prognose rechnet
    weiter mit dem ungerundeten Wert.

    ``digits`` ist die Einstellung ``capacity.rounding`` des Teams (Standard 1), dieselbe wie bei
    ``CapacityBreakdown.rounded``: Anzeige und eingefrorener Wert stimmen so auch bei einer
    anderen Stellenzahl überein. Aufrufer mit Team bzw. Sprint übergeben sie
    (``TimelineEntry.capacity_digits``, ``CapacityBreakdown.rounding``)."""
    return "–" if value is None else fmt(round_half_up(value, digits), digits)


def pct(value: float | None) -> str:
    return "–" if value is None else fmt(value * 100, 0, " %")


def period(e: TimelineEntry) -> str:
    return f"{e.sprint.start:%d.%m.} – {e.sprint.end:%d.%m.%Y}"


def source_label(source: CapacitySource | None) -> str:
    return t(source.value) if source else ""


def capacity_source_note(e: TimelineEntry) -> str:
    """Quelle der Kapazität allein (ohne Zahl) – für Kennzahlen, deren Wert nicht durch einen
    angehängten Text gekürzt werden soll; bei unsicherer Quelle mit Warnzeichen, ohne Quelle
    leer."""
    source = e.result.plan_capacity_source
    if source in UNSURE_SOURCES:
        return f"⚠️ {source_label(source)}"
    return source_label(source)


def capacity_label(e: TimelineEntry) -> str:
    """Kapazität mit angehängter Quelle als ein Text (Tabellen, Berichte, Kommandozeile)."""
    source = e.result.plan_capacity_source
    value = fmt_capacity(e.result.plan_capacity, e.capacity_digits)
    if source in UNSURE_SOURCES:
        return f"{value} {capacity_source_note(e)}"
    return f"{value} ({capacity_source_note(e)})" if source else value


def band_range(fc: Forecast, e: TimelineEntry) -> str:
    """„niedrig–hoch“ der Spanne eines künftigen Sprints für Tabellen („–“, wenn nicht
    berechenbar oder der Sprint schon abgeschlossen ist)."""
    from sprintforecast.analysis import band

    b = band(fc, e) if e.sprint.end > fc.today else None
    return f"{fmt(b.low)}–{fmt(b.high)}" if b else "–"


def band_note(fc: Forecast, e: TimelineEntry, without_assumption: bool = False) -> str:
    """Spanne mit Stichprobengröße als Satz direkt an einer Prognose-Kachel; bei wenig Daten
    mit Hinweis. Leer, wenn die Spanne nicht berechenbar ist oder der Sprint schon abgeschlossen
    ist (die Spanne gehört zur heutigen Historie, die Prognose eines alten Sprints nicht).
    ``without_assumption``: Die Prognose daneben rechnet mit einer Annahme, die Spanne nicht."""
    from sprintforecast.analysis import band, few_samples

    b = band(fc, e) if e.sprint.end > fc.today else None
    if b is None:
        return ""
    note = t(
        "Spanne {low}–{high} aus den letzten {samples} Sprints",
        low=fmt(b.low),
        high=fmt(b.high),
        samples=b.samples,
    )
    if without_assumption:
        note = f"{note} ({t('ohne die Annahme')})"
    return f"{note} · {t('wenig Daten, grober Hinweis')}" if few_samples(fc) else note


def absence_status_label(sprint: Sprint) -> str:
    """Stand der Fehltage eines Sprints in Worten."""
    return {
        AbsenceState.CONFIRMED: t("bestätigt"),
        AbsenceState.EXPECTED: t("angekündigt"),
        AbsenceState.UNKNOWN: t("unbekannt"),
    }[absence_status(sprint)]


def reliability_notes(fc: Forecast) -> list[str]:
    """Hinweise zur Belastbarkeit der Prognose (Kommandozeile und Bericht)."""
    from sprintforecast.analysis import sample_count
    from sprintforecast.model import TrendMode

    notes = []
    samples = sample_count(fc)
    if samples and samples < MIN_SAMPLES:
        notes.append(
            " ".join(
                part
                for part in (
                    t(
                        "Wenig Daten: bisher nur {samples} Sprints mit Velocity (ab {min} ist die "
                        "Spanne belastbarer). Plan und Spanne sind grobe Hinweise.",
                        samples=samples,
                        min=MIN_SAMPLES,
                    ),
                    window_hint(fc.data.team.forecast.window),
                )
                if part
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


def window_hint(window: int) -> str:
    """Zusatz zu „Wenig Daten“ bei einem Prognosefenster unter ``MIN_SAMPLES``: Die Stichprobe
    ist auf das Fenster gedeckelt und kann die Schwelle dann nie erreichen. Sonst leer."""
    if window >= MIN_SAMPLES:
        return ""
    return t(
        "Das Prognosefenster ist auf {window} Sprints gestellt; mit einem größeren Fenster "
        "(Einstellungen) gehen mehr Werte in die Spanne ein.",
        window=window,
    )


def completion_note(samples: int) -> str | None:
    """Warnung der Fertigstellungs-Simulation bei wenig Daten (Kommandozeile und Weboberfläche)."""
    if samples >= MIN_SAMPLES:
        return None
    return t(
        "Wenig Daten: Die Simulation zieht aus nur {samples} Sprints (ab {min} "
        "sind Aussagen belastbarer). Die Häufigkeiten sind grobe Hinweise.",
        samples=samples,
        min=MIN_SAMPLES,
    )


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
            "| Spanne | Roadmap ({share}) | Kleinkram |",
            unit=unit,
            share=pct(f.roadmap_share),
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    upcoming = fc.upcoming()
    for e in upcoming:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {period(e)} | {status(fc, e)} | {capacity_label(e)} "
            f"| {fmt(r.normalized_velocity.trend, 2)} | **{fmt(r.plan)}** "
            f"| {band_range(fc, e)} | {fmt(r.roadmap, 2)} | {fmt(r.small_stuff, 2)} |"
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
            "Kapazität (PT) | Commitment | Velocity | n. Velocity | Ø n. Velocity "
            "| Fulfillment | Scope Creep |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in past:
        r = e.result
        lines.append(
            f"| {e.sprint.id} | {fmt_capacity(r.capacity.value, e.capacity_digits)} "
            f"| {fmt(r.forecast_ist.value, 2)} "
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
                "Linien: Commitment (Vergangenheit) bzw. Forecast PLAN (Zukunft), Velocity und "
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
                "Ø Scope Creep ({count} Sprints): {scope} des Commitments = {late} des Forecast "
                "PLAN · Kleinkram-Anteil: {small}",
                count=hint.samples,
                scope=pct(hint.average_scope_creep),
                late=pct(hint.average_late_share),
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
    # nur Produkte mit mindestens einem Wert (wie in der Weboberfläche)
    rows = [b for b in balance(fc, fc.history(history)) if b.sprints]
    if rows:
        with_missing = any(b.missing for b in rows)
        header = t("| Produkt | Sprints | Σ Standard | Σ Erledigt | Saldo ({unit}) |", unit=unit)
        lines += [
            "",
            t("**Saldo** (Σ Erledigt − Σ Standard, letzte {count} Sprints)", count=history),
            "",
            header + (f" {t('ohne Wert')} |" if with_missing else ""),
            "|---|---|---|---|---|" + ("---|" if with_missing else ""),
        ]
        lines += [
            f"| {b.product.name} | {b.sprints} | {fmt(b.standard, 2)} | {fmt(b.done, 2)} "
            f"| {fmt(b.difference, 2)} |" + (f" {b.missing} |" if with_missing else "")
            for b in rows
        ]
    return lines
