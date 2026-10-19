# SPDX-License-Identifier: EUPL-1.2
"""Ticket pre-planning: distribution of tickets over future sprints (spec section 5).

Pure computation on top of the forecast; nothing here is stored. The core (storage, model,
validate, forecast) never imports this module.

    Budget[s, p]  = share[p] × base[s]  −  fixed points (tickets in the sprint according to
                    the tracker, earmarks)  −  tickets placed by the distribution
    base[s]       = Forecast PLAN × plannable share (``budget_basis: roadmap_share``) or the
                    whole Forecast PLAN (``plan``); per team, overridable per project
    Order         = projects by target date, priority and id; tickets by rank; dependencies
                    first (topological)
    Placement     = earliest sprint from (latest sprint of the dependencies + ``dependency_gap``)
                    whose free budget for the product suffices
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sprintforecast.analysis import HorizonEntry, horizon_entries, horizon_forecast
from sprintforecast.capacity import production_share
from sprintforecast.engine import round_down
from sprintforecast.forecast import lookup_sprint
from sprintforecast.model import (
    BudgetBasis,
    EstimateSource,
    Product,
    Project,
    Sprint,
    Ticket,
)
from sprintforecast.products import standard_shares
from sprintforecast.storage import TeamData
from sprintforecast.validate import find_cycles

# Traffic light per project (spec section 5.3): display texts, translated with t() on display.
LIGHTS: dict[str, str] = {
    "on_track": "im Plan",
    "tight": "knapp",
    "missed": "verfehlt",
    "empty": "leer",
}

# Why a ticket is in its sprint, or why it is not distributable.
REASONS: dict[str, str] = {
    "placed": "verteilt",
    "fixed_sprint": "Sprint laut Ticketsystem",
    "earmark": "Vormerkung",
    "unestimated": "ungeschätzt",
    "too_large": "zu groß, bitte teilen",
    "no_budget": "kein Budget",
    "no_project": "ohne Projekt",
    "cycle": "Abhängigkeiten im Kreis",
    "blocked": "Abhängigkeit nicht verteilbar",
    "beyond_horizon": "außerhalb des Zeitraums",
}

# Where the estimate the distribution calculates with comes from.
SOURCES: dict[str, str] = {
    "refined": "refined",
    "rough": "grob geschätzt",
    "manual": "eigene Schätzung",
    "none": "ohne Schätzung",
}

# Reasons of a ticket that is in a sprint (fixed or distributed).
PLACED_REASONS = frozenset({"placed", "fixed_sprint", "earmark"})

# Tolerance for the budget comparison (floating point).
_EPS = 1e-9
# Product key of a ticket without known project (matches no budget).
_NO_PRODUCT = "\0no-product"


@dataclass
class Budget:
    """What a sprint can take on for one product."""

    sprint: str
    # Product id; None = the implicit product of a team without ``features.products``.
    product: str | None
    # Plannable amount by the team's ``tracker.budget_basis``.
    base: float
    # The same amount by the whole Forecast PLAN and by its plannable share (for projects that
    # override the basis).
    plan: float
    roadmap: float
    # Consumed by tickets that are in the sprint according to the tracker and by earmarks.
    fixed: float = 0.0
    # Consumed by the distribution.
    placed: float = 0.0
    # What the people with production access can do in the sprint (only reported, never added).
    production_available: float | None = None

    def limit(self, basis: BudgetBasis | None = None) -> float:
        """The plannable amount by ``basis`` (None = the team's basis)."""
        if basis is BudgetBasis.PLAN:
            return self.plan
        if basis is BudgetBasis.ROADMAP_SHARE:
            return self.roadmap
        return self.base

    def free_for(self, basis: BudgetBasis | None = None) -> float:
        """What is left for a project with ``basis``; negative = the fixed points overflow."""
        return self.limit(basis) - self.fixed - self.placed

    @property
    def free(self) -> float:
        return self.free_for(None)


@dataclass
class Placement:
    """Where a ticket ended up and why (one per open ticket)."""

    ticket: str
    # None = not distributable (see ``reason``).
    sprint: str | None
    reason: str
    # Number the distribution calculated with; None = unestimated.
    size: float | None = None
    source: EstimateSource = EstimateSource.NONE
    project: str | None = None

    @property
    def distributable(self) -> bool:
        return self.reason in PLACED_REASONS


@dataclass
class ProjectStatus:
    """Traffic light of a project (spec section 5.3)."""

    project: str
    light: str
    # Last sprint ending on or before the target date (the current sprint when the target lies
    # inside it); None without target date or when it lies outside the horizon.
    target_sprint: str | None
    # Sprint of the project's last ticket; None without placed tickets.
    last_sprint: str | None
    open_tickets: int
    not_distributable: int


@dataclass
class RefinementItem:
    """A ticket that has to be refined before its sprint is planned (spec section 5.4)."""

    ticket: str
    sprint: str
    # Planning of the sprint = sprint start.
    deadline: date
    source: EstimateSource
    # Refined status unclear (spec section 6.3).
    unclear: bool = False


@dataclass
class Distribution:
    """Result of :func:`distribute`."""

    # Future sprints of the horizon in order.
    sprints: list[str]
    budgets: list[Budget] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    projects: list[ProjectStatus] = field(default_factory=list)
    refinement: list[RefinementItem] = field(default_factory=list)
    # Open tickets with unclear refined status (listed separately from the refinement list).
    unclear: list[str] = field(default_factory=list)
    # Dependency cycles (keys in dependency order), each once.
    cycles: list[list[str]] = field(default_factory=list)
    # Sprints of fixed tickets or earmarks that lie after the horizon or are unknown (later
    # than everything the distribution knows) -> their last day; None = unknown sprint.
    later: dict[str, date | None] = field(default_factory=dict)
    # True when no sprint of the horizon has any budget at all (no past sprints, no forecast).
    no_forecast: bool = False

    def placement(self, key: str) -> Placement | None:
        return next((p for p in self.placements if p.ticket == key), None)

    def budget(self, sprint: str, product: str | None) -> Budget | None:
        return next((b for b in self.budgets if b.sprint == sprint and b.product == product), None)

    def status(self, project_id: str) -> ProjectStatus | None:
        return next((s for s in self.projects if s.project == project_id), None)

    def in_sprint(self, sprint: str) -> list[Placement]:
        return [p for p in self.placements if p.sprint == sprint]

    def not_distributable(self) -> list[Placement]:
        return [p for p in self.placements if not p.distributable]


# --- Budget ---------------------------------------------------------------------------------


def plan_of(entry: HorizonEntry, data: TeamData) -> float | None:
    """Forecast PLAN of a horizon sprint. Beyond the people list the plan is recalculated with
    the average capacity of the last sprints (like ``analysis.completion``)."""
    if not entry.trend:
        return entry.entry.result.plan
    n_trend = entry.entry.result.normalized_velocity.trend
    if n_trend is None:
        return entry.entry.result.plan
    settings = data.team.forecast
    plan = round_down(n_trend / settings.reference_capacity * entry.capacity, settings.rounding)
    return max(plan, 0.0)


def base_amount(
    plan: float | None, basis: BudgetBasis, share: float, roadmap_share: float
) -> float:
    """Plannable amount of one product in one sprint: its share of the Forecast PLAN, by
    ``basis`` reduced to the plannable share of the team."""
    if plan is None:
        return 0.0
    amount = plan * share
    return amount * roadmap_share if basis is BudgetBasis.ROADMAP_SHARE else amount


def active_products(products: list[Product], sprint: Sprint) -> list[Product]:
    return [p for p in products if p.active_between(sprint.start, sprint.end)]


def product_shares(data: TeamData, sprint: Sprint) -> dict[str | None, float]:
    """Share of each product in a sprint (sum 1). Without ``features.products`` the team has
    one implicit product (key None) that takes everything."""
    if not data.team.features.products:
        return {None: 1.0}
    return dict(standard_shares(active_products(data.products, sprint), 1.0))


def budgets(data: TeamData, horizon: list[HorizonEntry]) -> list[Budget]:
    """Budget per horizon sprint and product, before fixed points and distribution."""
    team = data.team
    result = []
    for h in horizon:
        plan = plan_of(h, data)
        group = None
        if team.features.production and plan is not None:
            group = production_share(team, data.people, h.sprint)
        for product, share in product_shares(data, h.sprint).items():
            whole = base_amount(plan, BudgetBasis.PLAN, share, team.forecast.roadmap_share)
            roadmap = base_amount(
                plan, BudgetBasis.ROADMAP_SHARE, share, team.forecast.roadmap_share
            )
            result.append(
                Budget(
                    sprint=h.sprint.id,
                    product=product,
                    base=whole if team.tracker.budget_basis is BudgetBasis.PLAN else roadmap,
                    plan=whole,
                    roadmap=roadmap,
                    production_available=None if group is None else whole * group,
                )
            )
    return result


# --- Order ----------------------------------------------------------------------------------


def project_order(projects: list[Project]) -> list[Project]:
    """Projects by target date (without target last), priority and id."""
    return sorted(
        projects, key=lambda p: (p.target is None, p.target or date.min, p.priority, p.id)
    )


def ticket_order(tickets: list[Ticket]) -> list[Ticket]:
    """Tickets by rank (as text, without rank last), then key."""
    return sorted(tickets, key=lambda tk: (tk.rank is None, tk.rank or "", tk.key))


def order_tickets(data: TeamData) -> tuple[list[Ticket], list[Ticket]]:
    """Open tickets in distribution order: by project (target date, priority), within a project
    by rank, tickets without project last; dependencies always before their successors (Kahn).
    Second list: tickets that cannot be ordered because they are in a dependency cycle or
    depend on one (in the same order)."""
    open_tickets = [tk for tk in data.tickets if not tk.done]
    by_project: dict[str | None, list[Ticket]] = {}
    for tk in open_tickets:
        by_project.setdefault(tk.project, []).append(tk)
    sequence: list[Ticket] = []
    for project in project_order(data.projects):
        sequence += ticket_order(by_project.pop(project.id, []))
    # Tickets of unknown projects and without project (not distributable, but reported).
    for key in sorted(by_project, key=lambda k: (k is None, k or "")):
        sequence += ticket_order(by_project[key])

    known = {tk.key for tk in open_tickets}
    ordered: list[Ticket] = []
    placed: set[str] = set()
    pending = list(sequence)
    while pending:
        pick = next(
            (tk for tk in pending if all(d in placed or d not in known for d in tk.depends_on)),
            None,
        )
        if pick is None:
            break
        pending.remove(pick)
        ordered.append(pick)
        placed.add(pick.key)
    return ordered, pending


# --- Size -----------------------------------------------------------------------------------


def ticket_size(ticket: Ticket, data: TeamData) -> tuple[float | None, EstimateSource]:
    """The number the distribution calculates with and where it comes from: the ticket's
    size by ``tracker.planning_uses``; a manual estimate of the PO replaces a missing size.
    Rough values count as they are: ``tracker.rough_factor`` belongs to the conservative
    variant (step 4), not to this distribution."""
    size = ticket.size(data.team.tracker.planning_uses)
    if size is None:
        manual = data.preplan.estimate_for(ticket.key)
        if manual is not None and manual.estimate is not None:
            return manual.estimate, EstimateSource.MANUAL
        return None, EstimateSource.NONE
    return size, ticket.estimate_source


# --- Distribution ---------------------------------------------------------------------------


def distribute(data: TeamData, today: date, max_sprints: int = 26) -> Distribution:
    """Distributes the open tickets over the future sprints (spec section 5)."""
    fc = horizon_forecast(data, today, max_sprints)
    horizon = horizon_entries(fc, max_sprints)
    sprints = [h.sprint for h in horizon]
    index = {s.id: i for i, s in enumerate(sprints)}
    budget_list = budgets(data, horizon)
    by_cell = {(b.sprint, b.product): b for b in budget_list}
    products = {p.id: p.product for p in data.projects}
    basis_of = {p.id: p.budget_basis or data.team.tracker.budget_basis for p in data.projects}
    gap = data.team.tracker.dependency_gap
    current = fc.current.sprint if fc.current is not None else None
    known_sprints: dict[str, Sprint | None] = {}

    def sprint_of_id(sprint_id: str) -> Sprint | None:
        if sprint_id not in known_sprints:
            known_sprints[sprint_id] = lookup_sprint(fc, sprint_id)
        return known_sprints[sprint_id]

    def ended(sprint_id: str) -> bool:
        """A sprint that is already over (the tracker keeps closed sprints on carried-over
        tickets, and tickets.yaml outlives the import by days)."""
        sprint = sprint_of_id(sprint_id)
        return sprint is not None and sprint.end <= today

    def position(sprint_id: str) -> int:
        """Position of a sprint relative to the horizon: its index; -1 = before it (current
        or past sprint); ``len(sprints)`` = after it or unknown."""
        if sprint_id in index:
            return index[sprint_id]
        sprint = sprint_of_id(sprint_id)
        if sprint is not None and (not sprints or sprint.start < sprints[0].start):
            return -1
        return len(sprints)

    def product_of(project_id: str | None) -> str | None:
        """Product whose budget a ticket of the project consumes. Without the products
        feature every ticket counts against the one implicit product, also without project;
        with it, a ticket without (known) project counts against no product."""
        if project_id in products:
            return products[project_id]
        return None if not data.team.features.products else _NO_PRODUCT

    ordered, leftover = order_tickets(data)
    open_tickets = ordered + leftover
    known = {tk.key for tk in open_tickets}
    in_cycle = {key for cycle in find_cycles(open_tickets) for key in cycle}
    placements: dict[str, Placement] = {}

    # Fixed points: real sprint according to the tracker, then earmarks of the PO.
    for tk in open_tickets:
        earmark = data.preplan.earmark_for(tk.key)
        # A sprint of the tracker that is over does not count: earmark or distribution apply.
        tracker_sprint = tk.in_sprint if tk.in_sprint and not ended(tk.in_sprint) else None
        if tracker_sprint is not None:
            sprint, reason = tracker_sprint, "fixed_sprint"
        elif earmark is not None and not ended(earmark.sprint):
            # An earmark of a sprint that is over would put an open ticket into the past.
            sprint, reason = earmark.sprint, "earmark"
        else:
            continue
        size, source = ticket_size(tk, data)
        placements[tk.key] = Placement(tk.key, sprint, reason, size, source, tk.project)
        cell = by_cell.get((sprint, product_of(tk.project)))
        if cell is not None and size is not None:
            cell.fixed += size

    def sprint_index(key: str) -> int | None:
        """Position of a placed ticket (see ``position``); None = not placed."""
        p = placements.get(key)
        if p is None or p.sprint is None:
            return None
        return position(p.sprint)

    for tk in ordered:
        if tk.key in placements:
            continue
        size, source = ticket_size(tk, data)
        placement = Placement(tk.key, None, "placed", size, source, tk.project)
        placements[tk.key] = placement
        if tk.project is None or tk.project not in products:
            placement.reason = "no_project"
            continue
        if size is None:
            placement.reason = "unestimated"
            continue
        first = 0
        for dep in tk.depends_on:
            if dep not in known:
                continue  # done or unknown ticket: nothing to wait for
            dep_index = sprint_index(dep)
            if dep_index is None:
                placement.reason = "blocked"
                break
            first = max(first, dep_index + gap)
        if placement.reason == "blocked":
            continue
        product, basis = products[tk.project], basis_of[tk.project]
        cells = [c for s in sprints if (c := by_cell.get((s.id, product))) is not None]
        best = max((c.limit(basis) for c in cells), default=0.0)
        if size > best + _EPS:
            # No budget at all (no forecast, or no budget cell of the product) is not the
            # ticket's fault; only a ticket above every positive budget is too large.
            placement.reason = "no_budget" if best <= _EPS else "too_large"
            continue
        for s in sprints[first:]:
            cell = by_cell.get((s.id, product))
            if cell is not None and cell.free_for(basis) + _EPS >= size:
                cell.placed += size
                placement.sprint = s.id
                break
        else:
            placement.reason = "beyond_horizon"

    for tk in leftover:
        if tk.key in placements:
            continue
        size, source = ticket_size(tk, data)
        reason = "cycle" if tk.key in in_cycle else "blocked"
        placements[tk.key] = Placement(tk.key, None, reason, size, source, tk.project)

    result = Distribution(
        sprints=[s.id for s in sprints],
        budgets=budget_list,
        placements=[placements[tk.key] for tk in data.tickets if tk.key in placements],
        cycles=find_cycles(open_tickets),
        later={
            p.sprint: _last_day(sprint_of_id(p.sprint))
            for p in placements.values()
            if p.sprint is not None and position(p.sprint) >= len(sprints)
        },
        no_forecast=not any(b.plan > _EPS for b in budget_list),
    )
    length = data.team.sprint.length_days
    result.projects = [
        traffic_light(p, result, sprints, length, current, today)
        for p in project_order(data.projects)
    ]
    result.refinement = refinement_list(data, result, sprints)
    result.unclear = [tk.key for tk in open_tickets if tk.refined_unclear]
    return result


def sprint_sums(dist: Distribution, sprint: str) -> dict[str | None, float]:
    """Amount per product that the tickets take up in ``sprint`` (tickets of the tracker, earmarks
    and distributed tickets). Empty when the sprint is not in the horizon."""
    return {b.product: b.fixed + b.placed for b in dist.budgets if b.sprint == sprint}


# --- Traffic light and refinement list ------------------------------------------------------


def _last_day(sprint: Sprint | None) -> date | None:
    return None if sprint is None else sprint.end - timedelta(days=1)


def _later_position(last_day: date | None, target: date | None, size: int, length_days: int) -> int:
    """Position in the timeline of a sprint after the horizon (``size`` = length of the
    timeline = the target sprint when the target lies beyond the horizon): later than the
    target unless the sprint is known and ends by the target date."""
    if last_day is None or target is None or last_day > target:
        return size + 1
    # The target sprint is the last one ending on or before the target date.
    return size if target < last_day + timedelta(days=length_days) else size - 1


def target_sprint(
    target: date | None,
    sprints: list[Sprint],
    length_days: int,
    current: Sprint | None = None,
    today: date | None = None,
) -> int | None:
    """Index of the last sprint of the timeline whose last day lies on or before ``target``
    (the sprint end is exclusive); None without target date or when no sprint ends by then.
    The timeline is the current sprint (when given) followed by the horizon sprints. A target
    inside the current sprint (and not yet over) is the current sprint itself. ``len(timeline)``
    = the target sprint lies beyond the horizon (the sprint after the last one would end by the
    target as well)."""
    timeline = ([current] if current is not None else []) + sprints
    if not timeline or target is None:
        return None
    if (
        current is not None
        and current.start <= target < current.end - timedelta(days=1)
        and (today is None or target >= today)
    ):
        return 0
    if timeline[-1].end + timedelta(days=length_days - 1) <= target:
        return len(timeline)
    ending = [i for i, s in enumerate(timeline) if s.end - timedelta(days=1) <= target]
    return ending[-1] if ending else None


def traffic_light(
    project: Project,
    dist: Distribution,
    sprints: list[Sprint],
    length_days: int = 14,
    current: Sprint | None = None,
    today: date | None = None,
) -> ProjectStatus:
    """Traffic light of a project from the placements of its tickets (spec section 5.3).
    ``length_days`` (sprint length of the team) tells whether a target date lies beyond the
    horizon; ``current`` is the running sprint: work placed in it counts as on time for a
    target date inside it. Tickets fixed or earmarked after the horizon (``dist.later``) are
    compared with the target date by the last day of their sprint (an unknown sprint counts as
    later than the target)."""
    own = [p for p in dist.placements if p.project == project.id]
    timeline = ([current] if current is not None else []) + sprints
    index = {s.id: i for i, s in enumerate(timeline)}
    target = target_sprint(project.target, sprints, length_days, current, today)
    target_id = timeline[target].id if target is not None and target < len(timeline) else None
    undistributed = [p for p in own if not p.distributable]
    last: int | None = None
    last_id = None
    for p in own:
        if p.sprint is None:
            continue
        # Not in the timeline: a sprint after the horizon (or unknown) or a past one.
        i = index.get(p.sprint, -1)
        if p.sprint not in index and p.sprint in dist.later:
            i = _later_position(dist.later[p.sprint], project.target, len(timeline), length_days)
        if last is None or i > last:
            last, last_id = i, p.sprint
    if not own:
        light = "empty"
    elif undistributed:
        light = "missed"
    elif project.target is None:
        light = "on_track"
    elif target is None:
        light = "missed"  # the target date lies before the first sprint of the timeline
    elif last is None or last < target:
        light = "on_track"
    elif last == target:
        light = "tight"
    else:
        light = "missed"
    return ProjectStatus(
        project=project.id,
        light=light,
        target_sprint=target_id,
        last_sprint=last_id,
        open_tickets=len(own),
        not_distributable=len(undistributed),
    )


def refinement_list(
    data: TeamData, dist: Distribution, sprints: list[Sprint]
) -> list[RefinementItem]:
    """Per future sprint the tickets whose estimate is rough or manual; deadline = planning
    of the sprint (spec section 5.4)."""
    result = []
    for s in sprints:
        for p in dist.in_sprint(s.id):
            if p.source not in (EstimateSource.ROUGH, EstimateSource.MANUAL):
                continue
            ticket = data.ticket(p.ticket)
            result.append(
                RefinementItem(
                    ticket=p.ticket,
                    sprint=s.id,
                    deadline=s.start,
                    source=p.source,
                    unclear=ticket.refined_unclear if ticket is not None else False,
                )
            )
    return result
