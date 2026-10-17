# SPDX-License-Identifier: EUPL-1.2
"""Kapazität eines Sprints aus Personenliste, Feiertagen und Fehltagen."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from sprintforecast.calendar import is_holiday, person_weekend, workdays
from sprintforecast.engine import round_down
from sprintforecast.model import AbsenceState, Person, Sprint, Team, absence_status


@dataclass
class PersonCapacity:
    person: Person
    workdays: int
    holidays: int
    absence_days: float
    # Verfügbar nach Feiertagen und Fehltagen (vor den Abzügen für Scrum-Termine).
    capacity: float
    mean_fte: float = 1.0
    # Die FTE wechselt im Sprint: Fehltage werden mit der mittleren FTE gewichtet (Näherung).
    fte_changes: bool = False
    # Fester Abzug für Scrum-Termine: PT je Person × FTE, höchstens die Kapazität.
    overhead: float = 0.0


@dataclass
class CapacityBreakdown:
    people: list[PersonCapacity] = field(default_factory=list)

    @property
    def approximated(self) -> list[PersonCapacity]:
        """Personen mit FTE-Wechsel im Sprint (Fehltage nur näherungsweise gewichtet)."""
        return [p for p in self.people if p.fte_changes and p.absence_days]

    gross: float = 0.0
    # Abzug Scrum-Termine gesamt = Anteil + feste PT
    overhead: float = 0.0
    overhead_share_part: float = 0.0
    overhead_days_part: float = 0.0
    capacity: float = 0.0


def person_capacity(
    team: Team, person: Person, sprint: Sprint, absence_rate: float = 0.0
) -> PersonCapacity | None:
    """Kapazität einer Person im Sprint in PT.

    FTE ist der Anteil an den Arbeitstagen der Person (siehe ``Person.workweek``): Wer vier
    Tage pro Woche arbeitet und das als ``workweek: mon,tue,wed,thu`` einträgt, hat FTE 1;
    ``fte: 0.8`` mit voller Arbeitswoche (Mo–Fr) ergibt dieselbe Kapazität. Beides zusammen
    (vier Tage und 0,8) würde doppelt abziehen.

    ``absence_rate`` mindert die Kapazität um einen erwarteten Anteil unbekannter Fehltage
    (Schätzung nach Historie); eingetragene Fehltage gelten zusätzlich."""
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
    """Kapazität des Sprints. Eine gemeinsame Rechnung für bestätigte, angekündigte und
    erwartete Fehltage: erst Feiertage und Fehltage (bzw. erwartete Quote) je Person, dann der
    Abzug für Scrum-Termine, dann die Rundung.

    Der Abzug: feste PT je Person (``overhead_days`` × FTE, höchstens die Kapazität der Person)
    ersetzen den Prozentabzug (``overhead_share``); beide sind derselbe Abzug in zwei Einheiten
    und werden nicht addiert."""
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


@dataclass(frozen=True)
class AbsenceHistory:
    """Ø Anteil der Kapazität, der in vergangenen Sprints durch Fehltage verloren ging."""

    rate: float | None
    # Die tatsächlich verwendeten Sprints (IDs, ältere zuerst) und ihre Quoten.
    sprints: list[str]
    rates: list[float]


def absence_history(
    team: Team, people: list[Person], past: list[Sprint], count: int
) -> AbsenceHistory:
    """Durchschnittlicher Verlust durch Fehltage in den letzten ``count`` Sprints.

    Berücksichtigt werden abgeschlossene Sprints, deren Fehltage **bestätigt** sind – dieselbe
    Definition wie für die Kapazität (``absence_status``). Bestätigte Sprints ohne Fehltage
    zählen mit der Quote 0 mit, sonst wäre die Quote zu hoch. Unbekannte und nur
    angekündigte Sprints bleiben außen vor."""
    if count <= 0:
        return AbsenceHistory(None, [], [])
    used: list[tuple[str, float]] = []
    for sprint in past:
        if absence_status(sprint) is not AbsenceState.CONFIRMED:
            continue
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
    )


def expected_absence_rate(
    team: Team, people: list[Person], past: list[Sprint], count: int
) -> float | None:
    """Ø Anteil der Kapazität, der durch Fehltage verloren ging (0–1); None ohne Historie."""
    return absence_history(team, people, past, count).rate


def estimated_capacity(team: Team, people: list[Person], sprint: Sprint, rate: float) -> float:
    """Kapazität eines Sprints ohne bekannte Fehltage, gemindert um die erwartete Quote."""
    return sprint_capacity(team, people, sprint, rate).capacity


def capacity_with_expected_absences(team: Team, people: list[Person], sprint: Sprint) -> float:
    """Kapazität eines Sprints mit seinen angekündigten Fehltagen (PO-Vorplanung)."""
    probe = copy.deepcopy(sprint)
    probe.absences = dict(sprint.expected_absences)
    return sprint_capacity(team, people, probe).capacity
