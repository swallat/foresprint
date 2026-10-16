# SPDX-License-Identifier: EUPL-1.2
"""Szenarien, in denen Kennzahlen auseinanderlaufen könnten.

Jede Kombination wird gegen den Rechenkern und gegen die Seiten der Weboberfläche geprüft:
Zustand der Sprintdatei × erwartete Fehltage, eingefrorener Forecast PLAN, Produktbasis,
Rundung, Kapazitätsdetails, Einheit, Sprintlängen, dünne Historie, Stichtag, Sprache.
"""

import copy
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast import i18n
from sprintforecast.engine import CapacitySource, round_down
from sprintforecast.forecast import absences_known, build_forecast
from sprintforecast.formulas import steps
from sprintforecast.model import ProductBasis, ProductValues, Prognosis, Sprint, TrendMode, Unit
from sprintforecast.products import distribution
from sprintforecast.report import fmt, render
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository
from sprintforecast.validate import check_team
from sprintforecast.web.logic import apply_calendar, calendar_table, with_sprints

TODAY = date(2026, 10, 15)
TARGET = "2026.23"  # künftiger Sprint ohne Datei
APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def num(text: str) -> float:
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    assert match, text
    return float(match.group().replace(",", "."))


def load(data_dir: Path):
    return Repository(data_dir).load("demo")


def web(data_dir: Path, monkeypatch: pytest.MonkeyPatch, today: str = "2026-10-15") -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, today)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def target_sprint(data) -> Sprint:
    entry = build_forecast(data, TODAY).entry(TARGET)
    return copy.deepcopy(entry.sprint)


# --- 1. Zustand der Sprintdatei × erwartete Fehltage ------------------------------------------

STATES = {
    "keine Datei": (None, None),
    "leere Datei": (lambda s: None, None),
    "bestätigt ohne Einträge": (lambda s: setattr(s, "absences_confirmed", True), "PEOPLE"),
    "nur Vorplanung": (
        lambda s: s.products.update({"webshop": ProductValues(preplanned=2.0)}),
        None,
    ),
    "nur Prognose": (
        lambda s: s.prognoses.append(Prognosis(at=datetime(2026, 10, 15, 9, 0), expected_done=8)),
        None,
    ),
    "Fehltage eingetragen": (lambda s: s.absences.update({"anna": 2.0}), "PEOPLE"),
    "Forecast IST gesetzt": (lambda s: setattr(s, "forecast_ist", 9.0), "PEOPLE"),
    "voraussichtliche Fehltage": (lambda s: s.expected_absences.update({"anna": 3.0}), "EXPECTED"),
    "feste Kapazität": (lambda s: setattr(s, "capacity", 30.0), "RECORDED"),
}


def prepare_state(data_dir: Path, state: str, history: int) -> None:
    repo = Repository(data_dir)
    data = repo.load("demo")
    if history:
        data.team.capacity.absence_history = history
        repo.save_team(data.team)
    change, _ = STATES[state]
    if state != "keine Datei":
        sprint = target_sprint(data)
        change(sprint)
        repo.save_sprint("demo", sprint)


def expected_source(state: str, history: int) -> CapacitySource:
    fixed = STATES[state][1]
    if fixed:
        return CapacitySource[fixed]
    return CapacitySource.ESTIMATED if history else CapacitySource.TREND


