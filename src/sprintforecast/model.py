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
    # Ticket pre-planning: projects, tickets from the tracker (CSV import), earmarks and the
    # distribution of tickets over future sprints (projects.yaml, tickets.yaml, preplan.yaml).
    tickets: bool = False
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
    # Settings of the ticket pre-planning (section ``tracker`` in team.yaml); only used with
    # ``features.tickets``.
    tracker: TrackerSettings = field(default_factory=lambda: TrackerSettings())


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


# --- Ticket pre-planning ---------------------------------------------------------------
#
# Domain model of docs/design/ticket-planning.md (section 4): projects with assignment rules,
# tickets from the tracker, earmarks and manual estimates of the PO. The distribution itself
# (preplan.py) is not stored; it is recalculated from these objects and the forecast.


class EstimateSource(StrEnum):
    """Where a ticket's estimate comes from."""

    # Refinement: the ticket carries the refined label or fulfils ``tracker.refined_also_if``.
    REFINED = "refined"
    # A rough value (not refined, or refined status unclear); multiplied by ``rough_factor``.
    ROUGH = "rough"
    # Entered by the PO in preplan.yaml.
    MANUAL = "manual"
    # No estimate at all: the ticket is not distributed.
    NONE = "none"


class PlanningUses(StrEnum):
    """Which number the distribution calculates with (``tracker.planning_uses``)."""

    # Remaining effort if filled, otherwise the estimate (default).
    REMAINING = "remaining"
    # Always the estimate.
    ESTIMATE = "estimate"


class BudgetBasis(StrEnum):
    """What a sprint's budget for pre-planning is derived from."""

    # Forecast PLAN × plannable share (``forecast.roadmap_share``).
    ROADMAP_SHARE = "roadmap_share"
    # The whole forecast PLAN.
    PLAN = "plan"


# Sources a rule leaf can refer to; the ticket facts carry one value list per source.
RULE_SOURCES: tuple[str, ...] = ("epic", "component", "label", "status", "issue_type", "in_sprint")
# Operators of the long form; a leaf has the operator ``leaf``.
RULE_OPERATORS: tuple[str, ...] = ("any", "all", "none")
# Default order in which the sources decide between two matching projects.
DEFAULT_MATCH_ORDER: tuple[str, ...] = ("epic", "component", "label")


@dataclass
class Rule:
    """One node of an assignment rule (spec section 6.4).

    A leaf (``op == "leaf"``) names a source and a list of values; the values are OR-combined.
    An operator node (``any``, ``all``, ``none``) combines its children. The short form of
    projects.yaml (several sources directly under ``match:``) is an ``any`` node with
    ``short=True``; it is written back as the flat mapping. Unknown sources and operators
    without children are kept so that the validation can report them."""

    op: str = "leaf"
    source: str | None = None
    values: list[str] = field(default_factory=list)
    children: list[Rule] = field(default_factory=list)
    short: bool = False

    def matches(self, facts: dict[str, list[str]]) -> bool:
        """Does a ticket with these facts (see :meth:`Ticket.facts`) fulfil the rule?"""
        if self.op == "leaf":
            have = facts.get(self.source or "", [])
            return any(v in have for v in self.values)
        results = [child.matches(facts) for child in self.children]
        if self.op == "all":
            return all(results)
        if self.op == "none":
            return not any(results)
        return any(results)

    def leaf_sources(self) -> set[str]:
        """All sources the rule refers to (also unknown ones)."""
        if self.op == "leaf":
            return {self.source or ""}
        return set().union(*(child.leaf_sources() for child in self.children))

    def matched_sources(self, facts: dict[str, list[str]]) -> set[str]:
        """Sources of the leaves that the facts fulfil (``project_match_order`` decides between
        two matching projects by the source of the match)."""
        if self.op == "leaf":
            return {self.source or ""} if self.matches(facts) else set()
        if self.op == "none":
            return set()
        return set().union(*(child.matched_sources(facts) for child in self.children))

    def leaves(self) -> list[Rule]:
        """All leaves in document order."""
        if self.op == "leaf":
            return [self]
        return [leaf for child in self.children for leaf in child.leaves()]


@dataclass
class TrackerFields:
    """Display names of the tracker fields (as in the instance or the CSV export header)."""

    estimate: str | None = None
    remaining: str | None = None
    epic: str | None = None


