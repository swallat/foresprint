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
from sprintforecast.model import ForecastSettings, Sprint
from sprintforecast.storage import TeamData

# Unter so vielen Sprints mit Velocity sind Spanne und Häufigkeiten nur grobe Hinweise.
MIN_SAMPLES = 5


def _recent(values: list[float | None], window: int) -> list[float]:
    present = [v for v in values if v is not None]
    return present[-window:]


def plan_basis(fc: Forecast) -> list[TimelineEntry]:
    """Sprints, deren Velocity die Engine für den Plan nutzt: die abgeschlossenen und der
    laufende Sprint (sobald sein Review-Wert erfasst ist, hat er eine normierte Velocity).

    Die Garantie „Plan liegt in der Spanne“ gilt bis einschließlich dem laufenden Sprint. Die
    Engine mittelt auch einen künftigen Sprint (``start > today``) mit erfasstem Wert ein (Import
    oder Datei); der gehört hier bewusst nicht dazu, der Plan kann dann außerhalb der Spanne
    liegen (bekannter, offener Randfall)."""
    return [e for e in fc.entries if e.sprint.start <= fc.today]


def normalized_history(fc: Forecast) -> list[float]:
    """Normierte Velocity der letzten ``window`` Sprints mit Wert – abgeschlossene Sprints und der
    laufende, sobald dessen Review-Wert (Velocity) erfasst ist."""
    return _recent(
        [e.result.normalized_velocity.value for e in plan_basis(fc)], fc.data.team.forecast.window
    )


def sample_count(fc: Forecast) -> int:
    """Anzahl der Sprints mit normierter Velocity, aus denen die Prognose tatsächlich zieht:
    höchstens ``window`` (Stichprobe von Spanne und Simulation)."""
    return len(normalized_history(fc))


def available_count(fc: Forecast) -> int:
    """Anzahl aller verfügbaren Sprints mit normierter Velocity (ungedeckelt, gleiche Wertemenge
    wie ``plan_basis``). Sie entscheidet, ob es schon einen Forecast gibt (``MIN_THIN_HISTORY``);
    ``sample_count`` dagegen ist die auf ``window`` gedeckelte Stichprobe der Rechnung."""
    return sum(1 for e in plan_basis(fc) if e.result.normalized_velocity.value is not None)


def few_samples(fc: Forecast) -> bool:
    return sample_count(fc) < MIN_SAMPLES


# --- Bandbreite -----------------------------------------------------------------------


def plan_at(settings: ForecastSettings, nvel: float, capacity: float) -> float:
    """Forecast PLAN for a normalized velocity and a capacity: scaled to the capacity and
    rounded down to the team's precision (the calculation behind ``band``)."""
    return round_down(nvel / settings.reference_capacity * capacity, settings.rounding)


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
        return plan_at(settings, nvel, capacity)

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
    # Ø Scope Creep, bezogen auf das Commitment des jeweiligen Sprints (so wird er erfasst) …
    average_scope_creep: float | None
    samples: int
    # … und umgerechnet auf dieselbe Bezugsgröße wie der Kleinkram-Anteil: den Forecast PLAN.
    average_late_share: float | None
    configured_small_stuff: float  # 1 − verplanbarer Anteil, bezogen auf den Forecast PLAN

    @property
    def sufficient_data(self) -> bool:
        return self.samples >= 3

    @property
    def buffer_too_small(self) -> bool:
        return (
            self.sufficient_data
            and self.average_late_share is not None
            and self.average_late_share > self.configured_small_stuff
        )


def _late_share(e: TimelineEntry) -> float | None:
    """Nachträglich hinzugekommene Menge als Anteil des Forecast PLAN des Sprints (beim Planning
    eingefroren, sonst wie berechnet) – dieselbe Bezugsgröße wie der Kleinkram-Anteil. Scope
    Creep selbst ist auf das Commitment bezogen."""
    s = e.sprint
    if s.scope_creep is None:
        return None
    plan = s.forecast_plan if s.forecast_plan is not None else e.result.plan
    if s.forecast_ist is None or not plan:
        return s.scope_creep  # ohne Commitment oder Plan nicht umrechenbar
    return s.scope_creep * s.forecast_ist / plan


