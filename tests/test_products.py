# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

import pytest

from sprintforecast.forecast import build_forecast, freeze_plan
from sprintforecast.model import Product, ProductBasis, ProductValues
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
    assert d.available == pytest.approx(11.2)
    assert all(r.standard == pytest.approx(11.2 / 3) for r in d.rows)
    assert d.total("preplanned") == 10


def test_fixed_share_and_rest_split_evenly(fc):
    next(p for p in fc.data.products if p.id == "app").share = 0.1
    d = distribution(fc, fc.entry("2026.22"))
    standard = {r.product.id: r.standard for r in d.rows}
    assert standard["app"] == pytest.approx(1.12)
    assert standard["webshop"] == standard["portal"] == pytest.approx((11.2 - 1.12) / 2)
    assert sum(standard.values()) == pytest.approx(11.2)


def test_share_roundtrip_and_table(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.products[0].share = 0.1
    repo.save_products("demo", data.products)
    again = repo.load("demo").products
    assert again[0].share == pytest.approx(0.1)
    assert again[1].share is None
    rows, hidden = product_table(again, TODAY, True)
    assert rows[0]["Anteil"] == pytest.approx(10.0)
    result = products_from_table(rows, again, hidden)
    assert result.errors == [] and result.products[0].share == pytest.approx(0.1)
    rows[1]["Anteil"] = 150
    assert products_from_table(rows, again, hidden).errors


def test_production_access_group(data_dir: Path):
    from sprintforecast.web.logic import people_from_table, people_table

    repo = Repository(data_dir)
    data = repo.load("demo")
    base = build_forecast(data, TODAY)
    assert distribution(base, base.entry("2026.22")).production_share is None

    rows, hidden = people_table(data.people, TODAY, True)
    for row in rows:
        row["Produktionszugriff"] = row["Name"] == "Ben"  # Ben arbeitet 0,5 FTE
    people = people_from_table(rows, data.people, hidden).people
    assert [p.name for p in people if p.production_access] == ["Ben"]
    data.people = people
    repo.save_people("demo", people)
    assert [p.id for p in repo.load("demo").people if p.production_access] == ["ben"]

    fc = build_forecast(data, TODAY)
    entry = fc.entry("2026.22")
    entry.sprint.products["webshop"] = ProductValues(planned=2, production_planned=1)
    d = distribution(fc, entry)
    assert 0 < d.production_share < 0.5
    assert d.production_available == pytest.approx(d.plan * d.production_share)
    assert d.production_overload is None
    entry.sprint.products["webshop"].production_planned = 50
    assert distribution(fc, entry).production_overload is not None


def test_production_values_roundtrip_and_validation(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprint("2026.21")
    sprint.products["webshop"] = ProductValues(planned=1, production_planned=2, production_done=-1)
    messages = [i.message for i in check_team(data, TODAY)]
    assert any("production_done" in m for m in messages)
    assert any("Produktionszugriff" in m or "production access" in m for m in messages)
    sprint.products["webshop"] = ProductValues(planned=3, production_planned=1)
    repo.save_sprint("demo", sprint)
    saved = repo.load("demo").sprint("2026.21").products["webshop"]
    assert saved.production_planned == 1 and saved.production_done is None


def test_roadmap_basis(fc):
    fc.data.team.forecast.product_basis = ProductBasis.ROADMAP
    d = distribution(fc, fc.entry("2026.22"))
    assert d.available == pytest.approx(11.2 * 0.8)


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
    assert any("größer als das Commitment" in m for m in messages)


def test_freeze_keeps_existing_plan_unless_requested(fc):
    from sprintforecast.forecast import refreeze_offer

    entry = fc.entry("2026.22")
    entry.sprint.forecast_plan = 9.0
    freeze_plan(entry.sprint, entry, TODAY)
    assert entry.sprint.forecast_plan == 9.0
    assert refreeze_offer(entry.sprint, entry) == (9.0, pytest.approx(11.2))
    freeze_plan(entry.sprint, entry, TODAY, refreeze=True)
    assert entry.sprint.forecast_plan == pytest.approx(11.2)
    assert refreeze_offer(entry.sprint, entry) is None


def test_planning_default_skips_committed_future_sprint(fc):
    assert fc.default_entry("planning").sprint.id == "2026.22"
    fc.entry("2026.22").sprint.forecast_ist = 10
    assert fc.default_entry("planning").sprint.id == "2026.23"
    assert fc.default_entry("next").sprint.id == "2026.22"  # Fehltage unverändert


def test_fixed_shares_over_100_percent_are_rejected(fc):
    """A10: Zwei feste Anteile von je 60 % werden abgelehnt."""
    for p in fc.data.products:
        if p.id in ("webshop", "app"):
            p.share = 0.6
    issues = check_team(fc.data, TODAY)
    errors = [i for i in issues if i.level.value == "Fehler" and "mehr als 100 %" in i.message]
    assert errors and errors[0].where == "products.yaml"
    assert "120" in errors[0].message


def test_fixed_shares_adding_to_100_percent_warn_when_others_remain(fc):
    for p in fc.data.products:
        if p.id in ("webshop", "app"):
            p.share = 0.5
    issues = check_team(fc.data, TODAY)
    assert not [i for i in issues if i.level.value == "Fehler" and "100 %" in i.message]
    assert any("bleibt nichts" in i.message for i in issues)


def test_balance_distinguishes_missing_from_zero(fc):
    """A10: In einem Sprint mit Erledigt für andere Produkte zählt ein fehlender Wert nicht
    als 0 – weder sein Erledigt noch sein Standard fließen in den Saldo ein."""
    from sprintforecast.products import balance

    entry = fc.entry("2026.20")
    sprint = entry.sprint
    recorded = {pid: v.done for pid, v in sprint.products.items() if v.done is not None}
    assert len(recorded) >= 2
    before = {b.product.id: b for b in balance(fc, [entry])}
    skipped = next(iter(recorded))
    sprint.products[skipped].done = None  # nicht erfasst
    after = {b.product.id: b for b in balance(fc, [entry])}
    assert after[skipped].missing == 1 and after[skipped].sprints == 0
    assert after[skipped].standard == 0.0 and after[skipped].done == 0.0  # nicht als 0 gezählt
    other = next(pid for pid in recorded if pid != skipped)
    assert after[other].difference == pytest.approx(before[other].difference)
    # als echte 0 erfasst, zählt der Standard dagegen mit
    sprint.products[skipped].done = 0.0
    zero = {b.product.id: b for b in balance(fc, [entry])}
    assert zero[skipped].sprints == 1 and zero[skipped].missing == 0
    assert zero[skipped].difference == pytest.approx(-before[skipped].standard)


def test_production_state_distinguishes_unconfigured_from_unavailable(fc):
    """A11: „niemand markiert“ (Konfiguration unbekannt) ≠ „Berechtigte sind im Sprint nicht da“."""
    entry = fc.entry("2026.22")
    for p in fc.data.people:
        p.production_access = False
    unconfigured = distribution(fc, entry)
    assert unconfigured.production_state == "unconfigured"
    assert unconfigured.production_share is None

    anna = next(p for p in fc.data.people if p.id == "anna")
    anna.production_access = True
    assert distribution(fc, entry).production_state == "ok"
    assert distribution(fc, entry).production_share > 0

    entry.sprint.absences = {"anna": 10.0}  # die einzige Berechtigte fehlt den ganzen Sprint
    fc = build_forecast(fc.data, TODAY)
    unavailable = distribution(fc, fc.entry("2026.22"))
    assert unavailable.production_state == "unavailable"
    assert unavailable.production_share == 0.0
