# SPDX-License-Identifier: EUPL-1.2
"""Distribution of the sprint quantity across the team's products.

Per product and sprint:
    Standard     = available quantity × the product's agreed share (share), or
                   (available quantity − Σ fixed shares) / number of products without a fixed share
                   available = Forecast PLAN (frozen at Planning, otherwise current)
                   or only its plannable part (setting forecast.product_basis)
    Pre-planning = intended on the PO side (before Planning)
    Planning     = scheduled in Sprint Planning
    Done         = actually completed, as recorded in Review
    Balance      = Σ Done − Σ Standard over several sprints
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sprintforecast.capacity import production_share
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import t
from sprintforecast.model import Features, Product, ProductBasis, ProductValues, Sprint

# Columns of the report: attribute → display name
MEASURES: dict[str, str] = {
    "standard": "Standard",
    "preplanned": "PO pre-planning",
    "planned": "Planning",
    "done": "Done",
}


# "Of which" values for tickets that require production access (subset of Planning/Done)
PRODUCTION_MEASURES: dict[str, str] = {
    "production_planned": "of which production access (planning)",
    "production_done": "of which production access (done)",
}


def measure_label(measure: str) -> str:
    """Display name of a measure in the configured language."""
    return t((MEASURES | PRODUCTION_MEASURES)[measure])


def sprint_products(products: list[Product], sprint: Sprint) -> list[Product]:
    """Products handled in the sprint plus those with recorded values (catalog order).
    Unknown IDs appear with the ID as their name so that no values disappear."""
    known = {p.id for p in products}
    result = [
        p
        for p in products
        if p.active_between(sprint.start, sprint.end)
        or not sprint.products.get(p.id, ProductValues()).is_empty()
    ]
    result += [Product(id=pid, name=pid) for pid in sprint.products if pid not in known]
    return result


@dataclass
class ProductRow:
    product: Product
    # Handled in the sprint: only these products get a standard share.
    active: bool
    standard: float | None
    preplanned: float | None
    planned: float | None
    done: float | None
    production_planned: float | None = None
    production_done: float | None = None

    def value(self, measure: str) -> float | None:
        return getattr(self, measure)


@dataclass
class Distribution:
    sprint: Sprint
    # Forecast PLAN of the sprint and whether it was frozen at Planning.
    plan: float | None
    plan_frozen: bool
    basis: ProductBasis
    # Distributable quantity (Forecast PLAN or its plannable part).
    available: float | None
    rows: list[ProductRow] = field(default_factory=list)
    # Share of capacity held by people with production access (None = no group) and the
    # quantity this group can handle in the sprint (share × Forecast PLAN).
    production_share: float | None = None
    production_available: float | None = None
    # Is anybody marked as authorized at all? Without any mark the configuration is unknown,
    # which is different from "authorized people are not available in this sprint".
    production_configured: bool = False
    # Which areas the team uses (controls columns and hints in the UI).
    features: Features = field(default_factory=Features)
    # Currently calculated Forecast PLAN (differs from ``plan`` if that one is frozen).
    current_plan: float | None = None

    @property
    def production_state(self) -> str:
        """``unconfigured`` (nobody marked), ``unavailable`` (authorized people marked, but
        without capacity in the sprint) or ``ok``."""
        if not self.production_configured:
            return "unconfigured"
        if not self.production_share:
            return "unavailable"
        return "ok"

    @property
    def production_overload(self) -> float | None:
        """By how much the Planning with production access exceeds the group (else None)."""
        planned = self.total("production_planned")
        if planned is None or self.production_available is None:
            return None
        over = planned - self.production_available
        return over if over > 0.05 else None

    @property
    def active_count(self) -> int:
        return sum(1 for r in self.rows if r.active)

    def total(self, measure: str) -> float | None:
        values = [v for r in self.rows if (v := r.value(measure)) is not None]
        if not values and measure in PRODUCTION_MEASURES:
            # Teams without a product distribution record the production-access quantities per
            # sprint.
            return getattr(self.sprint, measure)
        return sum(values) if values else None

    def has(self, measure: str) -> bool:
        return any(r.value(measure) is not None for r in self.rows)


def plan_of(entry: TimelineEntry) -> tuple[float | None, bool]:
    """Forecast PLAN of a sprint: frozen at Planning, otherwise as currently calculated."""
    if entry.sprint.forecast_plan is not None:
        return entry.sprint.forecast_plan, True
    return entry.result.plan, False


@dataclass(frozen=True)
class PlanView:
    """Both states of a sprint's Forecast PLAN: currently calculated and frozen at Planning
    (None until frozen)."""

    current: float | None
    frozen: float | None

    @property
    def difference(self) -> float | None:
        """Current − at Planning; None without a frozen or current value."""
        if self.current is None or self.frozen is None:
            return None
        return self.current - self.frozen


def plan_view(entry: TimelineEntry) -> PlanView:
    return PlanView(current=entry.result.plan, frozen=entry.sprint.forecast_plan)


def standard_shares(active: list[Product], available: float | None) -> dict[str, float]:
    """Standard quantity per handled product: fixed shares first, the rest evenly."""
    if available is None or not active:
        return {}
    fixed = {p.id: available * p.share for p in active if p.share is not None}
    rest = [p for p in active if p.share is None]
    left = max(available - sum(fixed.values()), 0.0)
    return fixed | {p.id: left / len(rest) for p in rest}


def distribution(fc: Forecast, entry: TimelineEntry) -> Distribution:
    data = fc.data
    sprint = entry.sprint
    basis = data.team.forecast.product_basis
    plan, frozen = plan_of(entry)
    available = plan
    if plan is not None and basis is ProductBasis.ROADMAP:
        available = plan * data.team.forecast.roadmap_share
    products = sprint_products(data.products, sprint)
    known = {p.id for p in data.products}
    active = [p for p in products if p.id in known and p.active_between(sprint.start, sprint.end)]
    shares = standard_shares(active, available)
    rows = []
    for p in products:
        values = sprint.products.get(p.id, ProductValues())
        is_active = p in active
        rows.append(
            ProductRow(
                product=p,
                active=is_active,
                standard=shares.get(p.id) if is_active else None,
                preplanned=values.preplanned,
                planned=values.planned,
                done=values.done,
                production_planned=values.production_planned,
                production_done=values.production_done,
            )
        )
    group = production_share(data.team, data.people, sprint)
    return Distribution(
        sprint=sprint,
        plan=plan,
        plan_frozen=frozen,
        basis=basis,
        available=available,
        rows=rows,
        production_configured=any(p.production_access for p in data.people),
        features=data.team.features,
        production_share=group,
        production_available=plan * group if plan is not None and group is not None else None,
        current_plan=entry.result.plan,
    )


def missing_footnote() -> str:
    """Footnote for the "no value" column (terminal and report; plain text, no markup)."""
    return t(
        '"no value": sprints in which the product was worked on but no done value is '
        "entered, although it is entered for other products (empty, not 0). They do not "
        "count towards the balance; please add the value in the sprint. Sprints without "
        "any done value (e.g. the current one) and sprints outside the product's period "
        "are left out."
    )


@dataclass
class Balance:
    product: Product
    sprints: int
    standard: float
    done: float
    # Sprints in which no "Done" is recorded for the product (missing ≠ 0): not counted.
    missing: int = 0

    @property
    def difference(self) -> float:
        """Positive = more done than the standard share."""
        return self.done - self.standard


def balance(fc: Forecast, entries: list[TimelineEntry]) -> list[Balance]:
    """Balance per product over the sprints in which Done was recorded for the product. A
    missing value does not count as 0; such sprints are counted (``missing``) and contribute
    neither to Done nor to the standard."""
    order = {p.id: i for i, p in enumerate(fc.data.products)}
    sums: dict[str, Balance] = {}
    for e in entries:
        d = distribution(fc, e)
        if not d.has("done"):
            continue
        for r in d.rows:
            if r.standard is None and r.done is None:
                continue
            b = sums.setdefault(r.product.id, Balance(r.product, 0, 0.0, 0.0))
            if r.done is None:  # value missing: count neither as 0 nor with the standard
                b.missing += 1
                continue
            b.sprints += 1
            b.standard += r.standard or 0.0
            b.done += r.done
    return sorted(sums.values(), key=lambda b: order.get(b.product.id, len(order)))


def by_po(d: Distribution) -> list[tuple[str, dict[str, float | None]]]:
    """Totals per PO (only if at least one product has a PO)."""
    if not any(r.product.po for r in d.rows):
        return []
    groups: dict[str, list[ProductRow]] = {}
    for r in d.rows:
        groups.setdefault(r.product.po or t("(no PO)"), []).append(r)
    result = []
    for po, rows in groups.items():
        totals: dict[str, float | None] = {}
        for m in MEASURES:
            values = [v for r in rows if (v := r.value(m)) is not None]
            totals[m] = sum(values) if values else None
        result.append((po, totals))
    return result
