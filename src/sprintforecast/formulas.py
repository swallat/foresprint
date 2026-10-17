# SPDX-License-Identifier: EUPL-1.2
"""Rechenweg je Sprint: Formel und eingesetzte Zahlen für jede berechnete Kennzahl.

Spiegelt die Logik aus engine.py und capacity.py, damit jede Zahl in Oberfläche und
Bericht nachvollziehbar ist. Ohne Streamlit, damit testbar.
"""

from __future__ import annotations

from dataclasses import dataclass

from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource, Metric, PlanSource, parse_trend_mode
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import is_english, t
from sprintforecast.model import TrendMode
from sprintforecast.report import fmt, fmt_capacity, pct


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


def fte_change_note(names: list[str]) -> str:
    """Hinweis auf die Näherung bei FTE-Wechsel im Sprint (A7)."""
    return t(
        "≈ Näherung: Bei FTE-Wechsel im Sprint werden Fehltage mit der mittleren FTE gewichtet "
        "({names}).",
        names=", ".join(names),
    )


def _n(value: float | None, digits: int = 2) -> str:
    return fmt(value, digits)


def _g(value: float) -> str:
    """Kurz, mit dem Dezimalzeichen der Sprache: 0.5 → „0,5“, 3.0 → „3“."""
    text = f"{value:g}"
    return text if fmt(0.5) == "0.5" else text.replace(".", ",")


def _exact(value: float | None, digits: int = 4) -> str:
    """Bis zu ``digits`` Nachkommastellen ohne überflüssige Nullen: 30,4375 · 30 statt 30,0.

    Für Gleichungen: Dort muss die Zahl stehen, mit der wirklich gerechnet wird, sonst stimmt die
    Nachrechnung nicht (die Kapazität wird ungerundet verwendet und nur für die Anzeige gerundet,
    siehe :func:`sprintforecast.report.fmt_capacity`; der Trend wird ebenfalls ungerundet
    verwendet). Nullen werden nur hinter dem Dezimalzeichen entfernt: 100 bleibt 100."""
    text = fmt(value, digits)
    decimal = "." if is_english() else ","
    if decimal in text:
        text = text.rstrip("0").rstrip(decimal)
    return "0" if text == "-0" else text


