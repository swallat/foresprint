# SPDX-License-Identifier: EUPL-1.2
"""Ergänzende Analysen zum Forecast – ändern keine bestehenden Werte.

- Bandbreite: Forecast mit der niedrigsten, mittleren und höchsten normierten Velocity der
  letzten Sprints statt mit dem Trend.
- Fokusfaktor: Velocity / Kapazität (unabhängig von der Referenzkapazität).
- Puffer-Empfehlung: Ø Scope Creep der letzten Sprints im Vergleich zum Kleinkram-Anteil.
- Fertigstellung: Monte-Carlo-Simulation, in welchem Sprint eine Restmenge erledigt ist.
"""

from __future__ import annotations

import copy
import random
import statistics
from dataclasses import dataclass
from datetime import date

from sprintforecast.engine import CapacitySource, round_down
from sprintforecast.forecast import Forecast, TimelineEntry, build_forecast
from sprintforecast.storage import TeamData


def _recent(values: list[float | None], window: int) -> list[float]:
    present = [v for v in values if v is not None]
    return present[-window:]


def normalized_history(fc: Forecast) -> list[float]:
    """Normierte Velocity der letzten ``window`` abgeschlossenen Sprints mit Wert."""
    return _recent(
        [e.result.normalized_velocity.value for e in fc.history()], fc.data.team.forecast.window
    )


# --- Bandbreite -----------------------------------------------------------------------


@dataclass(frozen=True)
class Band:
    low: float
    mid: float
    high: float
    samples: int


def band(fc: Forecast, entry: TimelineEntry) -> Band | None:
    """Forecast-Spanne für einen künftigen Sprint aus der Streuung der letzten Sprints."""
    values = normalized_history(fc)
    capacity = entry.result.plan_capacity
    if len(values) < 2 or capacity is None:
        return None
    settings = fc.data.team.forecast

    def plan(nvel: float) -> float:
        return round_down(nvel / settings.reference_capacity * capacity, settings.rounding)

    return Band(
        low=plan(min(values)),
        mid=plan(statistics.median(values)),
        high=plan(max(values)),
        samples=len(values),
    )


# --- Fokusfaktor ----------------------------------------------------------------------


def focus_factor(entry: TimelineEntry) -> float | None:
    r = entry.result
    if r.velocity.value is None or not r.capacity.value:
        return None
    return r.velocity.value / r.capacity.value


def average_focus_factor(fc: Forecast) -> float | None:
    values = _recent([focus_factor(e) for e in fc.history()], fc.data.team.forecast.window)
    return statistics.fmean(values) if values else None


# --- Puffer ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BufferHint:
    average_scope_creep: float | None
    samples: int
    configured_small_stuff: float  # 1 − Roadmap-Anteil

    @property
    def sufficient_data(self) -> bool:
        return self.samples >= 3

    @property
    def buffer_too_small(self) -> bool:
        return (
            self.sufficient_data
            and self.average_scope_creep is not None
            and self.average_scope_creep > self.configured_small_stuff
        )


def buffer_hint(fc: Forecast) -> BufferHint:
    window = fc.data.team.forecast.window
    values = _recent([e.sprint.scope_creep for e in fc.history()], window)
    return BufferHint(
        average_scope_creep=statistics.fmean(values) if values else None,
        samples=len(values),
        configured_small_stuff=1 - fc.data.team.forecast.roadmap_share,
    )


# --- Fertigstellung (Monte Carlo) -----------------------------------------------------


@dataclass(frozen=True)
class Completion:
    remaining: float
    share: float  # Anteil des Forecasts, der für die Restmenge zur Verfügung steht
    runs: int
    # Sprint-IDs, in denen die Restmenge mit 50 % bzw. 85 % Wahrscheinlichkeit erledigt ist;
    # None = nicht innerhalb des betrachteten Zeitraums.
    p50: str | None
    p85: str | None
    sprints: list[str]
    # Wahrscheinlichkeit, bis einschließlich Sprint i fertig zu sein
    cumulative: list[float]
    trend_capacity_sprints: list[str]
    # Erwartete Menge je Sprint für die Restmenge (Median Velocity × Ø Kapazität × Anteil)
    per_sprint: float


def completion(
    data: TeamData,
    today: date,
    remaining: float,
    share: float,
    max_sprints: int = 26,
    runs: int = 10_000,
    seed: int = 1,
) -> Completion | None:
    """Simuliert ab dem nächsten Sprint, wann ``remaining`` erledigt ist.

    ``share`` ist der Anteil des Forecasts, der der Restmenge je Sprint zur Verfügung steht,
    z. B. Roadmap-Anteil × Projektanteil (0,8 × 0,5 = 0,4).

    Je Sprint wird zufällig eine normierte Velocity der letzten Sprints gezogen und mit der
    Kapazität des Sprints umgerechnet. Für Sprints ohne erfasste Fehltage wird statt des
    (über viele Sprints instabilen) Trends die Ø Kapazität der letzten Sprints genommen.
    """
    longer = copy.deepcopy(data)
    longer.team.forecast.horizon = max_sprints
    fc = build_forecast(longer, today)
    history = normalized_history(fc)
    if len(history) < 2 or remaining <= 0 or share <= 0:
        return None
    window = data.team.forecast.window
    avg_capacity = statistics.fmean(
        _recent([e.result.capacity.value for e in fc.history()], window) or [0.0]
    )
    future = [e for e in fc.entries if e.sprint.start > today][:max_sprints]
    capacities, trend_ids = [], []
    for e in future:
        if e.result.plan_capacity_source in (CapacitySource.RECORDED, CapacitySource.PEOPLE):
            capacities.append(e.result.plan_capacity or 0.0)
        else:
            capacities.append(avg_capacity)
            trend_ids.append(e.sprint.id)

    ref = data.team.forecast.reference_capacity
    rng = random.Random(seed)
    finished_in = [0] * len(future)
    for _ in range(runs):
        done = 0.0
        for i, cap in enumerate(capacities):
            done += rng.choice(history) / ref * cap * share
            if done >= remaining:
                finished_in[i] += 1
                break

    cumulative, total = [], 0
    for count in finished_in:
        total += count
        cumulative.append(total / runs)

    def first_reaching(p: float) -> str | None:
        return next((future[i].sprint.id for i, c in enumerate(cumulative) if c >= p), None)

    return Completion(
        remaining=remaining,
        share=share,
        runs=runs,
        p50=first_reaching(0.5),
        p85=first_reaching(0.85),
        sprints=[e.sprint.id for e in future],
        cumulative=cumulative,
        trend_capacity_sprints=trend_ids,
        per_sprint=statistics.median(history) / ref * statistics.median(capacities) * share,
    )
