# SPDX-License-Identifier: EUPL-1.2
"""Ticket pre-planning: distribution of tickets over future sprints (spec section 5).

Pure computation on top of the forecast; nothing here is stored. The core (storage, model,
validate, forecast) never imports this module.

    Budget[s, p]  = share[p] × base[s]  −  fixed points (tickets in the sprint according to
                    the tracker, earmarks)  −  tickets placed by the distribution
    base[s]       = Forecast PLAN × plannable share (``budget_basis: roadmap_share``) or the
                    whole Forecast PLAN (``plan``); per team, overridable per project
    Order         = tickets by priority, then project (target date, priority) and rank; dependencies
                    first (topological)
    Placement     = earliest sprint from (latest sprint of the dependencies + ``dependency_gap``)
                    whose free budget for the product suffices
    Variants      = the same distribution with a conservative, median and optimistic plan per
                    sprint (spec section 5.5); "median" is the Forecast PLAN as the forecast
                    shows it, the others recalculate the plan like ``analysis.band``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from foresprint.analysis import (
    HorizonEntry,
    horizon_entries,
    horizon_forecast,
    normalized_history,
    plan_at,
)
from foresprint.capacity import production_share
from foresprint.engine import round_down, round_half_up
from foresprint.forecast import Forecast, lookup_sprint
from foresprint.model import (
    BudgetBasis,
    EstimateSource,
    Product,
    Project,
    Sprint,
    Ticket,
)
from foresprint.products import standard_shares
from foresprint.storage import TeamData
from foresprint.ticket_import import assign_project
from foresprint.validate import find_cycles

# Traffic light per project (spec section 5.3): display texts, translated with t() on display.
LIGHTS: dict[str, str] = {
    "on_track": "on track",
    "tight": "tight",
    "missed": "missed",
    "empty": "empty",
    "backlog": "no target date",  # the tickets of a product without a project
}


class Variant(StrEnum):
    """Which plan per sprint the distribution calculates with (spec section 5.5)."""

    CONSERVATIVE = "conservative"
    # The Forecast PLAN as the forecast shows it.
    MEDIAN = "median"
    OPTIMISTIC = "optimistic"


# Display names of the variants: translated with t() on display.
VARIANT_NAMES: dict[str, str] = {
    "conservative": "conservative",
    "median": "median",
    "optimistic": "optimistic",
}

# Order of the traffic lights from good to bad (``empty`` = project without open tickets).
LIGHT_ORDER: tuple[str, ...] = ("empty", "on_track", "tight", "missed")

# Why a ticket is in its sprint, or why it is not distributable.
REASONS: dict[str, str] = {
    "placed": "distributed",
    "fixed_sprint": "sprint according to the tracker",
    "earmark": "earmark",
    "unestimated": "unestimated",
    "too_large": "too large, please split",
    "no_budget": "no budget",
    "no_product": "without product",
    "cycle": "circular dependencies",
    "blocked": "dependency not distributable",
    "beyond_horizon": "beyond the horizon",
}

# Where the estimate the distribution calculates with comes from.
SOURCES: dict[str, str] = {
    "refined": "refined",
    "rough": "rough estimate",
    "manual": "own estimate",
    "none": "no estimate",
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
    # Product whose budget the ticket uses (its project's, else by a product rule); None =
    # none found, or the team has no product distribution.
    product: str | None = None

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
    # The variant this distribution was calculated for.
    variant: Variant = Variant.MEDIAN

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


def variant_plans(data: TeamData, horizon: list[HorizonEntry], nvel: float) -> dict[str, float]:
    """Plan of every horizon sprint for the normalized velocity ``nvel``: calculated like
    ``analysis.band`` (capacity of the sprint; beyond the people list the average capacity of
    the last sprints, as in ``plan_of``)."""
    settings = data.team.forecast
    return {h.sprint.id: max(plan_at(settings, nvel, h.capacity), 0.0) for h in horizon}


def budgets(
    data: TeamData, horizon: list[HorizonEntry], plans: dict[str, float] | None = None
) -> list[Budget]:
    """Budget per horizon sprint and product, before fixed points and distribution. ``plans``
    replaces the Forecast PLAN per sprint id (variants); without it the plan of ``plan_of``
    counts."""
    team = data.team
    result = []
    for h in horizon:
        plan = plan_of(h, data) if plans is None else plans.get(h.sprint.id)
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


def ticket_product(ticket: Ticket, data: TeamData) -> tuple[str | None, list[str]]:
    """``(product id, candidates)`` whose budget a ticket uses. A ticket of a known project
    takes the project's product; otherwise the product rules decide (like the project rules,
    by ``tracker.project_match_order``; several products via the same source contradict: no
    product, all of them as candidates). Without ``features.products`` there is only the one
    implicit product: ``(None, [])``."""
    if not data.team.features.products:
        return None, []
    project = data.project(ticket.project) if ticket.project else None
    if project is not None and project.product:
        return project.product, []
    return assign_project(ticket.facts(), data.products, data.team.tracker.project_match_order)


def product_conflict(ticket: Ticket, data: TeamData) -> str | None:
    """The product a product rule assigns although the ticket's project belongs to another
    one (the project wins); None = no contradiction."""
    project = data.project(ticket.project) if ticket.project else None
    if project is None or not project.product or not data.team.features.products:
        return None
    other, _ = assign_project(ticket.facts(), data.products, data.team.tracker.project_match_order)
    return other if other is not None and other != project.product else None


def ticket_order(tickets: list[Ticket]) -> list[Ticket]:
    """Tickets by rank (as text, without rank last), then key."""
    return sorted(tickets, key=lambda tk: (tk.rank is None, tk.rank or "", tk.key))


def priority_rank(priority: str | None, order: list[str]) -> int:
    """Position of a tracker priority in ``tracker.priority_order`` (case-insensitive; 0 =
    most important). Without or with an unknown priority: after all named ones. An empty
    order ignores the priority: every ticket gets the same rank."""
    if not order:
        return 0
    names = [name.casefold() for name in order]
    return (
        names.index(priority.casefold())
        if priority and priority.casefold() in names
        else len(names)
    )


def order_tickets(data: TeamData) -> tuple[list[Ticket], list[Ticket]]:
    """Open tickets in distribution order: by ticket priority (``tracker.priority_order``),
    then by the ticket's unit, its project (target date, project priority) or, without a
    project, its product's own tickets (after the projects), then by rank. So a ticket
    without project can overtake a lower-priority ticket of a project. Tickets without project
    and product last; dependencies always before their successors (Kahn). Second list:
    tickets that cannot be ordered because they are in a dependency cycle or depend on one
    (in the same order)."""
    open_tickets = [tk for tk in data.tickets if not tk.done]
    projects = {p.id: p for p in data.projects}
    order = data.team.tracker.priority_order
    keyed: list[tuple[tuple, Ticket]] = []
    unassigned: list[Ticket] = []
    for tk in open_tickets:
        if tk.project in projects:
            pr = projects[tk.project or ""]
            unit = (pr.target is None, pr.target or date.min, pr.priority, pr.id)
        else:
            product, _ = ticket_product(tk, data)
            if product is None and data.team.features.products:
                unassigned.append(tk)
                continue
            unit = (True, date.max, 0, product or "")
        keyed.append(
            ((priority_rank(tk.priority, order), *unit, tk.rank is None, tk.rank or "", tk.key), tk)
        )
    sequence: list[Ticket] = [tk for _, tk in sorted(keyed, key=lambda kv: kv[0])]
    # Tickets without project and product (not distributable, but reported).
    for key in sorted({tk.project for tk in unassigned}, key=lambda k: (k is None, k or "")):
        sequence += ticket_order([tk for tk in unassigned if tk.project == key])

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


def ticket_size(
    ticket: Ticket, data: TeamData, rough_factor: float = 1.0
) -> tuple[float | None, EstimateSource]:
    """The number the distribution calculates with and where it comes from: the ticket's
    size by ``tracker.planning_uses``; a manual estimate of the PO replaces a missing size.
    Values count as they are unless ``rough_factor`` (the conservative variant passes
    ``tracker.rough_factor``) is given: it multiplies rough estimates and estimates of
    tickets whose refined status is unclear; refined and manual estimates are not inflated."""
    size = ticket.size(data.team.tracker.planning_uses)
    if size is None:
        manual = data.preplan.estimate_for(ticket.key)
        if manual is not None and manual.estimate is not None:
            return manual.estimate, EstimateSource.MANUAL
        return None, EstimateSource.NONE
    source = ticket.estimate_source
    if rough_factor != 1.0 and (
        source is EstimateSource.ROUGH
        or (ticket.refined_unclear and source is not EstimateSource.MANUAL)
    ):
        size *= rough_factor
    return size, source


# --- Distribution ---------------------------------------------------------------------------


def variant_velocity(history: list[float], variant: Variant) -> float | None:
    """Normalized velocity a variant calculates with: the lowest (conservative) or highest
    (optimistic) of the history like ``analysis.band``; None for the median (the Forecast
    PLAN counts) and when the history is too short for a range (fewer than two values)."""
    if variant is Variant.MEDIAN or len(history) < 2:
        return None
    return min(history) if variant is Variant.CONSERVATIVE else max(history)


def distribute(
    data: TeamData,
    today: date,
    max_sprints: int = 26,
    variant: Variant | str = Variant.MEDIAN,
) -> Distribution:
    """Distributes the open tickets over the future sprints (spec section 5).

    ``variant`` changes only the plan per sprint: ``median`` is the Forecast PLAN as the
    forecast shows it; ``conservative`` and ``optimistic`` recalculate it from the lowest and
    highest normalized velocity of the history (and need at least two values, otherwise a
    ``ValueError`` is raised; :func:`distribute_variants` handles that case). The conservative
    variant also inflates rough estimates by ``tracker.rough_factor``."""
    variant = Variant(variant)
    fc = horizon_forecast(data, today, max_sprints)
    horizon = horizon_entries(fc, max_sprints)
    nvel = variant_velocity(normalized_history(fc), variant)
    if variant is not Variant.MEDIAN and nvel is None:
        raise ValueError(f"variant {variant.value} needs at least two sprints with velocity")
    return _distribute(data, today, fc, horizon, variant, nvel)


def _distribute(
    data: TeamData,
    today: date,
    fc: Forecast,
    horizon: list[HorizonEntry],
    variant: Variant,
    nvel: float | None,
) -> Distribution:
    sprints = [h.sprint for h in horizon]
    index = {s.id: i for i, s in enumerate(sprints)}
    budget_list = budgets(
        data, horizon, None if nvel is None else variant_plans(data, horizon, nvel)
    )
    rough_factor = data.team.tracker.rough_factor if variant is Variant.CONSERVATIVE else 1.0
    by_cell = {(b.sprint, b.product): b for b in budget_list}
    default_basis = data.team.tracker.budget_basis
    basis_of = {p.id: p.budget_basis or default_basis for p in data.projects}
    resolved: dict[str, str | None] = {}

    def resolve(tk: Ticket) -> str | None:
        if tk.key not in resolved:
            resolved[tk.key] = ticket_product(tk, data)[0]
        return resolved[tk.key]

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

    def product_of(tk: Ticket) -> str | None:
        """Product whose budget a ticket uses. Without the products feature every ticket
        counts against the one implicit product; with it, a ticket without product counts
        against no product."""
        product = resolve(tk)
        return product if product is not None or not data.team.features.products else _NO_PRODUCT

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
        size, source = ticket_size(tk, data, rough_factor)
        placements[tk.key] = Placement(
            tk.key, sprint, reason, size, source, tk.project, resolve(tk)
        )
        cell = by_cell.get((sprint, product_of(tk)))
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
        size, source = ticket_size(tk, data, rough_factor)
        placement = Placement(tk.key, None, "placed", size, source, tk.project, resolve(tk))
        placements[tk.key] = placement
        if product_of(tk) == _NO_PRODUCT:
            placement.reason = "no_product"
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
        product, basis = resolve(tk), basis_of.get(tk.project or "", default_basis)
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
        size, source = ticket_size(tk, data, rough_factor)
        reason = "cycle" if tk.key in in_cycle else "blocked"
        placements[tk.key] = Placement(tk.key, None, reason, size, source, tk.project, resolve(tk))

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
        variant=variant,
    )
    length = data.team.sprint.length_days
    result.projects = [
        traffic_light(p, result, sprints, length, current, today)
        for p in project_order(data.projects)
    ]
    result.refinement = refinement_list(data, result, sprints)
    result.unclear = [tk.key for tk in open_tickets if tk.refined_unclear]
    return result


def sprint_sums(dist: Distribution, sprint: str, data: TeamData) -> dict[str | None, float]:
    """Amount per product that the tickets take up in ``sprint`` (tickets of the tracker, earmarks
    and distributed tickets). A sprint outside the horizon (e.g. the one starting today) has no
    budget; there only the tickets that sit in it according to the tracker or an earmark count."""
    cells = {b.product: b.fixed + b.placed for b in dist.budgets if b.sprint == sprint}
    if cells:
        return cells
    sums: dict[str | None, float] = {}
    for p in dist.placements:
        if p.sprint != sprint or p.size is None:
            continue
        product = p.product if data.team.features.products else None
        if product is None and data.team.features.products:
            continue
        sums[product] = sums.get(product, 0.0) + p.size
    return sums


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


# --- Variants and range (spec section 5.5) ---------------------------------------------------


@dataclass
class Variants:
    """The distribution under the three plans. The conservative and optimistic variants are
    None when the range is unavailable (fewer than two sprints with velocity)."""

    median: Distribution
    conservative: Distribution | None = None
    optimistic: Distribution | None = None
    # Sprints with normalized velocity the range is calculated from.
    samples: int = 0

    @property
    def available(self) -> bool:
        """The range can be shown (all three variants exist)."""
        return self.conservative is not None and self.optimistic is not None

    def get(self, variant: Variant | str) -> Distribution | None:
        return {
            Variant.CONSERVATIVE: self.conservative,
            Variant.MEDIAN: self.median,
            Variant.OPTIMISTIC: self.optimistic,
        }[Variant(variant)]

    def items(self) -> list[tuple[Variant, Distribution]]:
        """The existing variants from optimistic to conservative."""
        order = (Variant.OPTIMISTIC, Variant.MEDIAN, Variant.CONSERVATIVE)
        return [(v, d) for v in order if (d := self.get(v)) is not None]


def distribute_variants(data: TeamData, today: date, max_sprints: int = 26) -> Variants:
    """The distribution under the median (Forecast PLAN), conservative (lowest normalized
    velocity, rough estimates inflated by ``tracker.rough_factor``) and optimistic plan. With
    fewer than two sprints with velocity there is no range: only the median is returned."""
    fc = horizon_forecast(data, today, max_sprints)
    horizon = horizon_entries(fc, max_sprints)
    history = normalized_history(fc)
    median = _distribute(data, today, fc, horizon, Variant.MEDIAN, None)
    if len(history) < 2:
        return Variants(median, samples=len(history))
    return Variants(
        median,
        conservative=_distribute(
            data, today, fc, horizon, Variant.CONSERVATIVE,
            variant_velocity(history, Variant.CONSERVATIVE),
        ),
        optimistic=_distribute(
            data, today, fc, horizon, Variant.OPTIMISTIC,
            variant_velocity(history, Variant.OPTIMISTIC),
        ),
        samples=len(history),
    )  # fmt: skip


def sprint_key(dist: Distribution, sprint_id: str) -> tuple[int, int]:
    """Sort key of a sprint within a distribution: before the horizon (current or past sprint),
    the horizon sprints in order, then sprints after the horizon by their last day (an unknown
    sprint last)."""
    if sprint_id in dist.sprints:
        return 1, dist.sprints.index(sprint_id)
    if sprint_id in dist.later:
        last = dist.later[sprint_id]
        return 2, (last or date.max).toordinal()
    return 0, 0


def _light_rank(light: str) -> int:
    return LIGHT_ORDER.index(light)


@dataclass
class ProjectRange:
    """Traffic light and last sprint of a project under every variant."""

    project: str
    # False: only the median exists (too little history), the range is that single value.
    available: bool
    # Per variant; only the variants that exist.
    last_sprint: dict[Variant, str | None]
    light: dict[Variant, str]
    # Earliest and latest last sprint over the variants (greedy placement is not monotone
    # across variants, so this is the minimum and maximum, not optimistic and conservative).
    earliest: str | None
    latest: str | None
    # Best and worst traffic light over the variants (on_track < tight < missed).
    best_light: str
    worst_light: str
    # False: in at least one variant a ticket of the project is not distributable, so
    # ``latest`` is only the last sprint of the tickets that were placed.
    complete: bool = True

    @property
    def light_range(self) -> tuple[str, str]:
        return self.best_light, self.worst_light

    @property
    def uniform(self) -> bool:
        """All variants have the same traffic light."""
        return self.best_light == self.worst_light

    @property
    def on_track(self) -> bool:
        """On track in the range sense: in every variant."""
        return self.worst_light == "on_track"


def project_range(variants: Variants, project_id: str) -> ProjectRange:
    """Range of the project's last sprint and traffic light over the variants of ``variants``."""
    rows: list[tuple[Variant, Distribution, ProjectStatus]] = []
    for variant, dist in variants.items():
        status = dist.status(project_id)
        if status is None:
            raise KeyError(project_id)
        rows.append((variant, dist, status))
    placed = [(d, st.last_sprint) for _, d, st in rows if st.last_sprint is not None]
    keyed = sorted(placed, key=lambda x: sprint_key(x[0], x[1]))
    lights = [st.light for _, _, st in rows]
    return ProjectRange(
        project=project_id,
        available=variants.available,
        last_sprint={v: st.last_sprint for v, _, st in rows},
        light={v: st.light for v, _, st in rows},
        earliest=keyed[0][1] if keyed else None,
        latest=keyed[-1][1] if keyed else None,
        best_light=min(lights, key=_light_rank),
        worst_light=max(lights, key=_light_rank),
        complete=all(st.not_distributable == 0 for _, _, st in rows),
    )


