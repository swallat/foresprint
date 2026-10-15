# SPDX-License-Identifier: EUPL-1.2
"""Kapazität eines Sprints aus Personenliste, Feiertagen und Fehltagen."""

from __future__ import annotations

from dataclasses import dataclass, field

from sprintforecast.calendar import is_holiday, workdays
from sprintforecast.engine import round_down
from sprintforecast.model import Person, Sprint, Team


@dataclass
class PersonCapacity:
    person: Person
    workdays: int
    holidays: int
    absence_days: float
    capacity: float


@dataclass
class CapacityBreakdown:
    people: list[PersonCapacity] = field(default_factory=list)
    gross: float = 0.0
    overhead: float = 0.0
    capacity: float = 0.0


def person_capacity(team: Team, person: Person, sprint: Sprint) -> PersonCapacity | None:
    region = person.region or team.capacity.region
    days = [d for d in workdays(sprint.start, sprint.end) if person.fte_on(d) > 0]
    if not days:
        return None
    working = [d for d in days if not is_holiday(d, region)]
    absence = min(sprint.absences.get(person.id, 0.0), len(working))
    available = sum(person.fte_on(d) for d in working)
    mean_fte = available / len(working) if working else 0.0
    return PersonCapacity(
        person=person,
        workdays=len(days),
        holidays=len(days) - len(working),
        absence_days=absence,
        capacity=max(available - absence * mean_fte, 0.0),
    )


def sprint_capacity(team: Team, people: list[Person], sprint: Sprint) -> CapacityBreakdown:
    rows = [pc for p in people if (pc := person_capacity(team, p, sprint)) is not None]
    gross = sum(r.capacity for r in rows)
    overhead = gross * team.capacity.overhead_share
    return CapacityBreakdown(
        people=rows,
        gross=gross,
        overhead=overhead,
        capacity=round_down(gross - overhead, team.capacity.rounding),
    )