@dataclass
class TrackerSettings:
    """Section ``tracker`` of team.yaml (spec section 6.1)."""

    kind: str = "csv"
    base_url: str | None = None
    query: str | None = None
    fields: TrackerFields = field(default_factory=TrackerFields)
    planning_uses: PlanningUses = PlanningUses.REMAINING
    # Label that marks a refined ticket; ``refined_also_if`` counts as refined without the label.
    refined_label: str | None = None
    refined_also_if: Rule | None = None
    project_match_order: list[str] = field(default_factory=lambda: list(DEFAULT_MATCH_ORDER))
    # 1 = a dependent ticket goes at least one sprint after its dependency, 0 = same sprint allowed.
    dependency_gap: int = 1
    budget_basis: BudgetBasis = BudgetBasis.ROADMAP_SHARE
    # Factor applied to rough estimates in the distribution.
    rough_factor: float = 1.5
    # Step 5: write ``planned_for_<sprint_id>`` labels to the tracker.
    write_labels: bool = False
    # Sprint names of the tracker → sprint ids of the tool, when they differ.
    sprint_names: dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    """An undertaking of the PO with target date, product and assignment rule (not a Jira
    project). A ticket belongs to the project whose rule it fulfils."""

    id: str
    name: str
    product: str | None = None
    target: date | None = None
    # Lower = more important when two projects share a target date.
    priority: int = 0
    # Overrides ``tracker.budget_basis`` for this project.
    budget_basis: BudgetBasis | None = None
    match: Rule | None = None
    note: str | None = None


@dataclass
class Ticket:
    """A unit of work as last imported from the tracker (tickets.yaml)."""

    key: str
    title: str = ""
    status: str | None = None
    issue_type: str | None = None
    estimate: float | None = None
    remaining: float | None = None
    estimate_source: EstimateSource = EstimateSource.NONE
    # Counts as refined only via ``refined_also_if``, or carries the label without an estimate.
    refined_unclear: bool = False
    # Real sprint according to the tracker, as sprint id of the tool (resolved on import).
    in_sprint: str | None = None
    # The sprint name as the tracker exports it (kept when it could not be resolved).
    sprint_name: str | None = None
    # Rank of the tracker (order within the backlog); compared as text.
    rank: str | None = None
    epic: str | None = None
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    # Keys of tickets that must be finished first.
    depends_on: list[str] = field(default_factory=list)
    project: str | None = None
    # Projects whose rules match via the same source (contradiction; ``project`` stays empty).
    project_candidates: list[str] = field(default_factory=list)
    done: bool = False

    def facts(self) -> dict[str, list[str]]:
        """The ticket's values per rule source. ``in_sprint`` carries ``true``/``false`` and,
        when set, the sprint id, so that ``in_sprint: [true]`` and ``in_sprint: [2026.22]``
        both work."""
        in_sprint = ["true", self.in_sprint] if self.in_sprint else ["false"]
        return {
            "epic": [self.epic] if self.epic else [],
            "component": list(self.components),
            "label": list(self.labels),
            "status": [self.status] if self.status else [],
            "issue_type": [self.issue_type] if self.issue_type else [],
            "in_sprint": in_sprint,
        }

    def size(self, uses: PlanningUses) -> float | None:
        """The number the distribution calculates with; ``None`` = unestimated."""
        if uses is PlanningUses.REMAINING and self.remaining is not None:
            return self.remaining
        return self.estimate


@dataclass
class Earmark:
    """Intent of the PO to put a ticket into a future sprint (preplan.yaml)."""

    ticket: str
    sprint: str
    note: str | None = None


@dataclass
class ManualEstimate:
    """Estimate entered by the PO for a ticket without (usable) estimate (preplan.yaml)."""

    ticket: str
    estimate: float | None = None
    note: str | None = None


@dataclass
class Preplan:
    """Content of preplan.yaml: earmarks and manual estimates, each at most once per ticket."""

    earmarks: list[Earmark] = field(default_factory=list)
    estimates: list[ManualEstimate] = field(default_factory=list)

    def earmark_for(self, key: str) -> Earmark | None:
        return next((e for e in self.earmarks if e.ticket == key), None)

    def estimate_for(self, key: str) -> ManualEstimate | None:
        return next((e for e in self.estimates if e.ticket == key), None)
