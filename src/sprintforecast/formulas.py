# SPDX-License-Identifier: EUPL-1.2
"""Rechenweg je Sprint: Formel und eingesetzte Zahlen für jede berechnete Kennzahl.

Spiegelt die Logik aus engine.py und capacity.py, damit jede Zahl in Oberfläche und
Bericht nachvollziehbar ist. Ohne Streamlit, damit testbar.
"""

from __future__ import annotations

from dataclasses import dataclass

from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource, Metric, PlanSource
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import t
from sprintforecast.model import TrendMode
from sprintforecast.report import fmt, pct


@dataclass(frozen=True)
class Step:
    # Fester Schlüssel (z. B. "plan"), unabhängig von der Sprache.
    key: str
    name: str
    formula: str
    calculation: str

    def text(self) -> str:
        """Für Tooltips: Formel und Rechnung in zwei Zeilen."""
        return f"{self.formula}\n\n{self.calculation}"


def _n(value: float | None, digits: int = 2) -> str:
    return fmt(value, digits)


def _g(value: float) -> str:
    """Kurz, mit dem Dezimalzeichen der Sprache: 0.5 → „0,5“, 3.0 → „3“."""
    text = f"{value:g}"
    return text if fmt(0.5) == "0.5" else text.replace(".", ",")


# Allgemeine Formeln – z. B. für Spaltenköpfe (Anzeige mit general()).
GENERAL: dict[str, str] = {
    "capacity": "Kapazität = Σ Personen (Arbeitstage − Feiertage − Fehltage) × FTE − Abzug Scrum-Termine; "  # noqa: E501
    "nach dem Review eingefroren; ohne Fehltage: Trend",
    "normalized_velocity": "n. Velocity = Velocity / Kapazität × Referenzkapazität",
    "average": "Ø n. Velocity = Mittel(n. Velocity der letzten Sprints im Fenster)",
    "trend": "n. Velocity-Trend = Fortschreibung(Ø n. Velocity) gemäß Trend-Modus",
    "plan": "Forecast PLAN = abgerundet(n. Velocity-Trend / Referenzkapazität × Kapazität)",
    "roadmap": "Roadmap = Forecast PLAN × Roadmap-Anteil",
    "small_stuff": "Kleinkram = Forecast PLAN − Roadmap",
    "fulfillment": "Fulfillment = Velocity / Forecast IST",
    "scope_creep": "Scope Creep = nachträglich hinzugekommen / Forecast IST",
    "focus_factor": "Fokusfaktor = Velocity / Kapazität",
    "delta": "Planning-Delta = Forecast PLAN − (Überkipper + Backlog − Korrekturen)",
    "standard": "Standard = verfügbar × Anteil des Produkts (ohne festen Anteil: Rest / Anzahl dieser Produkte)",  # noqa: E501
    "balance": "Saldo = Σ Erledigt − Σ Standard",
}


def general(key: str) -> str:
    return t(GENERAL[key])


