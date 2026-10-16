# SPDX-License-Identifier: EUPL-1.2
"""Datenmodell: Team-Konfiguration, Personen und Sprints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Unit(StrEnum):
    PT = "PT"
    SP = "SP"


class TrendMode(StrEnum):
    # Klassisch: 1. Zukunftssprint linear, 2. multiplikativ, danach linear.
    CLASSIC = "classic"
    # Durchgehend lineare Fortschreibung des gleitenden Durchschnitts.
    LINEAR = "linear"
    # Letzten bekannten Durchschnitt unverändert fortschreiben.
    FLAT = "flat"

    @classmethod
    def _missing_(cls, value: object) -> TrendMode | None:
        # Ältere Dateien nennen den Modus noch deutsch.
        return cls.CLASSIC if value == "klassisch" else None


class ProductBasis(StrEnum):
    # Standardverteilung je Produkt aus dem gesamten Forecast PLAN …
    PLAN = "plan"
    # … oder nur aus dem Roadmap-Anteil (Kleinkram wird nicht auf Produkte verteilt).
    ROADMAP = "roadmap"


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
    trend_mode: TrendMode = TrendMode.CLASSIC
    horizon: int = 3
    product_basis: ProductBasis = ProductBasis.PLAN


@dataclass
class CapacitySettings:
    # Anteil der Kapazität für Scrum-Termine u. Ä., der pauschal abgezogen wird.
    overhead_share: float = 0.0
    # Derselbe Abzug in PT je Vollzeitperson und Sprint (× FTE), z. B. 1 für Planning, Review
    # und Retro. Ist er gesetzt, gilt er statt des Anteils (nicht zusätzlich).
    overhead_days: float = 0.0
    # Bundesland-Kürzel für Feiertage (z. B. "NW", "BY"); Personen können abweichen.
    region: str | None = None
    rounding: int = 1
    # Für künftige Sprints ohne eingetragene Fehltage: die durchschnittlichen Fehltage der
    # letzten so vielen Sprints (aus den Plannings) erwarten. 0 = aus (Trend der Kapazität).
    absence_history: int = 0


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
    # Darf Tickets bearbeiten, die Produktionszugriff erfordern (kleine Personengruppe).
    production_access: bool = False

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


def new_person_id(name: str, existing: set[str], fallback: str = "person") -> str:
    """Interne ID aus dem Namen, z. B. „Jörg Müller“ → „joerg-mueller“; eindeutig gemacht."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(_UMLAUTS)).strip("-") or fallback
    candidate, n = slug, 2
    while candidate in existing:
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


@dataclass
class Product:
    """Produkt, das das Team betreut. Wie Personen nie löschen, sondern mit ``end`` beenden."""

    id: str
    name: str
    # Verantwortlicher PO (optional, nur zur Gruppierung).
    po: str | None = None
    start: date | None = None
    end: date | None = None
    # Vereinbarter fester Anteil an der verteilbaren Menge (0–1), z. B. 0.1 = 10 %. Ohne Angabe
    # teilen sich die Produkte ohne festen Anteil den Rest gleichmäßig.
    share: float | None = None

    def active_between(self, start: date, end: date) -> bool:
        """Betreut im Sprint [start, end) – mindestens an einem Tag."""
        return (self.start is None or self.start < end) and (self.end is None or self.end >= start)


@dataclass
class ProductValues:
    """Werte eines Produkts in einem Sprint (Schätzeinheit des Teams); None = keine Angabe."""

    # In der PO-seitigen Vorplanung vorgesehen (vor dem Planning).
    preplanned: float | None = None
    # Im Sprint Planning eingeplant.
    planned: float | None = None
    # Im Sprint tatsächlich erledigt (Review).
    done: float | None = None
    # Davon Tickets, die Produktionszugriff erfordern (Teilmenge von planned bzw. done).
    production_planned: float | None = None
    production_done: float | None = None

    def is_empty(self) -> bool:
        return all(
            v is None
            for v in (
                self.preplanned,
                self.planned,
                self.done,
                self.production_planned,
                self.production_done,
            )
        )


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
class Prognosis:
    """Prognose des Teams für einen noch offenen Sprint, festgehalten bei einer PO-Vorplanung.
    Die Vorplanung wird mehrfach durchgeführt – jede Annahme bleibt nachvollziehbar."""

    at: datetime
    # Woher die Annahme stammt (z. B. „Prognose aus dem Daily vom 16.10.“).
    comment: str | None = None
    forecast_ist: float | None = None
    # Voraussichtlich nicht erledigt bzw. zusätzlich zum Forecast IST erledigt.
    not_done: float | None = None
    additional_done: float | None = None
    # Forecast IST − nicht erledigt + zusätzlich erledigt.
    expected_done: float | None = None
    # Forecast PLAN des Zielsprints mit dieser Annahme und die dabei vorgesehene Vorplanung.
    target: str | None = None
    plan: float | None = None
    preplanned: dict[str, float] = field(default_factory=dict)


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
    # Forecast PLAN zum Zeitpunkt des Plannings (eingefroren) – Basis der Standardverteilung.
    forecast_plan: float | None = None
    # Werte je Produkt-ID.
    products: dict[str, ProductValues] = field(default_factory=dict)
    note: str | None = None
    # Im Review erfasst: Menge, die nicht fertig wurde, bzw. zusätzlich zum Forecast IST
    # erledigt wurde (Velocity = Forecast IST − nicht erledigt + zusätzlich erledigt).
    not_done: float | None = None
    additional_done: float | None = None
    # Prognosen des Teams aus den PO-Vorplanungen, ältere zuerst.
    prognoses: list[Prognosis] = field(default_factory=list)
