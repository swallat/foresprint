# SPDX-License-Identifier: EUPL-1.2
"""Rechenkern: Velocity-, Kapazitäts- und Prognoseberechnung je Sprint.

Kennzahlen (je Sprint):
    Forecast IST, Velocity, Kapazität, Scope Creep   → Eingaben
    Normierte Velocity  = Velocity / Kapazität × Referenzkapazität
    Fulfillment         = Velocity / Forecast IST
    Ø (gleitend)        = Durchschnitt über ``window`` Sprints je Kennzahl
    Trend               = Fortschreibung des Durchschnitts in die Zukunft
    Forecast PLAN       = abgerundet(n. Velocity-Trend / Referenzkapazität × Kapazität)
    Roadmap / Kleinkram = Forecast PLAN × Roadmap-Anteil / Rest
    Planning-Delta      = Forecast PLAN − (Überkipper + Backlog − Korrekturen)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from sprintforecast.model import ForecastSettings, Planning, TrendMode

type Series = list[float | None]

_EPS = 1e-9


def round_down(value: float, digits: int) -> float:
    """Richtung null abschneiden (mit Toleranz für Gleitkommafehler)."""
    factor = 10**digits
    return math.copysign(math.floor(abs(value) * factor + _EPS) / factor, value)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def rolling_average(values: Series, window: int) -> Series:
    """Gleitender Durchschnitt über ``window`` Sprints.

    Nur definiert, wenn der Wert des Sprints selbst vorhanden ist und davor genügend
    Sprints liegen. Fehlende Werte im Fenster werden ignoriert.
    """
    result: Series = []
    for i, value in enumerate(values):
        if value is None or i < window - 1:
            result.append(None)
            continue
        present = [v for v in values[i - window + 1 : i + 1] if v is not None]
        result.append(sum(present) / len(present))
    return result


def trend(average: Series, mode: TrendMode) -> Series:
    """Schreibt den gleitenden Durchschnitt dort fort, wo er fehlt (Zukunft)."""
    result: Series = [None] * len(average)

    def avg(j: int) -> float | None:
        return average[j] if j >= 0 else None

    def tr(j: int) -> float | None:
        return result[j] if j >= 0 else None

    def known(j: int) -> float | None:
        return avg(j) if avg(j) is not None else tr(j)

    for i in range(len(average)):
        if average[i] is not None:
            continue
        if mode is TrendMode.FLAT:
            result[i] = known(i - 1)
            continue
        a1, a2 = avg(i - 1), avg(i - 2)
        if mode is TrendMode.KLASSISCH and a1 is not None:
            # =(Ø[i-1] − Ø[i-2]) + Ø[i-1]
            result[i] = None if a2 is None else a1 + (a1 - a2)
        elif mode is TrendMode.KLASSISCH and i >= 2 and tr(i - 2) is None:
            # =Ø[i-2] / Ø[i-3] × Trend[i-1]
            ratio = _div(avg(i - 2), avg(i - 3))
            t1 = tr(i - 1)
            result[i] = None if ratio is None or t1 is None else ratio * t1
        else:
            k1, k2 = known(i - 1), known(i - 2)
            result[i] = None if k1 is None or k2 is None else k1 + (k1 - k2)
    return result


class CapacitySource(StrEnum):
    RECORDED = "erfasst"
    PEOPLE = "Personenliste"
    TREND = "Trend"


class PlanSource(StrEnum):
    ACTUAL = "IST"
    FORECAST = "Prognose"


@dataclass
class SprintInput:
    id: str
    capacity: float | None
    capacity_source: CapacitySource | None
    forecast_ist: float | None
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
    forecast_ist: Metric
    velocity: Metric
    capacity: Metric
    normalized_velocity: Metric
    fulfillment: Metric
    scope_creep: Metric
    # Kapazität, mit der Forecast PLAN gerechnet wurde (erfasst oder Trend).
    plan_capacity: float | None
    plan_capacity_source: CapacitySource | None
    plan: float | None
    plan_source: PlanSource | None
    roadmap: float | None
    small_stuff: float | None
    planning_total: float | None
    planning_delta: float | None

    @property
    def id(self) -> str:
        return self.input.id


def _metric_series(values: Series, settings: ForecastSettings) -> list[Metric]:
    averages = rolling_average(values, settings.window)
    trends = trend(averages, settings.trend_mode)
    return [Metric(v, a, t) for v, a, t in zip(values, averages, trends, strict=True)]


def compute(inputs: list[SprintInput], settings: ForecastSettings) -> list[SprintResult]:
    ref = settings.reference_capacity
    capacity = [s.capacity for s in inputs]
    velocity = [s.velocity for s in inputs]
    forecast_ist = [s.forecast_ist for s in inputs]
    normalized = [
        None if v is None or c in (None, 0) else v / c * ref
        for v, c in zip(velocity, capacity, strict=True)
    ]
    fulfillment = [_div(v, f) for v, f in zip(velocity, forecast_ist, strict=True)]

    m_fist = _metric_series(forecast_ist, settings)
    m_vel = _metric_series(velocity, settings)
    m_cap = _metric_series(capacity, settings)
    m_norm = _metric_series(normalized, settings)
    m_ful = _metric_series(fulfillment, settings)
    m_scope = _metric_series([s.scope_creep for s in inputs], settings)

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
        elif s.forecast_ist is not None:
            # Auch der Rückgriff auf Forecast IST wird abgerundet.
            plan = round_down(s.forecast_ist, settings.rounding)
            plan_source = PlanSource.ACTUAL
        else:
            plan, plan_source = None, None

        roadmap = None if plan is None else plan * settings.roadmap_share
        planning_total = s.planning.total if s.planning else None
        results.append(
            SprintResult(
                input=s,
                forecast_ist=m_fist[i],
                velocity=m_vel[i],
                capacity=m_cap[i],
                normalized_velocity=m_norm[i],
                fulfillment=m_ful[i],
                scope_creep=m_scope[i],
                plan_capacity=plan_cap,
                plan_capacity_source=plan_cap_source,
                plan=plan,
                plan_source=plan_source,
                roadmap=roadmap,
                small_stuff=None if plan is None else plan - roadmap,
                planning_total=planning_total,
                planning_delta=(
                    None if plan is None or planning_total is None else plan - planning_total
                ),
            )
        )
    return results