def buffer_hint(fc: Forecast) -> BufferHint:
    window = fc.data.team.forecast.window
    values = _recent([e.sprint.scope_creep for e in fc.history()], window)
    late = _recent([_late_share(e) for e in fc.history()], window)
    return BufferHint(
        average_scope_creep=statistics.fmean(values) if values else None,
        samples=len(values),
        average_late_share=statistics.fmean(late) if late else None,
        configured_small_stuff=1 - fc.data.team.forecast.roadmap_share,
    )


# --- Fertigstellung (Monte Carlo) -----------------------------------------------------


@dataclass(frozen=True)
class Completion:
    remaining: float
    share: float  # Anteil des Forecasts, der für die Restmenge zur Verfügung steht
    runs: int
    # Sprint-IDs, in denen die Restmenge in 50 % bzw. 85 % der Simulationsläufe erledigt ist
    # (modellabhängige Häufigkeit, keine Zusage); None = nicht innerhalb des Zeitraums.
    p50: str | None
    p85: str | None
    sprints: list[str]
    # Stichprobe: Anzahl der Sprints, aus denen die Simulation zieht.
    samples: int
    # Wahrscheinlichkeit, bis einschließlich Sprint i fertig zu sein
    cumulative: list[float]
    trend_capacity_sprints: list[str]
    # Erwartete Menge je Sprint für die Restmenge (Median Velocity × Ø Kapazität × Anteil)
    per_sprint: float


@dataclass(frozen=True)
class HorizonEntry:
    """A future sprint of a long forecast with the capacity to calculate with."""

    entry: TimelineEntry
    capacity: float
    # True: the sprint lies beyond the people list (capacity source trend or none); it counts
    # with the average capacity of the last sprints instead of the (over many sprints unstable)
    # capacity trend.
    trend: bool

    @property
    def sprint(self) -> Sprint:
        return self.entry.sprint


def horizon_forecast(data: TeamData, today: date, max_sprints: int = 26) -> Forecast:
    """Forecast with ``max_sprints`` sprints after today (the team's horizon is usually much
    shorter); ``data`` stays unchanged."""
    longer = copy.deepcopy(data)
    longer.team.forecast.horizon = max_sprints
    return build_forecast(longer, today)


def horizon_entries(fc: Forecast, max_sprints: int = 26) -> list[HorizonEntry]:
    """The future sprints of ``fc`` (start after today) with the capacity to calculate with:
    as forecast while the people list reaches, beyond it the average capacity of the last
    ``window`` sprints."""
    window = fc.data.team.forecast.window
    avg_capacity = statistics.fmean(
        _recent([e.result.capacity.value for e in fc.history()], window) or [0.0]
    )
    result = []
    for e in [e for e in fc.entries if e.sprint.start > fc.today][:max_sprints]:
        if e.result.plan_capacity_source in (
            CapacitySource.RECORDED,
            CapacitySource.PEOPLE,
            CapacitySource.ESTIMATED,
            CapacitySource.CALENDAR,
            CapacitySource.EXPECTED,
        ):
            result.append(HorizonEntry(e, e.result.plan_capacity or 0.0, trend=False))
        else:
            result.append(HorizonEntry(e, avg_capacity, trend=True))
    return result


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
    z. B. verplanbarer Anteil × Projektanteil (0,8 × 0,5 = 0,4).

    Je Sprint wird zufällig eine normierte Velocity der letzten Sprints gezogen und mit der
    Kapazität des Sprints umgerechnet. Für Sprints ohne Personenliste (Kapazität nur als Trend)
    wird statt des (über viele Sprints instabilen) Trends die Ø Kapazität der letzten Sprints
    genommen.
    """
    fc = horizon_forecast(data, today, max_sprints)
    history = normalized_history(fc)
    if len(history) < 2 or remaining <= 0 or share <= 0:
        return None
    horizon = horizon_entries(fc, max_sprints)
    future = [h.entry for h in horizon]
    capacities = [h.capacity for h in horizon]
    trend_ids = [h.sprint.id for h in horizon if h.trend]

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
        samples=len(history),
        cumulative=cumulative,
        trend_capacity_sprints=trend_ids,
        per_sprint=statistics.median(history) / ref * statistics.median(capacities) * share,
    )
