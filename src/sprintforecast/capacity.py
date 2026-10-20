# SPDX-License-Identifier: EUPL-1.2
"""Sprint capacity from the list of people, holidays and absences."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from sprintforecast.calendar import is_holiday, person_weekend, workdays
from sprintforecast.engine import round_half_up
from sprintforecast.model import AbsenceState, Person, Sprint, Team, _legacy_known, absence_status


@dataclass
class PersonCapacity:
    person: Person
    workdays: int
    holidays: int
    absence_days: float
    # Available after holidays and absences (before the deductions for Scrum events).
    capacity: float
    mean_fte: float = 1.0
    # FTE changes during the sprint: absences are weighted with the mean FTE (approximation).
    fte_changes: bool = False
    # Fixed deduction for Scrum events: PD per person × FTE, at most the capacity.
    overhead: float = 0.0


@dataclass
class CapacityBreakdown:
    people: list[PersonCapacity] = field(default_factory=list)

    @property
    def approximated(self) -> list[PersonCapacity]:
        """People whose FTE changes during the sprint (absences weighted only approximately)."""
        return [p for p in self.people if p.fte_changes and p.absence_days]

    gross: float = 0.0
    # Total deduction for Scrum events = share + fixed PD
    overhead: float = 0.0
    overhead_share_part: float = 0.0
    overhead_days_part: float = 0.0
    # Unrounded: the forecast keeps calculating with it (no rounding error in the denominator
    # of the normalized velocity). Rounding happens only on display and freezing (``rounded``).
    capacity: float = 0.0
    rounding: int = 1

    @property
    def rounded(self) -> float:
        """Capacity for display and storage (rounded half up)."""
        return round_half_up(self.capacity, self.rounding)


def person_capacity(
    team: Team, person: Person, sprint: Sprint, absence_rate: float = 0.0
) -> PersonCapacity | None:
    """Capacity of one person in the sprint, in PD.

    FTE is the share of the person's working days (see ``Person.workweek``): someone who works
    four days a week and enters that as ``workweek: mon,tue,wed,thu`` has FTE 1; ``fte: 0.8``
    with a full working week (Mon-Fri) gives the same capacity. Using both (four days and 0.8)
    would deduct twice.

    ``absence_rate`` reduces the capacity by an expected share of unknown absences (estimated
    from history); entered absences apply in addition."""
    country = person.country or team.capacity.country
    # If the person has their own country, the team's region does not apply.
    region = person.region or (None if person.country else team.capacity.region)
    weekend = person_weekend(team, person)
    days = [d for d in workdays(sprint.start, sprint.end, weekend) if person.fte_on(d) > 0]
    if not days:
        return None
    working = [d for d in days if not is_holiday(d, region, country)]
    absence = min(sprint.absences.get(person.id, 0.0), len(working))
    available = sum(person.fte_on(d) for d in working)
    mean_fte = available / len(working) if working else 0.0
    capacity = max(available - absence * mean_fte, 0.0) * (1 - absence_rate)
    return PersonCapacity(
        person=person,
        workdays=len(days),
        holidays=len(days) - len(working),
        absence_days=absence,
        capacity=capacity,
        mean_fte=mean_fte,
        fte_changes=len({person.fte_on(d) for d in working}) > 1,
        overhead=min(capacity, team.capacity.overhead_days * mean_fte),
    )


def sprint_capacity(
    team: Team, people: list[Person], sprint: Sprint, absence_rate: float = 0.0
) -> CapacityBreakdown:
    """Capacity of the sprint. One shared calculation for confirmed, announced and expected
    absences: first holidays and absences (or the expected rate) per person, then the deduction
    for Scrum events. The result (``capacity``) stays unrounded; rounding happens only for
    display and freezing (``CapacityBreakdown.rounded``, half up).

    The deduction: fixed PD per person (``overhead_days`` × FTE, at most the person's capacity)
    replace the percentage deduction (``overhead_share``); both are the same deduction in two
    units and are not added."""
    rows = [
        pc for p in people if (pc := person_capacity(team, p, sprint, absence_rate)) is not None
    ]
    gross = sum(r.capacity for r in rows)
    days_part = sum(r.overhead for r in rows)
    share_part = 0.0 if team.capacity.overhead_days else gross * team.capacity.overhead_share
    overhead = share_part + days_part
    return CapacityBreakdown(
        people=rows,
        gross=gross,
        overhead=overhead,
        overhead_share_part=share_part,
        overhead_days_part=days_part,
        capacity=max(gross - overhead, 0.0),
        rounding=team.capacity.rounding,
    )


def production_share(team: Team, people: list[Person], sprint: Sprint) -> float | None:
    """Share of the sprint capacity held by people with production access (0-1).
    None if nobody has production access."""
    group = [p for p in people if p.production_access]
    if not group:
        return None
    total = sprint_capacity(team, people, sprint).gross
    return sprint_capacity(team, group, sprint).gross / total if total else 0.0


@dataclass(frozen=True)
class AbsenceHistory:
    """Average share of capacity lost to absences in past sprints."""

    rate: float | None
    # The sprints actually used (IDs, older first) and their rates.
    sprints: list[str]
    rates: list[float]
    # Of these, the sprints that are only derived as confirmed from other fields (older files
    # without a stored state) and have no absences: they count as "0 % loss", which makes the
    # rate uncertain. Changes no number.
    derived: list[str] = field(default_factory=list)


def absence_history(
    team: Team, people: list[Person], past: list[Sprint], count: int
) -> AbsenceHistory:
    """Average loss to absences over the last ``count`` sprints.

    Only completed sprints whose absences are **confirmed** are considered, using the same
    definition as for the capacity (``absence_status``). Confirmed sprints without absences
    count with a rate of 0, otherwise the rate would be too high. Unknown and merely announced
    sprints are left out."""
    if count <= 0:
        return AbsenceHistory(None, [], [])
    used: list[tuple[str, float]] = []
    derived: set[str] = set()
    for sprint in past:
        if absence_status(sprint) is not AbsenceState.CONFIRMED:
            continue
        if not sprint.absences and sprint.absence_state is None and _legacy_known(sprint):
            derived.add(sprint.id)
        without = copy.deepcopy(sprint)
        without.absences = {}
        full = sprint_capacity(team, people, without).gross
        if full <= 0:
            continue
        used.append((sprint.id, 1 - sprint_capacity(team, people, sprint).gross / full))
    used = used[-count:]
    rates = [r for _, r in used]
    return AbsenceHistory(
        rate=sum(rates) / len(rates) if rates else None,
        sprints=[i for i, _ in used],
        rates=rates,
        derived=[i for i, _ in used if i in derived],
    )


def expected_absence_rate(
    team: Team, people: list[Person], past: list[Sprint], count: int
) -> float | None:
    """Average share of capacity lost to absences (0-1); None without history."""
    return absence_history(team, people, past, count).rate


def estimated_capacity(team: Team, people: list[Person], sprint: Sprint, rate: float) -> float:
    """Capacity of a sprint without known absences, reduced by the expected rate."""
    return sprint_capacity(team, people, sprint, rate).capacity


def capacity_with_expected_absences(team: Team, people: list[Person], sprint: Sprint) -> float:
    """Capacity of a sprint with its announced absences (PO pre-planning)."""
    probe = copy.deepcopy(sprint)
    probe.absences = dict(sprint.expected_absences)
    return sprint_capacity(team, people, probe).capacity