@dataclass
class TicketRange:
    """Sprint of one ticket under every variant."""

    ticket: str
    # Per variant; None = not placed in that variant.
    sprints: dict[Variant, str | None]
    # Earliest and latest sprint over the variants that placed the ticket.
    earliest: str | None
    latest: str | None
    # False: at least one variant did not place the ticket.
    complete: bool = True

    @property
    def fixed(self) -> bool:
        """The ticket is in the same sprint in every variant."""
        return self.complete and self.earliest == self.latest


def ticket_range(variants: Variants, key: str) -> TicketRange | None:
    """Earliest and latest sprint of a ticket over the variants; None for a ticket the
    distribution does not know (done or unknown)."""
    if variants.median.placement(key) is None:
        return None
    found: list[tuple[Distribution, str | None, Variant]] = []
    for variant, dist in variants.items():
        placement = dist.placement(key)
        found.append((dist, placement.sprint if placement else None, variant))
    placed = sorted(
        ((d, sp) for d, sp, _ in found if sp is not None), key=lambda x: sprint_key(x[0], x[1])
    )
    return TicketRange(
        ticket=key,
        sprints={v: sp for _, sp, v in found},
        earliest=placed[0][1] if placed else None,
        latest=placed[-1][1] if placed else None,
        complete=all(sp is not None for _, sp, _ in found),
    )


