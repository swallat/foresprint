# SPDX-License-Identifier: EUPL-1.2
"""Datenmodell: Team-Konfiguration, Personen und Sprints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Unit(StrEnum):
    PT = "PT"
    SP = "SP"


class TrendMode(StrEnum):
    # Klassisch: 1. Zukunftssprint linear, 2. multiplikativ, danach linear.
    KLASSISCH = "klassisch"
    # Durchgehend lineare Fortschreibung des gleitenden Durchschnitts.
    LINEAR = "linear"
    # Letzten bekannten Durchschnitt unverändert fortschreiben.
    FLAT = "flat"


class Numbering(StrEnum):
    # 2026.1, 2026.2, …; Zähler beginnt mit dem Startjahr eines Sprints neu.
    YEARLY = "yearly"
    # 1, 2, 3, …
    SEQUENTIAL = "sequential"


@dataclass
class SprintSettings:
    length_days: int = 14
    numbering: Numbering = Numbering.YEARLY
    # Nur nötig, solange noch kein Sprint erfasst ist.
    first_id: str | None = None
    first_start: date | None = None


@dataclass
class ForecastSettings:
    reference_capacity: float = 67.0
    window: int = 5
    roadmap_share: float = 0.8
    rounding: int = 1
    trend_mode: TrendMode = TrendMode.KLASSISCH
    horizon: int = 3


@dataclass
class CapacitySettings:
    # Anteil der Kapazität für Scrum-Termine u. Ä., der pauschal abgezogen wird.
    overhead_share: float = 0.0
    # Bundesland-Kürzel für Feiertage (z. B. "NW", "BY"); Personen können abweichen.
    region: str | None = None
    rounding: int = 1


@dataclass
class Team:
    key: str
    name: str
    unit: Unit = Unit.PT
    sprint: SprintSettings = field(default_factory=SprintSettings)
    forecast: ForecastSettings = field(default_factory=ForecastSettings)
    capacity: CapacitySettings = field(default_factory=CapacitySettings)


@dataclass
class Membership:
    start: date
    end: date | None = None
    fte: float = 1.0

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass
class Person:
    id: str
    name: str
    region: str | None = None
    memberships: list[Membership] = field(default_factory=list)

    def fte_on(self, day: date) -> float:
        for m in self.memberships:
            if m.covers(day):
                return m.fte
        return 0.0

    def active_between(self, start: date, end: date) -> bool:
        return any(m.start < end and (m.end is None or m.end >= start) for m in self.memberships)

    def is_current(self, day: date) -> bool:
        """Heute oder künftig im Team (also nicht ausgeschieden)."""
        return any(m.end is None or m.end >= day for m in self.memberships)


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def new_person_id(name: str, existing: set[str]) -> str:
    """Interne ID aus dem Namen, z. B. „Jörg Müller“ → „joerg-mueller“; eindeutig gemacht."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(_UMLAUTS)).strip("-") or "person"
    candidate, n = slug, 2
    while candidate in existing:
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


@dataclass
class Planning:
    carryover: float = 0.0
    backlog: float = 0.0
    corrections: list[float] = field(default_factory=list)

    @property
    def committed(self) -> float:
        """Eingeplante Menge laut Board: Überkipper + Backlog (entspricht dem Forecast IST)."""
        return self.carryover + self.backlog

    @property
    def total(self) -> float:
        """Planning-Summe für das Delta: eingeplant abzüglich bereits erledigter Anteile."""
        return self.committed - sum(self.corrections)


@dataclass
class Sprint:
    id: str
    start: date
    end: date
    # Planbare Fehltage je Person (Arbeitstage).
    absences: dict[str, float] = field(default_factory=dict)
    # Erfasste bzw. beim Review eingefrorene Kapazität in PT.
    capacity: float | None = None
    forecast_ist: float | None = None
    velocity: float | None = None
    scope_creep: float | None = None
    planning: Planning | None = None
    note: str | None = None
