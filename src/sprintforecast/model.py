# SPDX-License-Identifier: EUPL-1.2
"""Datenmodell: Team-Konfiguration, Personen und Sprints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum


class Unit(StrEnum):
    PT = "PT"
    SP = "SP"


class TrendMode(StrEnum):
    # Klassisch: 1. Zukunftssprint linear, 2. multiplikativ, danach linear. Schreibt Rauschen
    # fort – nur ausdrücklich wählen.
    CLASSIC = "classic"
    # Durchgehend lineare Fortschreibung des gleitenden Durchschnitts (wie ``classic``).
    LINEAR = "linear"
    # Letzten bekannten Durchschnitt unverändert fortschreiben (Standard, robust).
    FLAT = "flat"

    @classmethod
    def _missing_(cls, value: object) -> TrendMode | None:
        # Ältere Dateien nennen den Modus noch deutsch.
        return cls.CLASSIC if value == "klassisch" else None


class ProductBasis(StrEnum):
    # Standardverteilung je Produkt aus dem gesamten Forecast PLAN …
    PLAN = "plan"
    # … oder nur aus dem verplanbaren Anteil (Kleinkram wird nicht auf Produkte verteilt).
    ROADMAP = "roadmap"


class AbsenceState(StrEnum):
    """Stand der Fehltage eines Sprints – bestimmt, womit die Kapazität gerechnet wird."""

    # Nichts bekannt: Kapazität aus Kalender und Personen, Fehltage nach Historie geschätzt.
    UNKNOWN = "unknown"
    # Angekündigte Fehltage aus der PO-Vorplanung (Prognose, nicht bestätigt).
    EXPECTED = "expected"
    # Fehltage bestätigt – auch „niemand fehlt“.
    CONFIRMED = "confirmed"


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
    trend_mode: TrendMode = TrendMode.FLAT
    horizon: int = 3
    product_basis: ProductBasis = ProductBasis.PLAN


@dataclass
class CapacitySettings:
    # Anteil der Kapazität für Scrum-Termine u. Ä., der pauschal abgezogen wird.
    overhead_share: float = 0.0
    # Derselbe Abzug in PT je Vollzeitperson und Sprint (× FTE), z. B. 1 für Planning, Review
    # und Retro. Ist er gesetzt, gilt er statt des Anteils (nicht zusätzlich).
    overhead_days: float = 0.0
    # Land (ISO 3166-1, z. B. "DE", "US") und Region darin (z. B. "NW", "CA") für die Feiertage;
    # Personen können abweichen. Die Arbeitswoche folgt dem Land ("auto") oder ist festgelegt
    # ("mon-fri", "sun-thu", "mon-sat").
    country: str = "DE"
    region: str | None = None
    workweek: str = "auto"
    rounding: int = 1
    # Für künftige Sprints ohne bekannte Fehltage: die durchschnittlichen Fehltage der letzten so
    # vielen Sprints mit bestätigten Fehltagen erwarten. 0 = keine Schätzung (ohne Abzug).
    absence_history: int = 4


@dataclass
class Features:
    """Optionale Bereiche, die nicht jedes Team braucht – unabhängig voneinander zuschaltbar.
    Bei einem neuen Team sind alle aus."""

    # Verteilung des Sprints auf mehrere Produkte (Produktliste, PO-Vorplanung, Planning und
    # Erledigt je Produkt, Standardverteilung, Saldo).
    products: bool = False
    # Zuordnung eines PO zu jedem Produkt (Spalte PO, Summen je PO).
    po: bool = False
    # Themen mit Produktionszugriff: Personen mit Berechtigung, Engpass-Hinweis, davon-Mengen.
    production: bool = False
    # False: Die Datei hat keinen Abschnitt ``features`` (ältere Dateien) – die Werte wurden
    # aus den vorhandenen Daten abgeleitet, damit nichts verschwindet.
    explicit: bool = True


@dataclass
class Team:
    key: str
    name: str
    unit: Unit = Unit.PT
    sprint: SprintSettings = field(default_factory=SprintSettings)
    forecast: ForecastSettings = field(default_factory=ForecastSettings)
    capacity: CapacitySettings = field(default_factory=CapacitySettings)
    features: Features = field(default_factory=Features)


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
    # Abweichendes Land der Person (Feiertage und Wochenende); sonst das des Teams.
    country: str | None = None
    # Eigene Arbeitswoche der Person (z. B. "mon,tue,wed,thu" bei einer 4-Tage-Woche); sonst die
    # des Landes bzw. des Teams.
    workweek: str | None = None

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
        """Eingeplante Menge laut Board: Überkipper + Backlog (entspricht dem Commitment)."""
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
    # Voraussichtlich nicht erledigt bzw. zusätzlich zum Commitment erledigt.
    not_done: float | None = None
    additional_done: float | None = None
    # Commitment − nicht erledigt + zusätzlich erledigt.
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
    # Davon Menge mit Produktionszugriff, wenn das Team keine Produktverteilung nutzt (sonst
    # stehen die Werte je Produkt in ``products``): im Planning eingeplant, im Review erledigt.
    production_planned: float | None = None
    production_done: float | None = None
    # Im Review erfasst: Menge, die nicht fertig wurde, bzw. zusätzlich zum Commitment
    # erledigt wurde (Velocity = Commitment − nicht erledigt + zusätzlich erledigt).
    not_done: float | None = None
    additional_done: float | None = None
    # Ausdrücklich gespeicherter Stand der Fehltage. ``None`` = nicht gespeichert (ältere
    # Dateien): dann wird er aus den vorhandenen Feldern abgeleitet (siehe absence_status).
    absence_state: AbsenceState | None = None
    # Angekündigte Fehltage je Person aus der PO-Vorplanung (Prognose, noch nicht bestätigt):
    # Sie wirken auf die Kapazität und den Forecast PLAN, solange keine Fehltage bestätigt sind.
    expected_absences: dict[str, float] = field(default_factory=dict)
    # Prognosen des Teams aus den PO-Vorplanungen, ältere zuerst.
    prognoses: list[Prognosis] = field(default_factory=list)

    @property
    def absences_confirmed(self) -> bool:
        """Fehltage bestätigt: eingetragen, ausdrücklich „niemand fehlt“ oder (ältere Dateien)
        aus den vorhandenen Feldern abgeleitet."""
        return absence_status(self) is AbsenceState.CONFIRMED

    @absences_confirmed.setter
    def absences_confirmed(self, value: bool) -> None:
        if value:
            self.absence_state = AbsenceState.CONFIRMED
        elif self.absence_state is AbsenceState.CONFIRMED:
            self.absence_state = AbsenceState.UNKNOWN


def _legacy_known(sprint: Sprint) -> bool:
    """Ältere Dateien ohne gespeicherten Stand: Fehltage galten als bekannt, wenn der Sprint
    schon geplant bzw. ausgewertet wurde. Eine Datei, die nur z. B. die PO-Vorplanung enthält
    oder versehentlich leer entstanden ist, bestätigt sie nicht."""
    return sprint.planning is not None or any(
        v is not None for v in (sprint.forecast_ist, sprint.velocity, sprint.forecast_plan)
    )


def explicit_state_needed(sprint: Sprint) -> bool:
    """Muss der Stand gespeichert werden? Nicht nötig, wenn die ältere Ableitung aus den Feldern
    dasselbe ergäbe – so bleiben vorhandene Dateien beim Speichern unverändert."""
    if sprint.absence_state is None:
        return False
    derived = replace(sprint, absence_state=None)
    return absence_status(sprint) is not absence_status(derived)


def absence_status(sprint: Sprint) -> AbsenceState:
    """Stand der Fehltage: bestätigt, angekündigt oder unbekannt.

    Eingetragene Fehltage sind bestätigt. Sonst gilt der gespeicherte Stand; fehlt er (ältere
    Dateien), wird er aus den vorhandenen Feldern abgeleitet. Angekündigte Fehltage
    wirken nur, solange nichts bestätigt ist."""
    if sprint.absences or sprint.absence_state is AbsenceState.CONFIRMED:
        return AbsenceState.CONFIRMED
    if sprint.absence_state is None and _legacy_known(sprint):
        return AbsenceState.CONFIRMED
    return AbsenceState.EXPECTED if sprint.expected_absences else AbsenceState.UNKNOWN
