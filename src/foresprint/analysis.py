# SPDX-License-Identifier: EUPL-1.2
"""Supplementary analyses for the forecast. They do not change any existing values.

- Range: forecast with the lowest, middle and highest normalized velocity of the last
  sprints instead of the trend.
- Focus factor: velocity / capacity (independent of the reference capacity).
- Buffer recommendation: average scope creep of the last sprints compared to the small-items
  share.
- Completion: Monte Carlo simulation of the sprint in which a remaining quantity is done.
"""

from __future__ import annotations

import copy
import random
import statistics
from dataclasses import dataclass
from datetime import date

from foresprint.engine import CapacitySource, round_down
from foresprint.forecast import Forecast, TimelineEntry, build_forecast
from foresprint.model import ForecastSettings, Sprint
from foresprint.storage import TeamData

# With fewer sprints with a velocity than this, the range and frequencies are only rough hints.
MIN_SAMPLES = 5


def _recent(values: list[float | None], window: int) -> list[float]:
    present = [v for v in values if v is not None]
    return present[-window:]


def plan_basis(fc: Forecast) -> list[TimelineEntry]:
    """Sprints whose velocity the engine uses for the plan: the completed ones and the current
    sprint (once its review value is recorded, it has a normalized velocity).

    The guarantee "the plan lies within the range" holds up to and including the current sprint.
    The engine also averages in a future sprint (``start > today``) with a recorded value (import
    or file); that one deliberately does not belong here, so the plan can then lie outside the
    range (known, open edge case)."""
    return [e for e in fc.entries if e.sprint.start <= fc.today]


def normalized_history(fc: Forecast) -> list[float]:
    """Normalized velocity of the last ``window`` sprints with a value: completed sprints and the
    current one, once its review value (velocity) is recorded."""
    return _recent(
        [e.result.normalized_velocity.value for e in plan_basis(fc)], fc.data.team.forecast.window
    )


def sample_count(fc: Forecast) -> int:
    """Number of sprints with a normalized velocity that the forecast actually draws from:
    at most ``window`` (sample for the range and the simulation)."""
    return len(normalized_history(fc))


def available_count(fc: Forecast) -> int:
    """Number of all available sprints with a normalized velocity (uncapped, same set of values
    as ``plan_basis``). It decides whether a forecast exists yet (``MIN_THIN_HISTORY``);
    ``sample_count``, in contrast, is the sample of the calculation capped at ``window``."""
    return sum(1 for e in plan_basis(fc) if e.result.normalized_velocity.value is not None)


def few_samples(fc: Forecast) -> bool:
    return sample_count(fc) < MIN_SAMPLES


# --- Range ----------------------------------------------------------------------------


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
    """Forecast range for a future sprint, from the spread of the last sprints."""
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


# --- Focus factor ---------------------------------------------------------------------


def focus_factor(entry: TimelineEntry) -> float | None:
    r = entry.result
    if r.velocity.value is None or not r.capacity.value:
        return None
    return r.velocity.value / r.capacity.value


def average_focus_factor(fc: Forecast) -> float | None:
    values = _recent([focus_factor(e) for e in fc.history()], fc.data.team.forecast.window)
    return statistics.fmean(values) if values else None


# --- Buffer ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BufferHint:
    # Average scope creep, relative to the commitment of the respective sprint (as recorded) ...
    average_scope_creep: float | None
    samples: int
    # ... and converted to the same base as the small-items share: the Forecast PLAN.
    average_late_share: float | None
    configured_small_stuff: float  # 1 − plannable share, relative to the Forecast PLAN

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
    """Quantity added later, as a share of the sprint's Forecast PLAN (frozen at Planning,
    otherwise as calculated), the same base as the small-items share. Scope creep itself is
    relative to the commitment."""
    s = e.sprint
    if s.scope_creep is None:
        return None
    plan = s.forecast_plan if s.forecast_plan is not None else e.result.plan
    if s.commitment is None or not plan:
        return s.scope_creep  # cannot be converted without a commitment or plan
    return s.scope_creep * s.commitment / plan


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


# --- Completion (Monte Carlo) ---------------------------------------------------------


@dataclass(frozen=True)
class Completion:
    remaining: float
    share: float  # share of the forecast available for the remaining quantity
    runs: int
    # Sprint IDs in which the remaining quantity is done in 50 % or 85 % of the simulation runs
    # (model-dependent frequency, not a commitment); None = not within the period.
    p50: str | None
    p85: str | None
    sprints: list[str]
    # Sample: number of sprints the simulation draws from.
    samples: int
    # Probability of being done by the end of sprint i
    cumulative: list[float]
    trend_capacity_sprints: list[str]
    # Expected quantity per sprint for the remaining quantity (median velocity × average
    # capacity × share)
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
    """Simulates, starting with the next sprint, when ``remaining`` is done.

    ``share`` is the share of the forecast available for the remaining quantity per sprint,
    e.g. plannable share × project share (0.8 × 0.5 = 0.4).

    For each sprint a normalized velocity of the last sprints is drawn at random and converted
    with the sprint's capacity. For sprints without a people list (capacity only as a trend),
    the average capacity of the last sprints is used instead of the trend (which is unstable
    over many sprints).
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
