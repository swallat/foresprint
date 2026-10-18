# SPDX-License-Identifier: EUPL-1.2
"""Verteilung der Sprint-Menge auf die Produkte des Teams.

Je Produkt und Sprint:
    Standard     = verfügbare Menge × vereinbarter Anteil des Produkts (share) bzw.
                   (verfügbare Menge − Σ feste Anteile) / Anzahl Produkte ohne festen Anteil
                   verfügbar = Forecast PLAN (eingefroren beim Planning, sonst aktuell)
                   bzw. nur dessen Roadmap-Anteil (Einstellung forecast.product_basis)
    Vorplanung   = PO-seitig vorgesehen (vor dem Planning)
    Planning     = im Sprint Planning eingeplant
    Erledigt     = im Review tatsächlich erledigt
    Saldo        = Σ Erledigt − Σ Standard über mehrere Sprints
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sprintforecast.capacity import production_share
from sprintforecast.forecast import Forecast, TimelineEntry
from sprintforecast.i18n import t
from sprintforecast.model import Features, Product, ProductBasis, ProductValues, Sprint

# Spalten der Auswertung: Attribut → Anzeigename
MEASURES: dict[str, str] = {
    "standard": "Standard",
    "preplanned": "PO-Vorplanung",
    "planned": "Planning",
    "done": "Erledigt",
}


# Davon-Werte für Tickets, die Produktionszugriff erfordern (Teilmenge von Planning/Erledigt)
PRODUCTION_MEASURES: dict[str, str] = {
    "production_planned": "davon Produktionszugriff (Planning)",
    "production_done": "davon Produktionszugriff (Erledigt)",
}


def measure_label(measure: str) -> str:
    """Anzeigename einer Kennzahl in der eingestellten Sprache."""
    return t((MEASURES | PRODUCTION_MEASURES)[measure])


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
    production_planned: float | None = None
    production_done: float | None = None

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
    # Anteil der Personen mit Produktionszugriff an der Kapazität (None = keine Gruppe) und
    # die Menge, die diese Gruppe im Sprint schaffen kann (Anteil × Forecast PLAN).
    production_share: float | None = None
    production_available: float | None = None
    # Ist überhaupt jemand als berechtigt markiert? Ohne Markierung ist die Konfiguration
    # unbekannt – das ist etwas anderes als „Berechtigte sind in diesem Sprint nicht da“.
    production_configured: bool = False
    # Welche Bereiche das Team nutzt (steuert Spalten und Hinweise in der Oberfläche).
    features: Features = field(default_factory=Features)
    # Aktuell berechneter Forecast PLAN (weicht von ``plan`` ab, wenn dieser eingefroren ist).
    current_plan: float | None = None

    @property
    def production_state(self) -> str:
        """``unconfigured`` (niemand markiert), ``unavailable`` (Berechtigte markiert, aber im
        Sprint ohne Kapazität) oder ``ok``."""
        if not self.production_configured:
            return "unconfigured"
        if not self.production_share:
            return "unavailable"
        return "ok"

    @property
    def production_overload(self) -> float | None:
        """Um wie viel das Planning mit Produktionszugriff die Gruppe übersteigt (sonst None)."""
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
            # Teams ohne Produktverteilung erfassen die Mengen mit Produktionszugriff je Sprint.
            return getattr(self.sprint, measure)
        return sum(values) if values else None

    def has(self, measure: str) -> bool:
        return any(r.value(measure) is not None for r in self.rows)


def plan_of(entry: TimelineEntry) -> tuple[float | None, bool]:
    """Forecast PLAN eines Sprints: beim Planning eingefroren, sonst wie aktuell berechnet."""
    if entry.sprint.forecast_plan is not None:
        return entry.sprint.forecast_plan, True
    return entry.result.plan, False


@dataclass(frozen=True)
class PlanView:
    """Beide Stände des Forecast PLAN eines Sprints: aktuell berechnet und beim Planning
    eingefroren (None, solange nicht eingefroren)."""

    current: float | None
    frozen: float | None

    @property
    def difference(self) -> float | None:
        """Aktuell − beim Planning; None ohne eingefrorenen oder aktuellen Wert."""
        if self.current is None or self.frozen is None:
            return None
        return self.current - self.frozen


def plan_view(entry: TimelineEntry) -> PlanView:
    return PlanView(current=entry.result.plan, frozen=entry.sprint.forecast_plan)


def standard_shares(active: list[Product], available: float | None) -> dict[str, float]:
    """Standardmenge je betreutem Produkt: feste Anteile zuerst, der Rest gleichmäßig."""
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
    """Fußnote zur Spalte „ohne Wert“ (Terminal und Bericht; nur Text, ohne Markup)."""
    return t(
        "„ohne Wert“: Sprints, in denen für das Produkt kein Erledigt-Wert eingetragen ist "
        "(leer, nicht 0). Sie zählen im Saldo nicht mit; bitte den Wert im Sprint nachtragen."
    )


@dataclass
class Balance:
    product: Product
    sprints: int
    standard: float
    done: float
    # Sprints, in denen für das Produkt kein „Erledigt“ erfasst ist (fehlt ≠ 0): nicht gezählt.
    missing: int = 0

    @property
    def difference(self) -> float:
        """Positiv = mehr erledigt als der Standardanteil."""
        return self.done - self.standard


def balance(fc: Forecast, entries: list[TimelineEntry]) -> list[Balance]:
    """Saldo je Produkt über die Sprints, in denen Erledigt für das Produkt erfasst wurde. Ein
    fehlender Wert zählt nicht als 0; solche Sprints werden gezählt (``missing``) und fließen
    weder mit Erledigt noch mit dem Standard ein."""
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
            if r.done is None:  # Wert fehlt: weder als 0 noch mit dem Standard zählen
                b.missing += 1
                continue
            b.sprints += 1
            b.standard += r.standard or 0.0
            b.done += r.done
    return sorted(sums.values(), key=lambda b: order.get(b.product.id, len(order)))


def by_po(d: Distribution) -> list[tuple[str, dict[str, float | None]]]:
    """Summen je PO (nur wenn mindestens ein Produkt einen PO hat)."""
    if not any(r.product.po for r in d.rows):
        return []
    groups: dict[str, list[ProductRow]] = {}
    for r in d.rows:
        groups.setdefault(r.product.po or t("(ohne PO)"), []).append(r)
    result = []
    for po, rows in groups.items():
        totals: dict[str, float | None] = {}
        for m in MEASURES:
            values = [v for r in rows if (v := r.value(m)) is not None]
            totals[m] = sum(values) if values else None
        result.append((po, totals))
    return result
