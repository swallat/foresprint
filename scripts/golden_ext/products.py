# SPDX-License-Identifier: EUPL-1.2
"""Golden references of ``foresprint.products`` for the Go port: the distribution of every
sprint over the products (rows, totals, production state), the totals per PO, the balance over
all sprints, the two views of the Forecast PLAN and the standard shares for edge cases."""

from __future__ import annotations

from foresprint import products
from foresprint.forecast import build_forecast
from foresprint.model import Product


def _row(r) -> dict:
    return {
        "product": r.product.id,
        "name": r.product.name,
        "po": r.product.po,
        "active": r.active,
        **{m: r.value(m) for m in (*products.MEASURES, *products.PRODUCTION_MEASURES)},
    }


def _distribution(d) -> dict:
    measures = (*products.MEASURES, *products.PRODUCTION_MEASURES)
    return {
        "sprint": d.sprint.id,
        "plan": d.plan,
        "plan_frozen": d.plan_frozen,
        "basis": d.basis.value,
        "available": d.available,
        "current_plan": d.current_plan,
        "production_share": d.production_share,
        "production_available": d.production_available,
        "production_configured": d.production_configured,
        "production_state": d.production_state,
        "production_overload": d.production_overload,
        "active_count": d.active_count,
        "rows": [_row(r) for r in d.rows],
        "totals": {m: d.total(m) for m in measures},
        "has": {m: d.has(m) for m in measures},
        "by_po": [{"po": po, "totals": totals} for po, totals in products.by_po(d)],
    }


def generate(ctx) -> None:
    for case in ctx.resolved:
        data = ctx.load(case)
        fc = build_forecast(data, case.today)
        out = {
            "distributions": [],
            "plan_views": [],
            "sprint_products": [],
            "balance": [],
            "balance_last3": [],
        }
        for e in fc.entries:
            out["distributions"].append(_distribution(products.distribution(fc, e)))
            view = products.plan_view(e)
            out["plan_views"].append(
                {
                    "sprint": e.sprint.id,
                    "current": view.current,
                    "frozen": view.frozen,
                    "difference": view.difference,
                }
            )
            out["sprint_products"].append(
                {
                    "sprint": e.sprint.id,
                    "products": [p.id for p in products.sprint_products(data.products, e.sprint)],
                }
            )

        def balances(fc, entries):
            return [
                {
                    "product": b.product.id,
                    "sprints": b.sprints,
                    "standard": b.standard,
                    "done": b.done,
                    "missing": b.missing,
                    "difference": b.difference,
                }
                for b in products.balance(fc, entries)
            ]

        out["balance"] = balances(fc, fc.entries)
        out["balance_last3"] = balances(fc, fc.history(3))
        ctx.write(f"products/{case.name}.json", ctx.dump_json(ctx.jsonable(out)))

    def prod(pid: str, share: float | None) -> Product:
        return Product(id=pid, name=pid, share=share)

    shares = []
    for available, active in [
        (None, [prod("a", None)]),
        (10.0, []),
        (10.0, [prod("a", None), prod("b", None), prod("c", None)]),
        (10.0, [prod("a", 0.5), prod("b", None)]),
        (10.0, [prod("a", 0.5), prod("b", 0.5)]),
        (10.0, [prod("a", 0.7), prod("b", 0.7), prod("c", None)]),
        (10.0, [prod("a", 0.2), prod("b", 0.3), prod("c", None), prod("d", None)]),
        (0.0, [prod("a", None), prod("b", 0.1)]),
        (7.5, [prod("a", 0.1), prod("b", 0.2), prod("c", 0.3)]),
    ]:
        shares.append(
            {
                "available": available,
                "shares": {p.id: p.share for p in active},
                "result": products.standard_shares(active, available),
            }
        )
    labels = {
        m: products.measure_label(m) for m in (*products.MEASURES, *products.PRODUCTION_MEASURES)
    }
    ctx.write(
        "products/misc.json",
        ctx.dump_json(
            ctx.jsonable(
                {
                    "standard_shares": shares,
                    "labels": labels,
                    "footnote": products.missing_footnote(),
                }
            )
        ),
    )