def capacity_step(fc: Forecast, e: TimelineEntry) -> Step:
    r = e.result
    source = r.plan_capacity_source
    team = fc.data.team
    name = t("Kapazität")
    if source is CapacitySource.RECORDED:
        return Step(
            "capacity",
            name,
            t("In der Sprintdatei erfasst (beim Review eingefroren)"),
            f"= {_n(r.plan_capacity, 1)} PT",
        )
    if source is CapacitySource.PEOPLE:
        b = sprint_capacity(team, fc.data.people, e.sprint)
        parts = " + ".join(
            f"{p.person.name} ({p.workdays} − {p.holidays} − {_g(p.absence_days)}) × "
            f"{_g(round(p.mean_fte, 2))}"
            for p in b.people
        )
        minus = ""
        if b.overhead_days_part:
            minus += f" − {_n(b.overhead_days_part)} ({t('Scrum-Termine PT')})"
        if b.overhead_share_part:
            minus += f" − {_n(b.overhead_share_part)} ({pct(team.capacity.overhead_share)})"
        return Step(
            "capacity",
            name,
            general("capacity"),
            t(
                "{parts} = {gross}{minus} → {capacity} PT (abgerundet)",
                parts=parts,
                gross=_n(b.gross),
                minus=minus,
                capacity=_n(b.capacity, 1),
            ),
        )
    if source is CapacitySource.TREND:
        return Step(
            "capacity",
            name,
            t("Keine Fehltage erfasst → Trend der Kapazität (wie n. Velocity fortgeschrieben)"),
            f"= {_n(r.plan_capacity, 1)} PT",
        )
    if source is CapacitySource.ESTIMATED:
        rate = fc.data.team.capacity.absence_history
        return Step(
            "capacity",
            name,
            t(
                "Keine Fehltage erfasst → Kapazität laut Personenliste, gemindert um die "
                "durchschnittlichen Fehltage der letzten {count} Sprints",
                count=rate,
            ),
            f"= {_n(r.plan_capacity, 1)} PT",
        )
    return Step("capacity", name, t("nicht bestimmbar"), "–")


def _index(fc: Forecast, e: TimelineEntry) -> int:
    return next(i for i, x in enumerate(fc.entries) if x.sprint.id == e.sprint.id)


def average_step(fc: Forecast, e: TimelineEntry) -> Step:
    i = _index(fc, e)
    window = fc.data.team.forecast.window
    values = [
        x.result.normalized_velocity.value for x in fc.entries[max(0, i - window + 1) : i + 1]
    ]
    present = [v for v in values if v is not None]
    avg = e.result.normalized_velocity.average
    name = t("Ø n. Velocity")
    if avg is None:
        return Step("average", name, general("average"), t("– (Sprint ohne eigenen Wert)"))
    return Step(
        "average",
        name,
        t(
            "Ø n. Velocity = Mittel der n. Velocity der letzten {window} Sprints (fehlende Werte zählen nicht)",  # noqa: E501
            window=window,
        ),
        f"({' + '.join(_n(v) for v in present)}) / {len(present)} = {_n(avg)}",
    )


def trend_step(fc: Forecast, e: TimelineEntry) -> Step:
    """Rechenweg des n. Velocity-Trends – wie engine.trend."""
    i = _index(fc, e)
    mode = fc.data.team.forecast.trend_mode
    m: list[Metric] = [x.result.normalized_velocity for x in fc.entries]
    value = m[i].trend
    name = t("n. Velocity-Trend")

    def made(formula: str, calculation: str) -> Step:
        return Step("trend", name, formula, calculation)

    if m[i].average is not None:
        return made(
            t("n. Velocity-Trend = Ø n. Velocity – vergangener Sprint"), f"Ø = {_n(m[i].average)}"
        )
    if value is None:
        return made(general("trend"), t("– (zu wenig Historie)"))

    def avg(j: int) -> float | None:
        return m[j].average if j >= 0 else None

    def tr(j: int) -> float | None:
        return m[j].trend if j >= 0 else None

    def known(j: int) -> float | None:
        return avg(j) if avg(j) is not None else tr(j)

    if mode is TrendMode.FLAT:
        return made(t("n. Velocity-Trend = Wert_vorher (flat)"), f"= {_n(known(i - 1))}")
    a1, a2 = avg(i - 1), avg(i - 2)
    if mode is TrendMode.CLASSIC and a1 is not None and a2 is not None:
        return made(
            t(
                "n. Velocity-Trend = Ø_vorher + (Ø_vorher − Ø_vorvorher) (klassisch, 1. Zukunftssprint)"  # noqa: E501
            ),
            f"{_n(a1)} + ({_n(a1)} − {_n(a2)}) = {_n(value)}",
        )
    if mode is TrendMode.CLASSIC and i >= 2 and tr(i - 2) is None:
        return made(
            t("n. Velocity-Trend = Ø[−2] / Ø[−3] × Trend[−1] (klassisch, 2. Zukunftssprint)"),
            f"{_n(avg(i - 2))} / {_n(avg(i - 3))} × {_n(tr(i - 1))} = {_n(value)}",
        )
    k1, k2 = known(i - 1), known(i - 2)
    return made(
        t("n. Velocity-Trend = Wert_vorher + (Wert_vorher − Wert_vorvorher) (linear)"),
        f"{_n(k1)} + ({_n(k1)} − {_n(k2)}) = {_n(value)}",
    )