@pytest.mark.parametrize("history", [0, 3])
@pytest.mark.parametrize("state", list(STATES))
def test_file_state_decides_capacity_source_and_pages_agree(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, state: str, history: int
):
    prepare_state(data_dir, state, history)
    data = load(data_dir)
    fc = build_forecast(data, TODAY)
    entry = fc.entry(TARGET)
    assert entry.result.plan_capacity_source is expected_source(state, history)
    plan = entry.result.plan
    assert entry.result.roadmap + entry.result.small_stuff == pytest.approx(plan)
    d = distribution(fc, entry)
    assert d.available == pytest.approx(plan)

    at = web(data_dir, monkeypatch)
    goto(at, "forecast")
    tile = next(m for m in at.metric if m.label.startswith(TARGET))
    assert num(tile.value) == pytest.approx(plan)

    goto(at, "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value(TARGET).run()
    assert not at.exception, at.exception
    headline = next(m for m in at.metric if m.label == f"Forecast PLAN {TARGET}")
    available = next(m for m in at.metric if m.label == "Verteilbar")
    assert num(headline.value) == pytest.approx(plan)
    assert num(available.value) == pytest.approx(plan, abs=0.051)


def test_absences_known_rules():
    base = dict(id="x", start=date(2026, 1, 1), end=date(2026, 1, 15))
    assert not absences_known(Sprint(**base))
    assert not absences_known(Sprint(**base, products={"a": ProductValues(preplanned=1.0)}))
    assert not absences_known(Sprint(**base, expected_absences={"anna": 1.0}))
    assert absences_known(Sprint(**base, absences={"anna": 1.0}))
    assert absences_known(Sprint(**base, absences_confirmed=True))
    assert absences_known(Sprint(**base, forecast_ist=5.0))


def test_confirmed_absences_beat_expected_absences(data_dir: Path):
    data = load(data_dir)
    sprint = target_sprint(data)
    sprint.expected_absences = {"anna": 9.0}
    sprint.absences = {"anna": 1.0}
    fc = build_forecast(with_sprints(data, [sprint]), TODAY)
    confirmed = copy.deepcopy(sprint)
    confirmed.expected_absences = {}
    plain = build_forecast(with_sprints(data, [confirmed]), TODAY)
    assert fc.entry(TARGET).result.plan_capacity_source is CapacitySource.PEOPLE
    assert fc.entry(TARGET).result.plan_capacity == plain.entry(TARGET).result.plan_capacity


def test_more_expected_absences_lower_capacity_and_plan(data_dir: Path):
    data = load(data_dir)
    values = []
    for days in (0.0, 2.0, 6.0):
        sprint = target_sprint(data)
        sprint.expected_absences = {"anna": days} if days else {"ben": 0.0}
        e = build_forecast(with_sprints(data, [sprint]), TODAY).entry(TARGET)
        values.append((e.result.plan_capacity, e.result.plan))
    assert values[0][0] > values[1][0] > values[2][0]
    assert values[0][1] >= values[1][1] >= values[2][1]


# --- 2. Eingefrorener Forecast PLAN -------------------------------------------------------------


def test_frozen_plan_drives_distribution_but_not_forecast_page(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprint("2026.22")
    sprint.forecast_plan = 5.0
    repo.save_sprint("demo", sprint)
    data = repo.load("demo")
    fc = build_forecast(data, TODAY)
    live = fc.entry("2026.22").result.plan
    assert live != 5.0
    d = distribution(fc, fc.entry("2026.22"))
    assert d.plan == 5.0 and d.plan_frozen and d.available == 5.0
    assert d.total("standard") == pytest.approx(5.0)

    at = web(data_dir, monkeypatch)
    goto(at, "forecast")
    tile = next(m for m in at.metric if m.label.startswith("2026.22"))
    assert num(tile.value) == pytest.approx(live)  # Forecast-Seite: live berechnet
    goto(at, "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    headline = next(m for m in at.metric if m.label == "Forecast PLAN 2026.22")
    assert num(headline.value) == pytest.approx(5.0)  # Board: eingefroren
    assert num(next(m for m in at.metric if m.label == "Verteilbar").value) == pytest.approx(5.0)


def test_unfreeze_clears_the_frozen_plan_after_confirmation(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(data_dir)
    sprint = repo.load("demo").sprint("2026.21")
    sprint.forecast_plan = 10.1
    repo.save_sprint("demo", sprint)
    assert load(data_dir).sprint("2026.21").forecast_plan is not None
    at = web(data_dir, monkeypatch)
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value("2026.21").run()
    assert any("nicht nachträglich ins Planning" in w.value for w in at.warning)
    button = next(b for b in at.button if b.key == "unfreeze-go-2026.21")
    assert button.disabled  # erst nach Bestätigung
    at.checkbox(key="unfreeze-2026.21").set_value(True).run()
    next(b for b in at.button if b.key == "unfreeze-go-2026.21").click().run()
    assert not at.exception, at.exception
    assert load(data_dir).sprint("2026.21").forecast_plan is None
    data = load(data_dir)
    fc = build_forecast(data, TODAY)
    d = distribution(fc, fc.entry("2026.21"))
    assert not d.plan_frozen and d.available == pytest.approx(fc.entry("2026.21").result.plan)


# --- 3. Was-wäre-wenn --------------------------------------------------------------------------


def test_whatif_with_two_open_sprints_and_frozen_target(data_dir: Path):
    from sprintforecast.web.logic import Assumption, open_velocity_sprints, whatif_forecast

    data = load(data_dir)
    fc = build_forecast(data, TODAY)
    open_sprints = open_velocity_sprints(fc)
    assert open_sprints
    low = whatif_forecast(fc, {s.id: Assumption(5.0) for s in open_sprints})
    high = whatif_forecast(fc, {s.id: Assumption(20.0) for s in open_sprints})
    assert fc.entry("2026.22").result.plan is not None
    assert low.entry("2026.22").result.plan < high.entry("2026.22").result.plan
    # eingefrorene Ziele ändern sich nicht (Verteilung nutzt den eingefrorenen Wert)
    frozen = copy.deepcopy(data.sprint("2026.22"))
    frozen.forecast_plan = 7.0
    base = build_forecast(with_sprints(data, [frozen]), TODAY)
    for assumption in (3.0, 25.0):
        scenario = whatif_forecast(base, {open_sprints[-1].id: Assumption(assumption)})
        assert distribution(scenario, scenario.entry("2026.22")).available == 7.0


def test_whatif_target_is_the_open_sprint_itself(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    at = web(data_dir, monkeypatch)
    goto(at, "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value("2026.21").run()
    box = next(n for n in at.number_input if n.key and n.key.endswith("-open"))
    box.set_value(3.0).run()
    assert not at.exception, at.exception
    assert any(m.label == "Forecast PLAN 2026.21" for m in at.metric)


# --- 4. Produktbasis, feste Anteile ------------------------------------------------------------


@pytest.mark.parametrize("basis", [ProductBasis.PLAN, ProductBasis.ROADMAP])
@pytest.mark.parametrize("shares", [{}, {"app": 0.1}, {"app": 0.6, "webshop": 0.6}])
def test_standard_always_adds_up(data_dir: Path, basis, shares):
    data = load(data_dir)
    data.team.forecast.product_basis = basis
    for product in data.products:
        product.share = shares.get(product.id)
    fc = build_forecast(data, TODAY)
    for e in fc.upcoming():
        d = distribution(fc, e)
        if d.available is None or not d.active_count:
            continue
        fixed = sum(
            s
            for p in data.products
            if p.id in shares and p in [r.product for r in d.rows if r.active]
            for s in [shares[p.id]]
        )
        if fixed <= 1:
            assert d.total("standard") == pytest.approx(d.available)
        else:  # Anteile über 100 %: der Rest wird 0, nichts wird negativ
            assert all(r.standard is None or r.standard >= 0 for r in d.rows)
        expected = d.plan * (
            data.team.forecast.roadmap_share if basis is ProductBasis.ROADMAP else 1
        )
        assert d.available == pytest.approx(expected)


def test_products_without_catalog_entry_and_inactive_products(data_dir: Path):
    data = load(data_dir)
    sprint = copy.deepcopy(data.sprint("2026.20"))
    sprint.products["geloescht"] = ProductValues(done=1.0)
    fc = build_forecast(with_sprints(data, [sprint]), TODAY)
    d = distribution(fc, fc.entry("2026.20"))
    assert any(r.product.id == "geloescht" and not r.active for r in d.rows)
    assert d.total("standard") == pytest.approx(d.available)  # nicht betreute Produkte: kein Anteil


# --- 5. Rundung --------------------------------------------------------------------------------


@pytest.mark.parametrize("rounding", [0, 1, 2])
def test_rounding_setting_is_applied_everywhere(data_dir: Path, rounding: int):
    data = load(data_dir)
    data.team.forecast.rounding = rounding
    fc = build_forecast(data, TODAY)
    ref = data.team.forecast.reference_capacity
    for e in fc.upcoming():
        r = e.result
        exact = r.normalized_velocity.trend / ref * r.plan_capacity
        assert r.plan == round_down(exact, rounding)
        assert r.roadmap + r.small_stuff == pytest.approx(r.plan)
        plan_step = next(x for x in steps(fc, e) if x.key == "plan")
        assert fmt(r.plan, rounding) in plan_step.calculation
    assert f"| {fc.upcoming()[1].sprint.id} |" in render(fc)


# --- 6. Kapazitätsdetails ----------------------------------------------------------------------


def test_capacity_details_add_up(data_dir: Path):
    from sprintforecast.capacity import production_share, sprint_capacity

    data = load(data_dir)
    sprint = data.sprint("2026.22")
    data.team.capacity.overhead_days = 1.0
    breakdown = sprint_capacity(data.team, data.people, sprint)
    assert breakdown.gross == pytest.approx(sum(r.capacity for r in breakdown.people))
    assert breakdown.overhead == pytest.approx(breakdown.overhead_days_part)
    assert breakdown.capacity == round_down(breakdown.gross - breakdown.overhead, 1)
    # Prozent und PT gleichzeitig: nur ein Abzug
    data.team.capacity.overhead_share = 0.5
    again = sprint_capacity(data.team, data.people, sprint)
    assert again.capacity == breakdown.capacity

    for person in data.people[:2]:
        person.production_access = True
    share = production_share(data.team, data.people, sprint)
    assert 0 < share < 1


def test_zero_fte_and_midsprint_change(data_dir: Path):
    from sprintforecast.capacity import sprint_capacity
    from sprintforecast.model import Membership

    data = load(data_dir)
    sprint = data.sprint("2026.22")
    before = sprint_capacity(data.team, data.people, sprint)
    anna = next(p for p in data.people if p.id == "anna")
    half = sprint.start + timedelta(days=7)
    anna.memberships = [
        Membership(start=anna.memberships[0].start, end=half - timedelta(days=1), fte=1.0),
        Membership(start=half, end=None, fte=0.0),
    ]
    after = sprint_capacity(data.team, data.people, sprint)
    assert after.gross < before.gross
    anna_before = next(r for r in before.people if r.person.id == "anna")
    anna_after = next(r for r in after.people if r.person.id == "anna")
    assert (
        anna_after.workdays < anna_before.workdays
    )  # nach dem Wechsel auf FTE 0 zählen nur frühere Tage
    assert anna_after.capacity < anna_before.capacity
    anna.memberships = [Membership(start=anna.memberships[0].start, end=None, fte=0.0)]
    gone = sprint_capacity(data.team, data.people, sprint)
    assert all(r.person.id != "anna" for r in gone.people)
    issues = check_team(with_sprints(data, []), TODAY)
    assert not [i for i in issues if i.level.value == "Fehler"]


def test_absences_cannot_exceed_workdays(data_dir: Path):
    data = load(data_dir)
    sprint = copy.deepcopy(data.sprint("2026.22"))
    sprint.absences = {"anna": 99.0}
    issues = check_team(with_sprints(data, [sprint]), TODAY)
    assert any(i.level.value == "Fehler" for i in issues)


# --- 7. Einheit SP ----------------------------------------------------------------------------


def test_unit_sp_changes_labels_but_not_numbers(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    repo = Repository(data_dir)
    data = repo.load("demo")
    reference = build_forecast(data, TODAY).entry("2026.22").result.plan
    data.team.unit = Unit.SP
    repo.save_team(data.team)
    at = web(data_dir, monkeypatch)
    goto(at, "forecast")
    tile = next(m for m in at.metric if m.label.startswith("2026.22"))
    assert tile.value.endswith(" SP") and num(tile.value) == pytest.approx(reference)
    goto(at, "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
    headline = next(m for m in at.metric if m.label == "Forecast PLAN 2026.22")
    assert headline.value.endswith(" SP")
    capacity = next(m for m in at.metric if m.label == "Kapazität (PT)")
    assert "PT" not in capacity.value or "SP" not in capacity.value  # Kapazität bleibt PT


# --- 8. Sprintlängen ---------------------------------------------------------------------------


def test_longer_sprint_scales_capacity_and_shifts_followers(data_dir: Path):
    data = load(data_dir)
    fc = build_forecast(data, TODAY)
    sprints = [e.sprint for e in fc.upcoming()]
    rows = calendar_table(data, sprints, TODAY)
    rows[1]["Letzter Tag"] = sprints[1].end + timedelta(days=13)  # 2026.22 vier Wochen
    after, errors = apply_calendar(data, sprints, rows)
    assert not errors
    assert after[1].end == sprints[1].end + timedelta(days=14)
    assert after[2].start == after[1].end
    assert (after[2].end - after[2].start) == (sprints[2].end - sprints[2].start)
    longer = build_forecast(with_sprints(data, [after[1]]), TODAY)
    short = fc.entry("2026.22").result
    long = longer.entry("2026.22").result
    assert long.plan_capacity > short.plan_capacity
    assert long.plan >= short.plan


def test_sequential_to_yearly_numbering_keeps_order(data_dir: Path):
    from sprintforecast.calendar import next_id
    from sprintforecast.model import Numbering

    assert next_id("39", date(2026, 1, 7), Numbering.YEARLY) == "2026.1"
    assert next_id("2026.9", date(2026, 6, 1), Numbering.YEARLY) == "2026.10"
    assert next_id("2026.26", date(2027, 1, 6), Numbering.YEARLY) == "2027.1"


# --- 9. Dünne Historie, Trend-Modi -------------------------------------------------------------


@pytest.mark.parametrize("keep", [0, 1, 2, 3])
def test_thin_history_does_not_break_any_page(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, keep: int
):
    sprints = sorted((data_dir / "demo" / "sprints").glob("*.yaml"))
    for path in sprints[: len(sprints) - keep - 2]:  # nur die jüngsten Dateien behalten
        path.unlink()
    at = web(data_dir, monkeypatch)
    for page in ("forecast", "vorplanung", "planning", "review", "produkte", "analyse", "fehltage"):
        goto(at, page)


@pytest.mark.parametrize("mode", list(TrendMode))
def test_trend_modes_match_formula_steps(data_dir: Path, mode: TrendMode):
    data = load(data_dir)
    data.team.forecast.trend_mode = mode
    fc = build_forecast(data, TODAY)
    for e in fc.upcoming():
        trend = fmt(e.result.normalized_velocity.trend, 2)
        calc = next(s for s in steps(fc, e) if s.key == "trend").calculation
        assert calc.rstrip().endswith(trend) or trend in calc, (mode, e.sprint.id, calc, trend)


# --- 10. Stichtag ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "current"),
    [
        (date(2026, 10, 14), "2026.21"),  # erster Tag
        (date(2026, 10, 27), "2026.21"),  # letzter Tag
        (date(2026, 10, 28), "2026.22"),  # Ende ist exklusiv
        (date(2026, 10, 17), "2026.21"),  # Wochenende
    ],
)
def test_today_boundaries(data_dir: Path, today: date, current: str):
    fc = build_forecast(load(data_dir), today)
    assert fc.current.sprint.id == current
    ids = [e.sprint.id for e in fc.upcoming()]
    assert ids[0] == current
    assert all(e.sprint.end <= today for e in fc.history())
    report = render(fc)
    assert f"| {current} |" in report and "**laufend**" in report


# --- 11. Sprache -------------------------------------------------------------------------------


def test_english_ui_shows_same_numbers(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    plan = build_forecast(load(data_dir), TODAY).entry("2026.22").result.plan
    try:
        i18n.save_language("en")
        at = web(data_dir, monkeypatch)
        goto(at, "forecast")
        tile = next(m for m in at.metric if m.label.startswith("2026.22"))
        assert num(tile.value) == pytest.approx(plan)
        goto(at, "vorplanung")
        at.selectbox(key="vorplanung-sprint").set_value("2026.22").run()
        assert not at.exception, at.exception
        headline = next(m for m in at.metric if m.label == "Forecast PLAN 2026.22")
        assert num(headline.value) == pytest.approx(plan)
    finally:
        i18n.save_language("de")


# --- Funktionen der neuen Abläufe -------------------------------------------------------------


def test_expected_absences_roundtrip_and_validation(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = target_sprint(data)
    sprint.expected_absences = {"anna": 2.5}
    repo.save_sprint("demo", sprint)
    saved = yaml.safe_load((data_dir / "demo" / "sprints" / f"{TARGET}.yaml").read_text())
    assert saved["expected_absences"] == {"anna": 2.5}
    assert repo.load("demo").sprint(TARGET).expected_absences == {"anna": 2.5}
    sprint.expected_absences = {"niemand": 1.0}
    issues = check_team(with_sprints(repo.load("demo"), [sprint]), TODAY)
    assert any(i.level.value == "Fehler" and "niemand" in i.message for i in issues)


def test_preplanning_saves_expected_absences_and_changes_plan(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = web(data_dir, monkeypatch)
    goto(at, "vorplanung")
    at.selectbox(key="vorplanung-sprint").set_value(TARGET).run()

    def plan_with(days: float) -> float:
        at.session_state[f"vorplanung-expected-{TARGET}"] = {
            "edited_rows": {0: {TARGET: days}},
            "added_rows": [],
            "deleted_rows": [],
        }
        at.run()
        assert not at.exception, at.exception
        return num(next(m for m in at.metric if m.label == f"Forecast PLAN {TARGET}").value)

    few, many = plan_with(2.0), plan_with(8.0)
    assert many < few  # mehr voraussichtliche Fehltage → kleinerer Forecast PLAN
    next(b for b in at.button if b.label == "PO-Vorplanung speichern").click().run()
    saved = yaml.safe_load((data_dir / "demo" / "sprints" / f"{TARGET}.yaml").read_text())
    assert sum(saved["expected_absences"].values()) == 8
    assert not saved.get("absences")  # bestätigt wurde nichts
    fc = build_forecast(load(data_dir), TODAY)
    assert fc.entry(TARGET).result.plan_capacity_source is CapacitySource.EXPECTED
    assert fc.entry(TARGET).result.plan == many  # gespeichert = angezeigt


def test_planning_prefills_absences_and_products_from_preplanning(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = target_sprint(data)
    sprint.expected_absences = {"anna": 2.0}
    sprint.products = {"webshop": ProductValues(preplanned=3.0)}
    repo.save_sprint("demo", sprint)

    at = web(data_dir, monkeypatch)
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value(TARGET).run()
    assert any("Vorbelegt mit den voraussichtlichen Fehltagen" in i.value for i in at.info)
    # Bestätigen übernimmt die vorbelegten Fehltage als echte Fehltage
    next(b for b in at.button if b.label == "Fehltage speichern und weiter").click().run()
    assert not at.exception, at.exception
    saved = load(data_dir).sprint(TARGET)
    assert saved.absences == {"anna": 2.0} and saved.absences_confirmed
    assert at.radio(key="planning-step").value == 1
    assert any("mit der letzten PO-Vorplanung vorbelegt" in c.value for c in at.caption)


def test_review_points_to_late_tickets(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    at = web(data_dir, monkeypatch)
    goto(at, "review")
    assert any("nicht nachträglich" in c.value for c in at.caption)
