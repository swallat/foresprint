# SPDX-License-Identifier: EUPL-1.2
"""Data model: team configuration, people and sprints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit


class Unit(StrEnum):
    PT = "PT"
    SP = "SP"


class TrendMode(StrEnum):
    # Classic: 1st future sprint linear, 2nd multiplicative, then linear. Carries noise
    # forward, so only choose it explicitly.
    CLASSIC = "classic"
    # Linear projection of the rolling average throughout (like ``classic``).
    LINEAR = "linear"
    # Carry the last known average forward unchanged (default, robust).
    FLAT = "flat"

    @classmethod
    def _missing_(cls, value: object) -> TrendMode | None:
        # Older files still name the mode in German.
        return cls.CLASSIC if value == "klassisch" else None


class ProductBasis(StrEnum):
    # Default distribution per product from the whole Forecast PLAN ...
    PLAN = "plan"
    # ... or only from the plannable share (small items are not distributed over products).
    ROADMAP = "roadmap"


class AbsenceState(StrEnum):
    """State of a sprint's absences, which determines what the capacity is calculated with."""

    # Nothing known: capacity from calendar and people, absences estimated from history.
    UNKNOWN = "unknown"
    # Announced absences from the PO pre-planning (forecast, not confirmed).
    EXPECTED = "expected"
    # Absences confirmed, including "nobody is absent".
    CONFIRMED = "confirmed"


class Numbering(StrEnum):
    # 2026.1, 2026.2, ...; the counter restarts with the start year of a sprint.
    YEARLY = "yearly"
    # 1, 2, 3, …
    SEQUENTIAL = "sequential"


@dataclass
class SprintSettings:
    length_days: int = 14
    numbering: Numbering = Numbering.YEARLY
    # Only needed as long as no sprint is recorded yet.
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
    # Share of the capacity for Scrum events and the like, deducted as a flat amount.
    overhead_share: float = 0.0
    # The same deduction in PT per full-time person and sprint (× FTE), e.g. 1 for Planning,
    # Review and Retro. If set, it applies instead of the share (not in addition).
    overhead_days: float = 0.0
    # Country (ISO 3166-1, e.g. "DE", "US") and region within it (e.g. "NW", "CA") for holidays;
    # people can differ. The workweek follows the country ("auto") or is fixed
    # ("mon-fri", "sun-thu", "mon-sat").
    country: str = "DE"
    region: str | None = None
    workweek: str = "auto"
    rounding: int = 1
    # For future sprints without known absences: expect the average absences of the last this
    # many sprints with confirmed absences. 0 = no estimate (no deduction).
    absence_history: int = 4