# --- Handover to the PO pre-planning (spec section 10, step 4) -------------------------------


@dataclass
class HandoverRow:
    """What the distribution proposes as ``preplanned`` for one sprint and product."""

    sprint: str
    product: str
    # Sum of the sizes of the tickets in the sprint, rounded to the team's precision.
    proposed: float
    # The value the PO pre-planning holds today; None = nothing entered (or no sprint file).
    current: float | None = None

    def action(self, overwrite: bool = False) -> str:
        """``write`` (nothing entered yet), ``same`` (already equal), ``overwrite`` (a different
        value entered and ``overwrite``) or ``keep`` (a different value entered: stays)."""
        if self.current is None:
            return "write"
        if abs(self.current - self.proposed) < 1e-9:
            return "same"
        return "overwrite" if overwrite else "keep"

    def writes(self, overwrite: bool = False) -> bool:
        return self.action(overwrite) in ("write", "overwrite")


def handover_rows(data: TeamData, dist: Distribution, sprint_count: int = 6) -> list[HandoverRow]:
    """Per future sprint (the first ``sprint_count`` of the horizon) and product the sum of
    the sizes of the tickets placed there (distributed, earmarked and fixed by the tracker),
    as the distribution used them. Tickets without a known product are left out;
    sums that round to nothing are left out. Pure: nothing is written."""
    known = {p.id for p in data.products}
    shown = dist.sprints[:sprint_count]
    sums: dict[tuple[str, str], float] = {}
    for p in dist.placements:
        if p.reason not in PLACED_REASONS or p.sprint not in shown or p.size is None:
            continue
        product = p.product
        if product is None or product not in known:
            continue
        sums[(p.sprint, product)] = sums.get((p.sprint, product), 0.0) + p.size
    digits = data.team.forecast.rounding
    order = {p.id: i for i, p in enumerate(data.products)}
    rows = []
    for (sprint_id, product), total in sorted(
        sums.items(), key=lambda kv: (shown.index(kv[0][0]), order[kv[0][1]])
    ):
        proposed = round_half_up(total, digits)
        if proposed <= 0:
            continue
        sprint = data.sprint(sprint_id)
        values = sprint.products.get(product) if sprint is not None else None
        rows.append(
            HandoverRow(sprint_id, product, proposed, values.preplanned if values else None)
        )
    return rows
