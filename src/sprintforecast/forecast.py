# SPDX-License-Identifier: EUPL-1.2
"""Connects storage, capacity calculator and calculation engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sprintforecast.calendar import following_sprint
from sprintforecast.capacity import (
    AbsenceHistory,
    absence_history,
    capacity_with_expected_absences,
    estimated_capacity,
    sprint_capacity,
)
from sprintforecast.engine import CapacitySource, SprintInput, SprintResult, compute
from sprintforecast.model import AbsenceState, Planning, Sprint, absence_status
from sprintforecast.storage import TeamData


@dataclass
class TimelineEntry:
    sprint: Sprint
    # False for sprints generated from the calendar only (no file).
    recorded: bool
    result: SprintResult
    # Digits to which this team's capacity is displayed (``team.capacity.rounding``, like
    # ``CapacityBreakdown.rounded``); see ``report.fmt_capacity``.
    capacity_digits: int = 1


@dataclass
class Forecast:
    data: TeamData
    today: date
    entries: list[TimelineEntry]
    # Absence history used to estimate unknown absences (None = without a people list).
    absences: AbsenceHistory | None = None

    @property
    def current(self) -> TimelineEntry | None:
        return next((e for e in self.entries if e.sprint.start <= self.today < e.sprint.end), None)

    def upcoming(self) -> list[TimelineEntry]:
        """Current sprint and the following ``horizon`` sprints."""
        horizon = self.data.team.forecast.horizon
        future = [e for e in self.entries if e.sprint.end > self.today]
        return future[: horizon + 1]

    def history(self, count: int | None = None) -> list[TimelineEntry]:
        past = [e for e in self.entries if e.sprint.end <= self.today]
        return past if count is None else past[-count:] if count > 0 else []

    def entry(self, sprint_id: str) -> TimelineEntry | None:
        return next((e for e in self.entries if e.sprint.id == sprint_id), None)

    def default_entry(self, purpose: str) -> TimelineEntry | None:
        """Suggestion per purpose: current (running), planning (next Planning), next (absences),
        review (Review)."""
        if purpose == "current":
            return self.current
        if purpose == "planning":
            # The earliest running or future sprint without a Commitment.
            open_ = [
                e for e in self.entries if e.sprint.end > self.today and e.sprint.commitment is None
            ]
            return open_[0] if open_ else None
        if purpose == "next":
            future = [e for e in self.entries if e.sprint.start > self.today]
            return future[0] if future else None
        if purpose == "review":
            open_past = [e for e in self.history() if e.sprint.velocity is None]
            return open_past[-1] if open_past else self.current
        raise ValueError(purpose)


def timeline(data: TeamData, today: date) -> list[tuple[Sprint, bool]]:
    """Recorded sprints plus generated follow-up sprints up to ``horizon`` sprints after today."""
    entries = [(s, True) for s in data.sprints]
    horizon = data.team.forecast.horizon
    last = data.sprints[-1] if data.sprints else None
    while sum(1 for s, _ in entries if s.start > today) < horizon:
        last = following_sprint(data.team, last)
        entries.append((last, False))
    return entries


def find_sprint(data: TeamData, sprint_id: str, max_ahead: int = 200) -> Sprint | None:
    """Sprint from storage or, if it has no file yet, generated from the calendar."""
    if (existing := data.sprint(sprint_id)) is not None:
        return existing
    last = data.sprints[-1] if data.sprints else None
    for _ in range(max_ahead):
        last = following_sprint(data.team, last)
        if last.id == sprint_id:
            return last
    return None


def lookup_sprint(fc: Forecast, sprint_id: str, max_ahead: int = 52) -> Sprint | None:
    """Sprint by id: recorded, in the forecast, or generated from the calendar up to
    ``max_ahead`` sprints beyond the last recorded one; None = unknown."""
    if (existing := fc.data.sprint(sprint_id)) is not None:
        return existing
    entry = fc.entry(sprint_id)
    if entry is not None:
        return entry.sprint
    return find_sprint(fc.data, sprint_id, max_ahead)


def apply_planning(sprint: Sprint, commitment: float | None, planning: Planning | None) -> bool:
    """Applies the Planning inputs to ``sprint``.

    The control calculation (carryover, backlog, corrections) is optional; empty or 0 means
    "not recorded". An empty Commitment is prefilled with carryover + backlog.
    Returns True if it was prefilled.
    """
    if planning is not None and not (
        planning.carryover or planning.backlog or planning.corrections
    ):
        planning = None
    sprint.planning = planning
    planned = planning.committed if planning is not None else 0.0
    prefilled = commitment is None and planned > 0
    sprint.commitment = planned if prefilled else commitment
    return prefilled


def freeze_plan(
    sprint: Sprint, entry: TimelineEntry | None, today: date, refreeze: bool = False
) -> None:
    """Remembers the Forecast PLAN at Planning time, the basis of the default distribution per
    product. An already frozen value is kept unless ``refreeze``; completed sprints stay
    unchanged."""
    if entry is None or sprint.end <= today or entry.result.plan is None:
        return
    if sprint.forecast_plan is not None and not refreeze:
        return
    sprint.forecast_plan = entry.result.plan


def refreeze_offer(sprint: Sprint, entry: TimelineEntry | None) -> tuple[float, float] | None:
    """(frozen, current) if the Forecast PLAN has changed since freezing."""
    if entry is None or sprint.forecast_plan is None or entry.result.plan is None:
        return None
    if abs(sprint.forecast_plan - entry.result.plan) < 1e-9:
        return None
    return sprint.forecast_plan, entry.result.plan


def absences_known(sprint: Sprint) -> bool:
    """Absences count as confirmed if some are entered, if "nobody is absent" was explicitly
    confirmed (Absences page), or, for older files without a stored state, if the sprint was
    already planned or evaluated. Announced absences from the PO pre-planning confirm
    nothing."""
    return absence_status(sprint) is AbsenceState.CONFIRMED


def resolve_capacity(
    data: TeamData, sprint: Sprint, history: AbsenceHistory | None = None
) -> tuple[float | None, CapacitySource | None]:
    """Capacity of a sprint and its source.

    With a people list it is always calculated from calendar and people (holidays, sprint
    length, FTE); only unknown absences are estimated. The capacity trend applies only to teams
    without a people list."""
    if sprint.capacity is not None:
        return sprint.capacity, CapacitySource.RECORDED
    if not data.people:
        return None, None
    state = absence_status(sprint)
    if state is AbsenceState.CONFIRMED:
        return sprint_capacity(data.team, data.people, sprint).capacity, CapacitySource.PEOPLE
    if state is AbsenceState.EXPECTED:
        capacity = capacity_with_expected_absences(data.team, data.people, sprint)
        return capacity, CapacitySource.EXPECTED
    rate = history.rate if history is not None else None
    capacity = estimated_capacity(data.team, data.people, sprint, rate or 0.0)
    return capacity, CapacitySource.ESTIMATED if rate is not None else CapacitySource.CALENDAR


def build_forecast(data: TeamData, today: date | None = None) -> Forecast:
    today = today or date.today()
    line = timeline(data, today)
    history = None
    if data.people:
        past = [s for s, rec in line if rec and s.end <= today]
        history = absence_history(data.team, data.people, past, data.team.capacity.absence_history)
    inputs = []
    for sprint, _ in line:
        capacity, source = resolve_capacity(data, sprint, history)
        inputs.append(
            SprintInput(
                id=sprint.id,
                capacity=capacity,
                capacity_source=source,
                commitment=sprint.commitment,
                velocity=sprint.velocity,
                scope_creep=sprint.scope_creep,
                planning=sprint.planning,
            )
        )
    results = compute(inputs, data.team.forecast)
    entries = [
        TimelineEntry(sprint=s, recorded=r, result=res, capacity_digits=data.team.capacity.rounding)
        for (s, r), res in zip(line, results, strict=True)
    ]
    return Forecast(data=data, today=today, entries=entries, absences=history)
