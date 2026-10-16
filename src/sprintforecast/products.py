# SPDX-License-Identifier: EUPL-1.2
"""Verteilung der Sprint-Menge auf die Produkte des Teams.

Je Produkt und Sprint:
    Standard     = verfügbare Menge / Anzahl betreuter Produkte
                   verfügbar = Forecast PLAN (eingefroren beim Planning, sonst aktuell)
                   bzw. nur dessen Roadmap-Anteil (Einstellung forecast.product_basis)
    Vorplanung   = PO-seitig vorgesehen (vor dem Planning)
    Planning     = im Sprint Planning eingeplant
    Erledigt     = im Review tatsächlich erledigt
    Saldo        = Σ Erledigt − Σ Standard über mehrere Sprints
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.model import Product, ProductBasis, ProductValues, Sprint

# Spalten der Auswertung: Attribut → Anzeigename
MEASURES: dict[str, str] = {
    "standard": "Standard",
    "preplanned": "PO-Vorplanung",
    "planned": "Planning",
    "done": "Erledigt",
}


def sprint_products(products: list[Product], sprint: Sprint) -> list[Product]:
    """Im Sprint betreute Produkte plus solche, für die Werte erfasst sind (Katalogreihenfolge).
    Unbekannte IDs erscheinen mit der ID als Namen, damit keine Werte verschwinden."""
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
    # Im Sprint betreut – nur diese Produkte bekommen einen Standardanteil.
    active: bool
    standard: float | None
    preplanned: float | None
    planned: float | None
    done: float | None

    def value(self, measure: str) -> float | None:
        return getattr(self, measure)


@dataclass
class Distribution:
    sprint: Sprint
    # Forecast PLAN des Sprints und ob er beim Planning eingefroren wurde.
    plan: float | None
    plan_frozen: bool
    basis: ProductBasis
    # Verteilbare Menge (Forecast PLAN oder dessen Roadmap-Anteil).
    available: float | None
    rows: list[ProductRow] = field(default_factory=list)

    @property
    def active_count(self) -> int:
        return sum(1 for r in self.rows if r.active)

    def total(self, measure: str) -> float | None:
        values = [v for r in self.rows if (v := r.value(measure)) is not None]
        return sum(values) if values else None

    def has(self, measure: str) -> bool:
        return any(r.value(measure) is not None for r in self.rows)


def plan_of(entry: TimelineEntry) -> tuple[float | None, bool]:
    """Forecast PLAN eines Sprints: beim Planning eingefroren, sonst wie aktuell berechnet."""
    if entry.sprint.forecast_plan is not None:
        return entry.sprint.forecast_plan, True
    return entry.result.plan, False


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
    share = available / len(active) if available is not None and active else None
    rows = []
    for p in products:
        values = sprint.products.get(p.id, ProductValues())
        is_active = p in active
        rows.append(
            ProductRow(
                product=p,
                active=is_active,
                standard=share if is_active else None,
                preplanned=values.preplanned,
                planned=values.planned,
                done=values.done,
            )
        )
    return Distribution(
        sprint=sprint, plan=plan, plan_frozen=frozen, basis=basis, available=available, rows=rows
    )


@dataclass
class Balance:
    product: Product
    sprints: int
    standard: float
    done: float

    @property
    def difference(self) -> float:
        """Positiv = mehr erledigt als der Standardanteil."""
        return self.done - self.standard


def balance(fc: Forecast, entries: list[TimelineEntry]) -> list[Balance]:
    """Saldo je Produkt über die Sprints, in denen Erledigt erfasst wurde."""
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
            b.sprints += 1
            b.standard += r.standard or 0.0
            b.done += r.done or 0.0
    return sorted(sums.values(), key=lambda b: order.get(b.product.id, len(order)))


def by_po(d: Distribution) -> list[tuple[str, dict[str, float | None]]]:
    """Summen je PO (nur wenn mindestens ein Produkt einen PO hat)."""
    if not any(r.product.po for r in d.rows):
        return []
    groups: dict[str, list[ProductRow]] = {}
    for r in d.rows:
        groups.setdefault(r.product.po or "(ohne PO)", []).append(r)
    result = []
    for po, rows in groups.items():
        totals: dict[str, float | None] = {}
        for m in MEASURES:
            values = [v for r in rows if (v := r.value(m)) is not None]
            totals[m] = sum(values) if values else None
        result.append((po, totals))
    return result
