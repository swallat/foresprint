# SPDX-License-Identifier: EUPL-1.2
"""Calculation engine: velocity, capacity and forecast calculation per sprint.

Metrics (per sprint):
    Commitment, Velocity, capacity, Scope Creep   → inputs
    Normalized velocity = Velocity / capacity × reference capacity
    Fulfillment         = Velocity / Commitment
    Ø (rolling)         = average over ``window`` sprints per metric
    Trend               = projection of the average into the future
    Forecast PLAN       = rounded down(norm. velocity trend / reference capacity × capacity)
    Plannable / small items = Forecast PLAN × plannable share (``roadmap_share``) / remainder
    Planning delta      = Forecast PLAN − (carryover + backlog − corrections)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from sprintforecast.model import ForecastSettings, Planning, TrendMode

type Series = list[float | None]

_EPS = 1e-9


def round_down(value: float, digits: int) -> float:
    """Truncate toward zero (with tolerance for floating-point errors)."""
    factor = 10**digits
    return math.copysign(math.floor(abs(value) * factor + _EPS) / factor, value)


def round_half_up(value: float, digits: int) -> float:
    """Round half up (.5 rounds up, tolerant of floating-point errors); no directional bias."""
    factor = 10**digits
    return math.copysign(math.floor(abs(value) * factor + 0.5 + _EPS) / factor, value)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


# New teams: with this many sprints with a value there is already an average and thus a
# forecast, even if the window is not full yet ("thin history", see thin_history).
MIN_THIN_HISTORY = 3


def thin_history(values: Series, window: int) -> bool:
    """Too few values for a full window, but enough for an initial forecast."""
    count = sum(1 for v in values if v is not None)
    return MIN_THIN_HISTORY <= count < window


def rolling_average(values: Series, window: int) -> Series:
    """Rolling average over the last ``window`` sprints **with a value**.

    Rule for gaps: sprints without a value do not count, the window reaches back further
    accordingly (always exactly ``window`` values are averaged, never fewer). The average is
    only defined if the sprint itself has a value and enough values precede it.

    Exception for new teams: if there are fewer than ``window`` values in total but at least
    ``MIN_THIN_HISTORY``, each sprint from the third value on averages over all values so far
    (thin history).
    """
    thin = thin_history(values, window)
    result: Series = []
    present: list[float] = []
    for value in values:
        if value is None:
            result.append(None)
            continue
        present.append(value)
        if len(present) >= window:
            result.append(sum(present[-window:]) / window)
        elif thin and len(present) >= MIN_THIN_HISTORY:
            result.append(sum(present) / len(present))
        else:
            result.append(None)
    return result


def gaps_in_window(values: Series, window: int) -> int:
    """Number of sprints without a value that the window of the last average skips over."""
    last = max((i for i, v in enumerate(values) if v is not None), default=None)
    if last is None:
        return 0
    seen = 0
    for i in range(last, -1, -1):
        if values[i] is not None:
            seen += 1
            if seen == window:
                return sum(1 for v in values[i:last] if v is None)
    return 0


def parse_trend_mode(mode: TrendMode | str) -> TrendMode:
    """Converts a string to ``TrendMode``; an unknown value is an error (no silent
    ``linear``)."""
    try:
        return TrendMode(mode)
    except ValueError:
        allowed = ", ".join(m.value for m in TrendMode)
        raise ValueError(f"Unbekannter Trend-Modus {mode!r} (erlaubt: {allowed})") from None


def _trend(average: Series, mode: TrendMode | str) -> tuple[Series, list[bool]]:
    """Trend, and per position whether it fell back to ``flat`` instead of the chosen mode
    (too little history to project)."""
    mode = parse_trend_mode(mode)
    result: Series = [None] * len(average)
    fallback = [False] * len(average)

    def avg(j: int) -> float | None:
        return average[j] if j >= 0 else None

    def tr(j: int) -> float | None:
        return result[j] if j >= 0 else None

    def known(j: int) -> float | None:
        return avg(j) if avg(j) is not None else tr(j)

    for i in range(len(average)):
        if average[i] is not None:
            continue
        value: float | None
        if mode is TrendMode.FLAT:
            value = known(i - 1)
        else:
            a1, a2 = avg(i - 1), avg(i - 2)
            if mode is TrendMode.CLASSIC and a1 is not None:
                # =(Ø[i-1] − Ø[i-2]) + Ø[i-1]
                value = None if a2 is None else a1 + (a1 - a2)
            elif mode is TrendMode.CLASSIC and i >= 2 and tr(i - 2) is None:
                # =Ø[i-2] / Ø[i-3] × Trend[i-1]
                ratio = _div(avg(i - 2), avg(i - 3))
                t1 = tr(i - 1)
                value = None if ratio is None or t1 is None else ratio * t1
            else:
                k1, k2 = known(i - 1), known(i - 2)
                value = None if k1 is None or k2 is None else k1 + (k1 - k2)
            if value is None and (value := known(i - 1)) is not None:
                fallback[i] = True  # thin history: carry the last average forward
            elif i > 0 and fallback[i - 1]:
                fallback[i] = True  # builds on a value that was already "flat"
        # Quantities, capacity and shares are never negative; a projection below zero (noise)
        # is clamped to zero.
        result[i] = None if value is None else max(value, 0.0)
    return result, fallback


def trend(average: Series, mode: TrendMode | str) -> Series:
    """Projects the rolling average forward where it is missing (future).

    If the history is not enough for ``classic``/``linear`` (e.g. exactly ``window`` sprints),
    ``flat`` applies. The result is never negative."""
    return _trend(average, mode)[0]


class CapacitySource(StrEnum):
    RECORDED = "recorded"
    PEOPLE = "people list"
    TREND = "Trend"
    # People list and calendar; absences unknown and no history, hence no deduction.
    CALENDAR = "Calendar, absences unknown"
    ESTIMATED = "expected absences"
    EXPECTED = "announced absences"


# Sources without known absences and without history: the capacity is only an estimate.
UNSURE_SOURCES = (CapacitySource.TREND, CapacitySource.CALENDAR)


class PlanSource(StrEnum):
    ACTUAL = "IST"
    FORECAST = "Projection"


@dataclass
class SprintInput:
    id: str
    capacity: float | None
    capacity_source: CapacitySource | None
    commitment: float | None
    velocity: float | None
    scope_creep: float | None
    planning: Planning | None = None


@dataclass
class Metric:
    value: float | None
    average: float | None
    trend: float | None


@dataclass
class SprintResult:
    input: SprintInput
    commitment: Metric
    velocity: Metric
    capacity: Metric
    normalized_velocity: Metric
    fulfillment: Metric
    scope_creep: Metric
    # Capacity the Forecast PLAN was calculated with (recorded, from people and calendar, or
    # trend).
    plan_capacity: float | None
    plan_capacity_source: CapacitySource | None
    plan: float | None
    plan_source: PlanSource | None
    # Sample behind the normalized velocity trend: number of all values so far; and whether
    # ``flat`` was used instead of the chosen trend mode because of thin history.
    samples: int
    trend_fallback: bool
    roadmap: float | None
    small_stuff: float | None
    planning_total: float | None
    planning_delta: float | None

    @property
    def id(self) -> str:
        return self.input.id


def _metric_series(values: Series, settings: ForecastSettings) -> tuple[list[Metric], list[bool]]:
    averages = rolling_average(values, settings.window)
    if thin_history(values, settings.window):
        # Thin history: only the average, no projection of an increase.
        trends, _ = _trend(averages, TrendMode.FLAT)
        fallback = [parse_trend_mode(settings.trend_mode) is not TrendMode.FLAT] * len(values)
    else:
        trends, fallback = _trend(averages, settings.trend_mode)
    metrics = [Metric(v, a, t) for v, a, t in zip(values, averages, trends, strict=True)]
    return metrics, fallback


def compute(inputs: list[SprintInput], settings: ForecastSettings) -> list[SprintResult]:
    ref = settings.reference_capacity
    capacity = [s.capacity for s in inputs]
    velocity = [s.velocity for s in inputs]
    commitment = [s.commitment for s in inputs]
    normalized = [
        None if v is None or c in (None, 0) else v / c * ref
        for v, c in zip(velocity, capacity, strict=True)
    ]
    fulfillment = [_div(v, f) for v, f in zip(velocity, commitment, strict=True)]

    m_fist, _ = _metric_series(commitment, settings)
    m_vel, _ = _metric_series(velocity, settings)
    m_cap, _ = _metric_series(capacity, settings)
    m_norm, norm_fallback = _metric_series(normalized, settings)
    m_ful, _ = _metric_series(fulfillment, settings)
    m_scope, _ = _metric_series([s.scope_creep for s in inputs], settings)

    results = []
    for i, s in enumerate(inputs):
        if s.capacity is not None:
            plan_cap, plan_cap_source = s.capacity, s.capacity_source
        else:
            plan_cap, plan_cap_source = m_cap[i].trend, CapacitySource.TREND
            if plan_cap is None:
                plan_cap_source = None

        n_trend = m_norm[i].trend
        if n_trend is not None and plan_cap is not None:
            plan = round_down(n_trend / ref * plan_cap, settings.rounding)
            plan_source = PlanSource.FORECAST
            plan = max(plan, 0.0)
        elif s.commitment is not None:
            # The fallback to Commitment is also rounded down.
            plan = round_down(s.commitment, settings.rounding)
            plan_source = PlanSource.ACTUAL
        else:
            plan, plan_source = None, None

        roadmap = None if plan is None else plan * settings.roadmap_share
        planning_total = s.planning.total if s.planning else None
        results.append(
            SprintResult(
                input=s,
                commitment=m_fist[i],
                velocity=m_vel[i],
                capacity=m_cap[i],
                normalized_velocity=m_norm[i],
                fulfillment=m_ful[i],
                scope_creep=m_scope[i],
                plan_capacity=plan_cap,
                plan_capacity_source=plan_cap_source,
                plan=plan,
                plan_source=plan_source,
                samples=sum(1 for v in normalized[:i] if v is not None),
                trend_fallback=norm_fallback[i] and plan_source is PlanSource.FORECAST,
                roadmap=roadmap,
                small_stuff=None if plan is None else plan - roadmap,
                planning_total=planning_total,
                planning_delta=(
                    None if plan is None or planning_total is None else plan - planning_total
                ),
            )
        )
    return results
