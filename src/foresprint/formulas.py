# SPDX-License-Identifier: EUPL-1.2
"""Calculation path per sprint: formula and plugged-in numbers for every computed figure.

Mirrors the logic of engine.py and capacity.py so that every number in the UI and the
report can be traced. Without Streamlit, so it is testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from foresprint.capacity import sprint_capacity
from foresprint.engine import CapacitySource, Metric, PlanSource, parse_trend_mode
from foresprint.forecast import Forecast, TimelineEntry
from foresprint.git import md_code
from foresprint.i18n import is_english, t
from foresprint.model import TrendMode
from foresprint.report import (
    absence_derived_hint,
    absence_derived_note,
    fmt,
    fmt_capacity,
    pct,
    sprint_text,
)


@dataclass(frozen=True)
class Step:
    # Fixed key (e.g. "plan"), independent of the language.
    key: str
    name: str
    formula: str
    calculation: str

    def text(self) -> str:
        """For tooltips: formula and calculation on two lines."""
        return f"{self.formula}\n\n{self.calculation}"


def fte_change_note(names: list[str]) -> str:
    """Note on the approximation for an FTE change within the sprint (A7)."""
    return t(
        (
            "≈ Approximation: with an FTE change within the sprint, absences are weighted with "
            "the mean FTE ({names})."
        ),
        names=", ".join(names),
    )


def _n(value: float | None, digits: int = 2) -> str:
    return fmt(value, digits)


def _g(value: float) -> str:
    """Short, with the decimal separator of the language: 0.5 → "0,5" (German), 3.0 → "3"."""
    text = f"{value:g}"
    return text if fmt(0.5) == "0.5" else text.replace(".", ",")


def _exact(value: float | None, digits: int = 4) -> str:
    """Up to ``digits`` decimal places without superfluous zeros: 30,4375 · 30 instead of 30,0.

    For equations: they must show the number actually used in the calculation, otherwise the
    recalculation does not add up (the capacity is used unrounded and only rounded for display,
    see :func:`foresprint.report.fmt_capacity`; the trend is likewise used unrounded).
    Zeros are only removed after the decimal separator: 100 stays 100."""
    text = fmt(value, digits)
    decimal = "." if is_english() else ","
    if decimal in text:
        text = text.rstrip("0").rstrip(decimal)
    return "0" if text == "-0" else text


# General formulas, e.g. for column headers (displayed with general()).
GENERAL: dict[str, str] = {
    "capacity": (
        "Capacity = Σ people (working days − holidays − absences) × FTE − Scrum "
        "events deduction; frozen after the review; unknown absences estimated "
        "from the history (without history, no deduction); trend only without a "
        "people list"
    ),
    "normalized_velocity": "norm. velocity = velocity / capacity × reference capacity",
    "average": "Ø norm. velocity = mean(norm. velocity of the last sprints in the window)",
    "trend": "norm. velocity trend = extrapolation(Ø norm. velocity) according to trend mode",
    "plan": "Forecast PLAN = rounded down(norm. velocity trend / reference capacity × capacity)",
    "roadmap": "Plannable = Forecast PLAN × plannable share",
    "small_stuff": "Small stuff = Forecast PLAN − plannable",
    "fulfillment": "Fulfillment = velocity / commitment",
    "scope_creep": "Scope creep = added later / commitment",
    "focus_factor": "Focus factor = velocity / capacity",
    "delta": "Planning delta = Forecast PLAN − (carry-over + backlog − corrections)",
    "standard": (
        "Standard = available × share of the product (without fixed share: rest / "
        "number of these products)"
    ),
    "balance": "Balance = Σ done − Σ standard",
}


def general(key: str) -> str:
    return t(GENERAL[key])


def capacity_step(fc: Forecast, e: TimelineEntry, code: bool = False, note: bool = True) -> Step:
    """``code=True`` sets sprint IDs as code (Markdown, e.g. tooltips); ``note=False``
    omits the note on the uncertain absence rate (the command line shows it separately)."""
    r = e.result
    source = r.plan_capacity_source
    team = fc.data.team
    name = t("Capacity")
    if source is CapacitySource.RECORDED:
        return Step(
            "capacity",
            name,
            t("Recorded in the sprint file (frozen at the review)"),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.PEOPLE:
        b = sprint_capacity(team, fc.data.people, e.sprint)
        parts = " + ".join(
            f"{md_code(p.person.name) if code else p.person.name} "
            f"({p.workdays} − {p.holidays} − {_g(p.absence_days)}) × "
            f"{_g(round(p.mean_fte, 2))}"
            for p in b.people
        )
        minus = ""
        if b.overhead_days_part:
            minus += f" − {_n(b.overhead_days_part)} ({t('Scrum events PT')})"
        if b.overhead_share_part:
            minus += f" − {_n(b.overhead_share_part)} ({pct(team.capacity.overhead_share)})"
        calculation = t(
            "{parts} = {gross}{minus} → {capacity} PT (rounded)",
            parts=parts,
            gross=_n(b.gross),
            minus=minus,
            capacity=fmt_capacity(b.capacity, b.rounding),
        )
        if b.approximated:
            calculation += " · " + fte_change_note(
                [md_code(p.person.name) if code else p.person.name for p in b.approximated]
            )
        return Step("capacity", name, general("capacity"), calculation)
    if source is CapacitySource.TREND:
        return Step(
            "capacity",
            name,
            t("No people list → capacity trend (extrapolated like the norm. velocity)"),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.CALENDAR:
        return Step(
            "capacity",
            name,
            t(
                "Absences unknown and no history yet → capacity from the people list and "
                "calendar (holidays, sprint length) without deduction for absences"
            ),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.EXPECTED:
        return Step(
            "capacity",
            name,
            t(
                "No absences confirmed → capacity from the people list with the announced "
                "absences from the PO pre-planning"
            ),
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    if source is CapacitySource.ESTIMATED:
        history = fc.absences
        used = history.sprints if history else []
        quota = history.rate if history and history.rate is not None else 0.0
        formula = t(
            (
                "Absences unknown → capacity from the people list and calendar, reduced by the "
                "average absences ({share}) of sprints {sprints}"
            ),
            share=pct(quota),
            sprints=", ".join(md_code(i) if code else sprint_text(i) for i in used),
        )
        # Short and without sprint IDs (the formula also serves as a tooltip); the list is on the
        # absences page, in the explanation and in the report.
        if note and (unsure := absence_derived_hint(history)):
            formula += ". " + unsure
        return Step(
            "capacity",
            name,
            formula,
            f"= {fmt_capacity(r.plan_capacity, e.capacity_digits)} PT",
        )
    return Step("capacity", name, t("cannot be determined"), "–")


def _index(fc: Forecast, e: TimelineEntry) -> int:
    return next(i for i, x in enumerate(fc.entries) if x.sprint.id == e.sprint.id)


def average_step(fc: Forecast, e: TimelineEntry) -> Step:
    i = _index(fc, e)
    window = fc.data.team.forecast.window
    values = [x.result.normalized_velocity.value for x in fc.entries[: i + 1]]
    present = [v for v in values if v is not None][-window:]  # sprints without a value do not count
    avg = e.result.normalized_velocity.average
    name = t("Ø norm. velocity")
    if avg is None:
        return Step("average", name, general("average"), t("– (sprint without its own value)"))
    return Step(
        "average",
        name,
        t(
            (
                "Ø norm. velocity = mean of the norm. velocity of the last {window} sprints "
                "with a value (sprints without a value do not count)"
            ),
            window=window,
        ),
        f"({' + '.join(_n(v) for v in present)}) / {len(present)} = {_n(avg)}",
    )


def trend_step(fc: Forecast, e: TimelineEntry) -> Step:
    """Calculation path of the normalized velocity trend, same as engine.trend."""
    i = _index(fc, e)
    mode = parse_trend_mode(fc.data.team.forecast.trend_mode)
    m: list[Metric] = [x.result.normalized_velocity for x in fc.entries]
    value = m[i].trend
    name = t("norm. velocity trend")

    def made(formula: str, calculation: str) -> Step:
        return Step("trend", name, formula, calculation)

    if m[i].average is not None:
        return made(
            t("norm. velocity trend = Ø norm. velocity – past sprint"), f"Ø = {_n(m[i].average)}"
        )
    if value is None:
        return made(general("trend"), t("– (not enough history)"))

    def avg(j: int) -> float | None:
        return m[j].average if j >= 0 else None

    def tr(j: int) -> float | None:
        return m[j].trend if j >= 0 else None

    def known(j: int) -> float | None:
        return avg(j) if avg(j) is not None else tr(j)

    if e.result.trend_fallback:
        return made(
            t(
                (
                    "Thin history: {mode} needs a second average, so norm. velocity trend = "
                    "value_prev (flat) applies"
                ),
                mode=mode.value,
            ),
            f"= {_n(known(i - 1))}",
        )
    if mode is TrendMode.FLAT:
        return made(t("norm. velocity trend = value_prev (flat)"), f"= {_n(known(i - 1))}")
    a1, a2 = avg(i - 1), avg(i - 2)
    if mode is TrendMode.CLASSIC and a1 is not None and a2 is not None:
        return made(
            t("norm. velocity trend = Ø_prev + (Ø_prev − Ø_prev2) (classic, 1st future sprint)"),
            f"{_n(a1)} + ({_n(a1)} − {_n(a2)}) = {_n(value)}",
        )
    if mode is TrendMode.CLASSIC and i >= 2 and tr(i - 2) is None:
        return made(
            t("norm. velocity trend = Ø[−2] / Ø[−3] × trend[−1] (classic, 2nd future sprint)"),
            f"{_n(avg(i - 2))} / {_n(avg(i - 3))} × {_n(tr(i - 1))} = {_n(value)}",
        )
    k1, k2 = known(i - 1), known(i - 2)
    return made(
        t("norm. velocity trend = value_prev + (value_prev − value_prev2) (linear)"),
        f"{_n(k1)} + ({_n(k1)} − {_n(k2)}) = {_n(value)}",
    )


def plain_explanation(fc: Forecast, e: TimelineEntry, note: bool = True) -> str:
    """Short plain-language explanation of how a sprint's forecast comes about, with the
    key numbers and sources. :func:`steps` provides the detailed formulas. ``note=False``
    omits the note on the uncertain absence rate (the command line shows it once separately,
    with the command instead of the web UI operation)."""
    team = fc.data.team
    f = team.forecast
    r = e.result
    unit = team.unit.value
    if r.plan is None:
        return t("No forecast can be calculated for this sprint yet (too little history).")
    if r.plan_source is PlanSource.ACTUAL:
        return t(
            "Past sprint: the commitment ({value} {unit}) counts, rounded down to {plan}.",
            value=_n(r.commitment.value),
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
            (
                "The team recently (sprints {sprints}) achieved an average of {trend} {unit}, "
                "converted to a reference capacity of {ref} PT (normalized velocity)."
            ),
            sprints=", ".join(basis),
            ref=_n(f.reference_capacity, 0),
            trend=_n(trend),
            unit=unit,
        ),
        t(
            (
                "{capacity} PT are available for {id} ({source}). That gives {trend} / {ref} × "
                "{exact} = {raw} {unit}, rounded down **{plan} {unit}**."
            ),
            id=e.sprint.id,
            capacity=fmt_capacity(r.plan_capacity, e.capacity_digits),
            exact=_exact(r.plan_capacity),
            source=t(r.plan_capacity_source.value) if r.plan_capacity_source else "–",
            trend=_exact(trend),  # equation: the trend that is actually used in the calculation
            ref=_n(f.reference_capacity, 0),
            raw=_n(raw, 3),
            unit=unit,
            plan=fmt(r.plan, f.rounding),
        ),
    ]
    if (
        note
        and r.plan_capacity_source is CapacitySource.ESTIMATED
        and (
            unsure := absence_derived_note(
                fc.absences, detailed=True, window=team.capacity.absence_history
            )
        )
    ):
        parts.append(unsure)
    if r.trend_fallback:
        parts.append(t("The history is thin: the last average applies, without extrapolation."))
    elif f.trend_mode is not TrendMode.FLAT:
        parts.append(
            t(
                (
                    "Trend mode {mode} extrapolates fluctuations of the last sprints – read "
                    "with caution."
                ),
                mode=f.trend_mode.value,
            )
        )
    return " ".join(parts)


@dataclass(frozen=True)
class Explanation:
    """:func:`plain_explanation` split for display: inputs, calculation, result, notes."""

    # Without values: only this sentence (past sprint, or no forecast possible yet).
    message: str = ""
    inputs: tuple[tuple[str, str], ...] = ()
    calculation: str = ""
    result_label: str = ""
    result: str = ""
    notes: tuple[str, ...] = ()


def structured_explanation(fc: Forecast, e: TimelineEntry, note: bool = True) -> Explanation:
    """The same facts as :func:`plain_explanation`, but as a short sequence (inputs →
    calculation → result, notes apart) instead of one paragraph."""
    team = fc.data.team
    f = team.forecast
    r = e.result
    unit = team.unit.value
    if r.plan is None or r.plan_source is PlanSource.ACTUAL:
        return Explanation(message=plain_explanation(fc, e, note=note))
    index = next(i for i, x in enumerate(fc.entries) if x.sprint.id == e.sprint.id)
    basis = [
        x.sprint.id for x in fc.entries[:index] if x.result.normalized_velocity.value is not None
    ][-f.window :]
    trend = r.normalized_velocity.trend
    raw = trend / f.reference_capacity * (r.plan_capacity or 0.0) if trend is not None else 0.0
    source = t(r.plan_capacity_source.value) if r.plan_capacity_source else "–"
    notes: list[str] = []
    if (
        note
        and r.plan_capacity_source is CapacitySource.ESTIMATED
        and (
            unsure := absence_derived_note(
                fc.absences, detailed=True, window=team.capacity.absence_history
            )
        )
    ):
        notes.append(unsure)
    if r.trend_fallback:
        notes.append(t("The history is thin: the last average applies, without extrapolation."))
    elif f.trend_mode is not TrendMode.FLAT:
        notes.append(
            t(
                (
                    "Trend mode {mode} extrapolates fluctuations of the last sprints – read "
                    "with caution."
                ),
                mode=f.trend_mode.value,
            )
        )
    return Explanation(
        inputs=(
            (t("Basis sprints"), ", ".join(md_code(i) for i in basis)),
            (
                t(
                    "Normalized velocity (reference capacity {ref} PT)",
                    ref=_n(f.reference_capacity, 0),
                ),
                f"{_n(trend)} {unit}",
            ),
            (
                t("Available in {id}", id=md_code(e.sprint.id)),
                f"{fmt_capacity(r.plan_capacity, e.capacity_digits)} PT ({source})",
            ),
        ),
        calculation=(
            f"{_exact(trend)} / {_n(f.reference_capacity, 0)} × {_exact(r.plan_capacity)} "
            f"= {_n(raw, 3)} {unit}"
        ),
        result_label=t("Forecast PLAN (rounded down)"),
        result=f"{fmt(r.plan, f.rounding)} {unit}",
        notes=tuple(notes),
    )


def steps(fc: Forecast, e: TimelineEntry, code: bool = False, note: bool = True) -> list[Step]:
    """All calculation steps of a sprint in reading order (``code`` and ``note`` as in
    :func:`capacity_step`)."""
    team = fc.data.team
    f = team.forecast
    r = e.result
    unit = team.unit.value
    ref = f.reference_capacity
    result = [capacity_step(fc, e, code, note)]
    if r.velocity.value is not None:
        result.append(
            Step(
                "normalized_velocity",
                t("norm. velocity"),
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
                    (
                        "Forecast PLAN = rounded down to {digits} digit(s): (norm. velocity "
                        "trend / reference capacity × capacity)"
                    ),
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
                t("Forecast PLAN = rounded down(commitment) – past sprint"),
                f"{_n(r.commitment.value)} → {fmt(r.plan, f.rounding)} {unit}",
            )
        )
    if r.plan is not None:
        result += [
            Step(
                "roadmap",
                t("Plannable"),
                general("roadmap"),
                f"{fmt(r.plan, f.rounding)} × {pct(f.roadmap_share)} = {_n(r.roadmap)}",
            ),
            Step(
                "small_stuff",
                t("Small items"),
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
                f"{_n(r.velocity.value)} / {_n(r.commitment.value)} = {pct(r.fulfillment.value)}",
            )
        )
    if r.planning_total is not None and e.sprint.planning is not None:
        p = e.sprint.planning
        corr = " − ".join(_n(c) for c in p.corrections) if p.corrections else "0"
        result.append(
            Step(
                "delta",
                t("Planning delta"),
                general("delta"),
                f"{fmt(r.plan, f.rounding)} − ({_n(p.carryover)} + {_n(p.backlog)} − {corr}) = "
                f"{_n(r.planning_delta)}",
            )
        )
    return result


def step(fc: Forecast, e: TimelineEntry, key: str, code: bool = False) -> Step | None:
    """One calculation step by key (capacity, trend, plan, roadmap, small_stuff …)."""
    return next((s for s in steps(fc, e, code) if s.key == key), None)
