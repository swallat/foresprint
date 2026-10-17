# SPDX-License-Identifier: EUPL-1.2
"""Rechenkern: Velocity-, Kapazitäts- und Prognoseberechnung je Sprint.

Kennzahlen (je Sprint):
    Commitment, Velocity, Kapazität, Scope Creep   → Eingaben
    Normierte Velocity  = Velocity / Kapazität × Referenzkapazität
    Fulfillment         = Velocity / Commitment
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


# Neue Teams: Schon ab so vielen Sprints mit Wert gibt es einen Durchschnitt und damit einen
# Forecast, auch wenn das Fenster noch nicht voll ist („Historie dünn“, siehe thin_history).
MIN_THIN_HISTORY = 3


def thin_history(values: Series, window: int) -> bool:
    """Zu wenige Werte für ein volles Fenster, aber genug für einen Anfangs-Forecast."""
    count = sum(1 for v in values if v is not None)
    return MIN_THIN_HISTORY <= count < window


def rolling_average(values: Series, window: int) -> Series:
    """Gleitender Durchschnitt über die letzten ``window`` Sprints **mit Wert**.

    Regel für Lücken: Sprints ohne Wert zählen nicht mit, das Fenster reicht entsprechend weiter
    zurück (es werden immer ``window`` Werte gemittelt, nie weniger). Der Durchschnitt ist nur
    definiert, wenn der Sprint selbst einen Wert hat und davor genug Werte vorliegen.

    Ausnahme für neue Teams: Gibt es insgesamt weniger als ``window``, aber mindestens
    ``MIN_THIN_HISTORY`` Werte, mittelt jeder Sprint ab dem dritten Wert über alle bisherigen
    (dünne Historie).
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
    """Anzahl der Sprints ohne Wert, die das Fenster des letzten Durchschnitts überspringt."""
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


def _trend(average: Series, mode: TrendMode | str) -> tuple[Series, list[bool]]:
    """Trend und je Position, ob statt des gewählten Modus auf ``flat`` zurückgegriffen wurde
    (zu wenig Historie für die Fortschreibung)."""
    mode = TrendMode(mode)
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
                fallback[i] = True  # Historie dünn: letzten Durchschnitt fortschreiben
            elif i > 0 and fallback[i - 1]:
                fallback[i] = True  # baut auf einem Wert auf, der schon „flat“ war
        # Mengen, Kapazität und Anteile sind nie negativ; eine Fortschreibung unter null
        # (Rauschen) wird auf null begrenzt.
        result[i] = None if value is None else max(value, 0.0)
    return result, fallback


def trend(average: Series, mode: TrendMode | str) -> Series:
    """Schreibt den gleitenden Durchschnitt dort fort, wo er fehlt (Zukunft).

    Reicht die Historie für ``classic``/``linear`` nicht (z. B. genau ``window`` Sprints),
    gilt ``flat``. Das Ergebnis ist nie negativ."""
    return _trend(average, mode)[0]


class CapacitySource(StrEnum):
    RECORDED = "erfasst"
    PEOPLE = "Personenliste"
    TREND = "Trend"
    # Personenliste und Kalender; Fehltage unbekannt und keine Historie, daher ohne Abzug.
    CALENDAR = "Kalender, Fehltage unbekannt"
    ESTIMATED = "erwartete Fehltage"
    EXPECTED = "angekündigte Fehltage"


# Quellen ohne bekannte Fehltage und ohne Historie: Die Kapazität ist nur geschätzt.
UNSURE_SOURCES = (CapacitySource.TREND, CapacitySource.CALENDAR)


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
    # Stichprobe hinter dem Trend der normierten Velocity: Anzahl aller bisherigen Werte; und ob
    # wegen dünner Historie ``flat`` statt des gewählten Trend-Modus gerechnet wurde.
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
        # Dünne Historie: nur der Durchschnitt, keine Fortschreibung eines Anstiegs.
        trends, _ = _trend(averages, TrendMode.FLAT)
        fallback = [TrendMode(settings.trend_mode) is not TrendMode.FLAT] * len(values)
    else:
        trends, fallback = _trend(averages, settings.trend_mode)
    metrics = [Metric(v, a, t) for v, a, t in zip(values, averages, trends, strict=True)]
    return metrics, fallback


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

    m_fist, _ = _metric_series(forecast_ist, settings)
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
        elif s.forecast_ist is not None:
            # Auch der Rückgriff auf Commitment wird abgerundet.
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