# Allgemeine Formeln – z. B. für Spaltenköpfe (Anzeige mit general()).
GENERAL: dict[str, str] = {
    "capacity": "Kapazität = Σ Personen (Arbeitstage − Feiertage − Fehltage) × FTE − Abzug Scrum-Termine; "  # noqa: E501
    "nach dem Review eingefroren; unbekannte Fehltage nach der Historie geschätzt; "
    "Trend nur ohne Personenliste",
    "normalized_velocity": "n. Velocity = Velocity / Kapazität × Referenzkapazität",
    "average": "Ø n. Velocity = Mittel(n. Velocity der letzten Sprints im Fenster)",
    "trend": "n. Velocity-Trend = Fortschreibung(Ø n. Velocity) gemäß Trend-Modus",
    "plan": "Forecast PLAN = abgerundet(n. Velocity-Trend / Referenzkapazität × Kapazität)",
    "roadmap": "Roadmap = Forecast PLAN × Roadmap-Anteil",
    "small_stuff": "Kleinkram = Forecast PLAN − Roadmap",
    "fulfillment": "Fulfillment = Velocity / Commitment",
    "scope_creep": "Scope Creep = nachträglich hinzugekommen / Commitment",
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
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
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
        calculation = t(
            "{parts} = {gross}{minus} → {capacity} PT (gerundet)",
            parts=parts,
            gross=_n(b.gross),
            minus=minus,
            capacity=fmt_capacity(b.capacity, b.rounding),
        )
        if b.approximated:
            calculation += " · " + fte_change_note([p.person.name for p in b.approximated])
        return Step("capacity", name, general("capacity"), calculation)
    if source is CapacitySource.TREND:
        return Step(
            "capacity",
            name,
            t("Keine Personenliste → Trend der Kapazität (wie n. Velocity fortgeschrieben)"),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.CALENDAR:
        return Step(
            "capacity",
            name,
            t(
                "Fehltage unbekannt und noch keine Historie → Kapazität laut Personenliste und "
                "Kalender (Feiertage, Sprintlänge) ohne Abzug für Fehltage"
            ),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.EXPECTED:
        return Step(
            "capacity",
            name,
            t(
                "Keine Fehltage bestätigt → Kapazität laut Personenliste mit den angekündigten "
                "Fehltagen aus der PO-Vorplanung"
            ),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.ESTIMATED:
        history = fc.absences
        used = history.sprints if history else []
        quota = history.rate if history and history.rate is not None else 0.0
        return Step(
            "capacity",
            name,
            t(
                "Fehltage unbekannt → Kapazität laut Personenliste und Kalender, gemindert um "
                "die durchschnittlichen Fehltage ({share}) der Sprints {sprints}",
                share=pct(quota),
                sprints=", ".join(used),
            ),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    return Step("capacity", name, t("nicht bestimmbar"), "–")


def _index(fc: Forecast, e: TimelineEntry) -> int:
    return next(i for i, x in enumerate(fc.entries) if x.sprint.id == e.sprint.id)


def average_step(fc: Forecast, e: TimelineEntry) -> Step:
    i = _index(fc, e)
    window = fc.data.team.forecast.window
    values = [x.result.normalized_velocity.value for x in fc.entries[: i + 1]]
    present = [v for v in values if v is not None][-window:]  # Sprints ohne Wert zählen nicht
    avg = e.result.normalized_velocity.average
    name = t("Ø n. Velocity")
    if avg is None:
        return Step("average", name, general("average"), t("– (Sprint ohne eigenen Wert)"))
    return Step(
        "average",
        name,
        t(
            "Ø n. Velocity = Mittel der n. Velocity der letzten {window} Sprints mit Wert (Sprints ohne Wert zählen nicht)",  # noqa: E501
            window=window,
        ),
        f"({' + '.join(_n(v) for v in present)}) / {len(present)} = {_n(avg)}",
    )


def trend_step(fc: Forecast, e: TimelineEntry) -> Step:
    """Rechenweg des n. Velocity-Trends – wie engine.trend."""
    i = _index(fc, e)
    mode = parse_trend_mode(fc.data.team.forecast.trend_mode)
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

    if e.result.trend_fallback:
        return made(
            t(
                "Historie dünn: für {mode} fehlt ein zweiter Durchschnitt, daher gilt "
                "n. Velocity-Trend = Wert_vorher (flat)",
                mode=mode.value,
            ),
            f"= {_n(known(i - 1))}",
        )
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


def plain_explanation(fc: Forecast, e: TimelineEntry) -> str:
    """Kurze Erklärung in Alltagssprache, wie die Prognose eines Sprints entsteht – mit den
    wichtigsten Zahlen und Quellen. Die ausführlichen Formeln liefert :func:`steps`."""
    team = fc.data.team
    f = team.forecast
    r = e.result
    unit = team.unit.value
    if r.plan is None:
        return t("Für diesen Sprint ist noch keine Prognose berechenbar (zu wenig Historie).")
    if r.plan_source is PlanSource.ACTUAL:
        return t(
            "Vergangener Sprint: Es zählt das Commitment ({value} {unit}), abgerundet auf {plan}.",
            value=_n(r.forecast_ist.value),
            unit=unit,
            plan=fmt(r.plan, f.rounding),
        )
    index = next(i for i, x in enumerate(fc.entries) if x.sprint.id == e.sprint.id)
    basis = [
        x.sprint.id for x in fc.entries[:index] if x.result.normalized_velocity.value is not None
    ][-f.window :]
    trend = r.normalized_velocity.trend
    raw = trend / f.reference_capacity * (r.plan_capacity or 0.0) if trend is not None else 0.0
    parts = [
        t(
            "Das Team hat zuletzt (Sprints {sprints}) umgerechnet auf eine Referenzkapazität von "
            "{ref} PT durchschnittlich {trend} {unit} geschafft (normierte Velocity).",
            sprints=", ".join(basis),
            ref=_n(f.reference_capacity, 0),
            trend=_n(trend),
            unit=unit,
        ),
        t(
            "Für {id} stehen {capacity} PT zur Verfügung ({source}). Das ergibt {trend} / {ref} "
            "× {exact} = {raw} {unit}, abgerundet **{plan} {unit}**.",
            id=e.sprint.id,
            capacity=fmt_capacity(r.plan_capacity, e.capacity_digits),
            exact=_exact(r.plan_capacity),
            source=t(r.plan_capacity_source.value) if r.plan_capacity_source else "–",
            trend=_exact(trend),  # Gleichung: der Trend, mit dem gerechnet wird
            ref=_n(f.reference_capacity, 0),
            raw=_n(raw, 3),
            unit=unit,
            plan=fmt(r.plan, f.rounding),
        ),
    ]
    if r.trend_fallback:
        parts.append(
            t("Die Historie ist dünn: Es gilt der letzte Durchschnitt, ohne Fortschreibung.")
        )
    elif f.trend_mode is not TrendMode.FLAT:
        parts.append(
            t(
                "Der Trend-Modus {mode} schreibt Schwankungen der letzten Sprints fort – "
                "vorsichtig lesen.",
                mode=f.trend_mode.value,
            )
        )
    return " ".join(parts)


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
                f"{_n(r.velocity.value)} / {_exact(r.capacity.value)} × {_n(ref, 0)} = "
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
                f"{_exact(r.normalized_velocity.trend)} / {_n(ref, 0)} × "
                f"{_exact(r.plan_capacity)} = "
                f"{_n(r.normalized_velocity.trend / ref * r.plan_capacity, 3)} → "
                f"{fmt(r.plan, f.rounding)} {unit}",
            )
        )
    elif r.plan_source is PlanSource.ACTUAL:
        result.append(
            Step(
                "plan",
                "Forecast PLAN",
                t("Forecast PLAN = abgerundet(Commitment) – vergangener Sprint"),
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