def steps(fc: Forecast, e: TimelineEntry) -> list[Step]:
    """Alle Rechenschritte eines Sprints in Lesereihenfolge."""
    team = fc.data.team
    f = team.forecast
    r = e.result
    unit = team.unit.value
    ref = f.reference_capacity
    result = [capacity_step(fc, e)]
    if r.velocity.value is not None:
        result.append(
            Step(
                "normalized_velocity",
                t("n. Velocity"),
                general("normalized_velocity"),
                f"{_n(r.velocity.value)} / {_n(r.capacity.value, 1)} × {_n(ref, 0)} = "
                f"{_n(r.normalized_velocity.value)}",
            )
        )
    if r.normalized_velocity.average is not None:
        result.append(average_step(fc, e))
    result.append(trend_step(fc, e))
    if r.plan_source is PlanSource.FORECAST:
        result.append(
            Step(
                "plan",
                "Forecast PLAN",
                t(
                    "Forecast PLAN = abgerundet auf {digits} Stelle(n): (n. Velocity-Trend / "
                    "Referenzkapazität × Kapazität)",
                    digits=f.rounding,
                ),
                f"{_n(r.normalized_velocity.trend)} / {_n(ref, 0)} × {_n(r.plan_capacity, 1)} = "
                f"{_n(r.normalized_velocity.trend / ref * r.plan_capacity, 3)} → "
                f"{fmt(r.plan, f.rounding)} {unit}",
            )
        )
    elif r.plan_source is PlanSource.ACTUAL:
        result.append(
            Step(
                "plan",
                "Forecast PLAN",
                t("Forecast PLAN = abgerundet(Forecast IST) – vergangener Sprint"),
                f"{_n(r.forecast_ist.value)} → {fmt(r.plan, f.rounding)} {unit}",
            )
        )
    if r.plan is not None:
        result += [
            Step(
                "roadmap",
                "Roadmap",
                general("roadmap"),
                f"{fmt(r.plan, f.rounding)} × {pct(f.roadmap_share)} = {_n(r.roadmap)}",
            ),
            Step(
                "small_stuff",
                t("Kleinkram"),
                general("small_stuff"),
                f"{fmt(r.plan, f.rounding)} − {_n(r.roadmap)} = {_n(r.small_stuff)}",
            ),
        ]
    if r.fulfillment.value is not None:
        result.append(
            Step(
                "fulfillment",
                "Fulfillment",
                general("fulfillment"),
                f"{_n(r.velocity.value)} / {_n(r.forecast_ist.value)} = {pct(r.fulfillment.value)}",
            )
        )
    if r.planning_total is not None and e.sprint.planning is not None:
        p = e.sprint.planning
        corr = " − ".join(_n(c) for c in p.corrections) if p.corrections else "0"
        result.append(
            Step(
                "delta",
                t("Planning-Delta"),
                general("delta"),
                f"{fmt(r.plan, f.rounding)} − ({_n(p.carryover)} + {_n(p.backlog)} − {corr}) = "
                f"{_n(r.planning_delta)}",
            )
        )
    return result


def step(fc: Forecast, e: TimelineEntry, key: str) -> Step | None:
    """Ein Rechenschritt nach Schlüssel (capacity, trend, plan, roadmap, small_stuff …)."""
    return next((s for s in steps(fc, e) if s.key == key), None)
