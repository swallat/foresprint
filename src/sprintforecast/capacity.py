# SPDX-License-Identifier: EUPL-1.2
"""Kapazität eines Sprints aus Personenliste, Feiertagen und Fehltagen."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from sprintforecast.calendar import is_holiday, person_weekend, workdays
from sprintforecast.engine import round_down
from sprintforecast.model import Person, Sprint, Team


@dataclass
class PersonCapacity:
    person: Person
    workdays: int
    holidays: int
    absence_days: float
    # Verfügbar nach Feiertagen und Fehltagen (vor den Abzügen für Scrum-Termine).
    capacity: float
    mean_fte: float = 1.0
    # Fester Abzug für Scrum-Termine: PT je Person × FTE, höchstens die Kapazität.
    overhead: float = 0.0


@dataclass
class CapacityBreakdown:
    people: list[PersonCapacity] = field(default_factory=list)
    gross: float = 0.0
    # Abzug Scrum-Termine gesamt = Anteil + feste PT
    overhead: float = 0.0
    overhead_share_part: float = 0.0
    overhead_days_part: float = 0.0
    capacity: float = 0.0


def person_capacity(team: Team, person: Person, sprint: Sprint) -> PersonCapacity | None:
    country = person.country or team.capacity.country
    # Hat die Person ein eigenes Land, gilt nicht die Region des Teams.
    region = person.region or (None if person.country else team.capacity.region)
    weekend = person_weekend(team, person)
    days = [d for d in workdays(sprint.start, sprint.end, weekend) if person.fte_on(d) > 0]
    if not days:
        return None
    working = [d for d in days if not is_holiday(d, region, country)]
    absence = min(sprint.absences.get(person.id, 0.0), len(working))
    available = sum(person.fte_on(d) for d in working)
    mean_fte = available / len(working) if working else 0.0
    capacity = max(available - absence * mean_fte, 0.0)
    return PersonCapacity(
        person=person,
        workdays=len(days),
        holidays=len(days) - len(working),
        absence_days=absence,
        capacity=capacity,
        mean_fte=mean_fte,
        overhead=min(capacity, team.capacity.overhead_days * mean_fte),
    )


def sprint_capacity(team: Team, people: list[Person], sprint: Sprint) -> CapacityBreakdown:
    rows = [pc for p in people if (pc := person_capacity(team, p, sprint)) is not None]
    gross = sum(r.capacity for r in rows)
    # Prozent und PT je Person sind derselbe Abzug in zwei Einheiten: nicht addieren.
    days_part = sum(r.overhead for r in rows)
    share_part = 0.0 if team.capacity.overhead_days else gross * team.capacity.overhead_share
    overhead = share_part + days_part
    return CapacityBreakdown(
        people=rows,
        gross=gross,
        overhead=overhead,
        overhead_share_part=share_part,
        overhead_days_part=days_part,
        capacity=round_down(max(gross - overhead, 0.0), team.capacity.rounding),
    )


def production_share(team: Team, people: list[Person], sprint: Sprint) -> float | None:
    """Anteil der Personen mit Produktionszugriff an der Kapazität des Sprints (0–1).
    None, wenn niemand Produktionszugriff hat."""
    group = [p for p in people if p.production_access]
    if not group:
        return None
    total = sprint_capacity(team, people, sprint).gross
    return sprint_capacity(team, group, sprint).gross / total if total else 0.0


def expected_absence_rate(
    team: Team, people: list[Person], past: list[Sprint], count: int
) -> float | None:
    """Durchschnittlicher Anteil der Kapazität, der in den letzten ``count`` Sprints durch
    Fehltage verloren ging (0–1). Berücksichtigt werden abgeschlossene Sprints, die in der
    Planung bearbeitet wurden (Fehltage oder Planning erfasst). None ohne solche Sprints."""
    if count <= 0:
        return None
    rates = []
    for sprint in past:
        if not sprint.absences and sprint.planning is None:
            continue
        without = copy.deepcopy(sprint)
        without.absences = {}
        full = sprint_capacity(team, people, without).gross
        if full <= 0:
            continue
        rates.append(1 - sprint_capacity(team, people, sprint).gross / full)
    rates = rates[-count:]
    return sum(rates) / len(rates) if rates else None


def estimated_capacity(team: Team, people: list[Person], sprint: Sprint, rate: float) -> float:
    """Kapazität eines Sprints ohne eingetragene Fehltage, gemindert um die erwarteten."""
    b = sprint_capacity(team, people, sprint)
    return round_down(max(b.gross * (1 - rate) - b.overhead, 0.0), team.capacity.rounding)


def capacity_with_expected_absences(team: Team, people: list[Person], sprint: Sprint) -> float:
    """Kapazität eines Sprints mit seinen voraussichtlichen Fehltagen (PO-Vorplanung)."""
    probe = copy.deepcopy(sprint)
    probe.absences = dict(sprint.expected_absences)
    return sprint_capacity(team, people, probe).capacity