@dataclass
class Features:
    """Optional areas that not every team needs, each switchable independently.
    For a new team all are off."""

    # Distribution of the sprint over several products (product list, PO pre-planning, Planning
    # and done per product, default distribution, balance).
    products: bool = False
    # Assignment of a PO to each product (PO column, totals per PO).
    po: bool = False
    # Topics with production access: people with permission, bottleneck hint, "of which" amounts.
    production: bool = False
    # Ticket pre-planning: projects, tickets from the tracker (CSV import), earmarks and the
    # distribution of tickets over future sprints (projects.yaml, tickets.yaml, preplan.yaml).
    tickets: bool = False
    # False: the file has no ``features`` section (older files); the values were derived from
    # the existing data so that nothing disappears.
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
    # Raw ``tracker`` section of team.yaml that could not be read while ``features.tickets`` is
    # off (not validated then); kept so that writing team.yaml does not drop it.
    tracker_raw: Any = field(default=None, compare=False, repr=False)


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
    # May work on tickets that require production access (small group of people).
    production_access: bool = False
    # The person's own country if different (holidays and weekend); otherwise the team's.
    country: str | None = None
    # The person's own workweek (e.g. "mon,tue,wed,thu" for a 4-day week); otherwise that of
    # the country or the team.
    workweek: str | None = None

    def fte_on(self, day: date) -> float:
        for m in self.memberships:
            if m.covers(day):
                return m.fte
        return 0.0

    def active_between(self, start: date, end: date) -> bool:
        return any(m.start < end and (m.end is None or m.end >= start) for m in self.memberships)

    def is_current(self, day: date) -> bool:
        """In the team today or in the future (i.e. has not left)."""
        return any(m.end is None or m.end >= day for m in self.memberships)


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def new_person_id(name: str, existing: set[str], fallback: str = "person") -> str:
    """Internal ID from the name, e.g. "Jörg Müller" → "joerg-mueller"; made unique."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(_UMLAUTS)).strip("-") or fallback
    candidate, n = slug, 2
    while candidate in existing:
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


@dataclass
class Product:
    """Product the team looks after. Like people, never delete, end with ``end`` instead."""

    id: str
    name: str
    # Responsible PO (optional, only for grouping).
    po: str | None = None
    start: date | None = None
    end: date | None = None
    # Agreed fixed share of the distributable amount (0-1), e.g. 0.1 = 10 %. If not given, the
    # products without a fixed share split the remainder evenly.
    share: float | None = None

    def active_between(self, start: date, end: date) -> bool:
        """Looked after in the sprint [start, end), on at least one day."""
        return (self.start is None or self.start < end) and (self.end is None or self.end >= start)


@dataclass
class ProductValues:
    """Values of a product in a sprint (the team's estimation unit); None = not specified."""

    # Provided for in the PO-side pre-planning (before Planning).
    preplanned: float | None = None
    # Scheduled in the sprint Planning.
    planned: float | None = None
    # Actually done in the sprint (Review).
    done: float | None = None
    # Of which tickets that require production access (subset of planned or done).
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
        """Scheduled amount according to the board: carryover + backlog (equals the Commitment)."""
        return self.carryover + self.backlog

    @property
    def total(self) -> float:
        """Planning total for the delta: scheduled minus the parts already done."""
        return self.committed - sum(self.corrections)


@dataclass
class Prognosis:
    """Team forecast for a still open sprint, recorded at a PO pre-planning.
    The pre-planning is done several times; every assumption stays traceable."""

    at: datetime
    # Where the assumption comes from (e.g. "forecast from the Daily of 16.10.").
    comment: str | None = None
    forecast_ist: float | None = None
    # Expected not done, or done in addition to the Commitment.
    not_done: float | None = None
    additional_done: float | None = None
    # Commitment − not done + additionally done.
    expected_done: float | None = None
    # Forecast PLAN of the target sprint with this assumption and the pre-planning provided for it.
    target: str | None = None
    plan: float | None = None
    preplanned: dict[str, float] = field(default_factory=dict)


@dataclass
class Sprint:
    id: str
    start: date
    end: date
    # Plannable absences per person (working days).
    absences: dict[str, float] = field(default_factory=dict)
    # Capacity in PT, recorded or frozen at the Review.
    capacity: float | None = None
    forecast_ist: float | None = None
    velocity: float | None = None
    scope_creep: float | None = None
    planning: Planning | None = None
    # Forecast PLAN at the time of Planning (frozen), the basis of the default distribution.
    forecast_plan: float | None = None
    # Values per product ID.
    products: dict[str, ProductValues] = field(default_factory=dict)
    note: str | None = None
    # Of which the amount with production access, if the team does not use a product
    # distribution (otherwise the values are per product in ``products``): scheduled in
    # Planning, done in Review.
    production_planned: float | None = None
    production_done: float | None = None
    # Recorded in the Review: amount that was not finished, or done in addition to the
    # Commitment (Velocity = Commitment − not done + additionally done).
    not_done: float | None = None
    additional_done: float | None = None
    # Explicitly stored state of the absences. ``None`` = not stored (older files): then it is
    # derived from the existing fields (see absence_status).
    absence_state: AbsenceState | None = None
    # Announced absences per person from the PO pre-planning (forecast, not yet confirmed):
    # they affect the capacity and the Forecast PLAN as long as no absences are confirmed.
    expected_absences: dict[str, float] = field(default_factory=dict)
    # Team forecasts from the PO pre-plannings, older first.
    prognoses: list[Prognosis] = field(default_factory=list)

    @property
    def absences_confirmed(self) -> bool:
        """Absences confirmed: entered, explicitly "nobody is absent", or (older files)
        derived from the existing fields."""
        return absence_status(self) is AbsenceState.CONFIRMED

    @absences_confirmed.setter
    def absences_confirmed(self, value: bool) -> None:
        if value:
            self.absence_state = AbsenceState.CONFIRMED
        elif self.absence_state is AbsenceState.CONFIRMED:
            self.absence_state = AbsenceState.UNKNOWN


def _legacy_known(sprint: Sprint) -> bool:
    """Older files without a stored state: absences counted as known if the sprint was already
    planned or evaluated. A file that contains only, e.g., the PO pre-planning or was created
    empty by accident does not confirm them."""
    return sprint.planning is not None or any(
        v is not None for v in (sprint.forecast_ist, sprint.velocity, sprint.forecast_plan)
    )


def explicit_state_needed(sprint: Sprint) -> bool:
    """Does the state need to be stored? Not needed if the older derivation from the fields would
    give the same result, so existing files stay unchanged when saving."""
    if sprint.absence_state is None:
        return False
    derived = replace(sprint, absence_state=None)
    return absence_status(sprint) is not absence_status(derived)


def absence_status(sprint: Sprint) -> AbsenceState:
    """State of the absences: confirmed, announced or unknown.

    Entered absences are confirmed. Otherwise the stored state applies; if it is missing (older
    files), it is derived from the existing fields. Announced absences only take effect as long
    as nothing is confirmed."""
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
    # A rough value (not refined, or refined status unclear); the conservative variant (step 4)
    # multiplies it by ``rough_factor``.
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


def base_url_problem(url: str) -> str | None:
    """Why ``tracker.base_url`` is unusable, or None: ``invalid`` (no http/https address, not
    parseable), ``credentials`` (user or password in the address) or ``extra`` (query or
    fragment). Never returns or raises with the address itself."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        return "invalid"
    if parts.scheme not in ("http", "https") or not host:
        return "invalid"
    if "@" in parts.netloc:
        return "credentials"
    if parts.query or parts.fragment or "?" in url or "#" in url:
        return "extra"
    return None


# Kinds of ticket sources (``tracker.kind``).
TRACKER_KINDS: tuple[str, ...] = ("csv", "jira")


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
    # Factor for rough estimates in the conservative variant (step 4); the distribution of
    # step 1 does not apply it.
    rough_factor: float = 1.5
    # Step 5: write ``planned_for_<sprint_id>`` labels to the tracker.
    write_labels: bool = False
    # Sprint names of the tracker → sprint ids of the tool, when they differ.
    sprint_names: dict[str, str] = field(default_factory=dict)
    # Jira: name of the issue link type whose inward side means "is blocked by".
    link_type: str = "Blocks"


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
