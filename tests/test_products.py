# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

import pytest

from sprintforecast.forecast import build_forecast, freeze_plan
from sprintforecast.model import Product, ProductBasis
from sprintforecast.products import balance, by_po, distribution
from sprintforecast.storage import Repository
from sprintforecast.validate import check_team
from sprintforecast.web.logic import (
    apply_product_values,
    product_table,
    product_values_table,
    products_from_table,
)

TODAY = date(2026, 10, 15)


@pytest.fixture
def fc(data_dir: Path):
    return build_forecast(Repository(data_dir).load("demo"), TODAY)


def test_standard_is_plan_divided_by_active_products(fc):
    d = distribution(fc, fc.entry("2026.22"))
    assert [r.product.id for r in d.rows] == ["webshop", "app", "portal"]  # Altsystem beendet
    assert d.available == pytest.approx(10.1)
    assert all(r.standard == pytest.approx(10.1 / 3) for r in d.rows)
    assert d.total("preplanned") == 10


def test_roadmap_basis(fc):
    fc.data.team.forecast.product_basis = ProductBasis.ROADMAP
    d = distribution(fc, fc.entry("2026.22"))
    assert d.available == pytest.approx(10.1 * 0.8)


def test_inactive_product_with_values_has_no_standard(fc):
    d = distribution(fc, fc.entry("2026.18"))
    # 2026.18: Altsystem noch betreut (bis 15.09.), Portal ab 02.09.
    assert d.active_count == 4
    s = fc.entry("2026.19").sprint
    s.products["altsystem"] = s.products["webshop"]
    d = distribution(fc, fc.entry("2026.19"))
    alt = next(r for r in d.rows if r.product.id == "altsystem")
    assert not alt.active and alt.standard is None


def test_frozen_plan_wins(fc):
    entry = fc.entry("2026.22")
    freeze_plan(entry.sprint, entry, TODAY)
    entry.sprint.forecast_plan = 9.0
    d = distribution(fc, entry)
    assert d.plan_frozen and d.available == 9.0


def test_freeze_plan_skips_finished_sprints(fc):
    entry = fc.entry("2026.20")
    freeze_plan(entry.sprint, entry, TODAY)
    assert entry.sprint.forecast_plan is None


def test_balance_over_history(fc):
    rows = balance(fc, fc.history(6))
    by_id = {b.product.id: b for b in rows}
    # 2026.17–2026.20 mit Erledigt; Webshop: 4,5 + 3,5 + 4,5 + 4
    assert by_id["webshop"].done == pytest.approx(16.5)
    assert by_id["webshop"].sprints == 4
    assert by_id["portal"].sprints == 3
    assert sum(b.done for b in rows) == pytest.approx(11.5 + 10.5 + 12.75 + 9.75)


def test_by_po(fc):
    totals = dict(by_po(distribution(fc, fc.entry("2026.22"))))
    assert totals["Alex"]["preplanned"] == 6
    assert totals["Bea"]["preplanned"] == 4


def test_product_values_roundtrip(fc, data_dir: Path):
    entry = fc.entry("2026.22")
    rows = product_values_table(distribution(fc, entry))
    rows[0]["Planning"] = 4.0
    rows[1]["PO-Vorplanung"] = None
    after = apply_product_values(entry.sprint, rows, ["preplanned", "planned"])
    assert after.products["webshop"].planned == 4
    assert "app" not in after.products  # leer → entfernt
    repo = Repository(data_dir)
    repo.save_sprint("demo", after)
    assert repo.load("demo").sprint("2026.22").products == after.products


def test_products_from_table_new_and_deleted():
    original = [Product("a", "A"), Product("b", "B", end=date(2026, 1, 1))]
    rows, hidden = product_table(original, TODAY, show_former=False)
    assert [r["Name"] for r in rows] == ["A"] and hidden == [original[1]]
    rows.append({"_id": None, "Name": "Neues Ding", "PO": "Bea", "ab": "2026-11-01", "bis": None})
    result = products_from_table(rows, original, hidden)
    assert not result.errors and not result.deleted
    assert [p.id for p in result.products] == ["a", "b", "neues-ding"]
    assert result.products[2].start == date(2026, 11, 1)
    assert products_from_table([], original, hidden).deleted == ["A"]


def test_validation_of_product_values(fc):
    data = fc.data
    s = data.sprint("2026.22")
    s.products["unbekannt"] = s.products["webshop"]
    s.forecast_ist = 5
    s.products["app"].planned = 7
    messages = [i.message for i in check_team(data, TODAY)]
    assert any("unbekanntes Produkt 'unbekannt'" in m for m in messages)
    assert any("größer als der Forecast IST" in m for m in messages)


def test_freeze_keeps_existing_plan_unless_requested(fc):
    from sprintforecast.forecast import refreeze_offer

    entry = fc.entry("2026.22")
    entry.sprint.forecast_plan = 9.0
    freeze_plan(entry.sprint, entry, TODAY)
    assert entry.sprint.forecast_plan == 9.0
    assert refreeze_offer(entry.sprint, entry) == (9.0, pytest.approx(10.1))
    freeze_plan(entry.sprint, entry, TODAY, refreeze=True)
    assert entry.sprint.forecast_plan == pytest.approx(10.1)
    assert refreeze_offer(entry.sprint, entry) is None


def test_planning_default_skips_committed_future_sprint(fc):
    assert fc.default_entry("planning").sprint.id == "2026.22"
    fc.entry("2026.22").sprint.forecast_ist = 10
    assert fc.default_entry("planning").sprint.id == "2026.23"
    assert fc.default_entry("next").sprint.id == "2026.22"  # Fehltage unverändert
