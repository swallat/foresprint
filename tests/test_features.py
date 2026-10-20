# SPDX-License-Identifier: EUPL-1.2
"""Feature areas: product distribution, PO assignment and production access can be enabled
independently of each other; off for new teams, derived from the data for older files."""

from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner
from webfixtures import nav_steps

from sprintforecast.cli import app as cli_app
from sprintforecast.model import Features, Sprint, Team
from sprintforecast.settings import SETTINGS
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository, team_from_dict, team_to_dict
from sprintforecast.validate import check_team

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
TEAM = "demo"


def set_features(data_dir: Path, **features: bool | None) -> None:
    path = data_dir / TEAM / "team.yaml"
    raw = yaml.safe_load(path.read_text())
    current = {"products": True, "po": True, "production": True}
    raw["features"] = {**current, **features}
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))


def mark_production_access(data_dir: Path, person: str = "ben") -> None:
    path = data_dir / TEAM / "people.yaml"
    raw = yaml.safe_load(path.read_text())
    next(p for p in raw["people"] if p["id"] == person)["production_access"] = True
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))


def start(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


# --- Default and older files -----------------------------------------------------


def test_new_team_has_all_areas_off_and_writes_them():
    team = Team(key="t", name="T")
    assert team.features == Features(products=False, po=False, production=False)
    assert team_to_dict(team)["features"] == {"products": False, "po": False, "production": False}


def test_settings_offer_the_three_areas_with_explanations():
    settings = {s.key: s for s in SETTINGS if s.key.startswith("features.")}
    assert set(settings) == {
        "features.products",
        "features.po",
        "features.production",
        "features.tickets",
    }
    team = Team(key="t", name="T")
    for setting in settings.values():
        assert setting.display(team) == "off" and len(setting.help) > 60
    settings["features.po"].set(team, "on")
    assert team.features.po and not team.features.products and not team.features.production


def test_legacy_team_file_derives_the_areas_from_its_data(data_dir: Path):
    path = data_dir / TEAM / "team.yaml"
    raw = yaml.safe_load(path.read_text())
    del raw["features"]
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))
    team = Repository(data_dir).load(TEAM).team
    assert not team.features.explicit
    # Products with PO are recorded, but nobody is marked as authorized in the demo team yet
    assert (team.features.products, team.features.po, team.features.production) == (
        True,
        True,
        False,
    )
    mark_production_access(data_dir)
    assert Repository(data_dir).load(TEAM).team.features.production
    # without products and without authorized people, everything stays off
    (data_dir / TEAM / "products.yaml").write_text("products: []\n")
    people = yaml.safe_load((data_dir / TEAM / "people.yaml").read_text())
    for person in people["people"]:
        person.pop("production_access", None)
    (data_dir / TEAM / "people.yaml").write_text(yaml.safe_dump(people, allow_unicode=True))
    bare = Repository(data_dir).load(TEAM).team.features
    assert (bare.products, bare.po, bare.production) == (False, False, False)


def test_legacy_file_is_written_with_explicit_areas_on_save(data_dir: Path):
    path = data_dir / TEAM / "team.yaml"
    raw = yaml.safe_load(path.read_text())
    del raw["features"]
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))
    repo = Repository(data_dir)
    repo.save_team(repo.load(TEAM).team)
    assert yaml.safe_load(path.read_text())["features"] == {
        "products": True,
        "po": True,
        "production": False,
    }
    assert team_from_dict("x", {"name": "X", "features": {"po": True}}, "x").features.po


# --- UI ----------------------------------------------------------------------------


def page_keys(at: AppTest) -> set[str]:
    return set(at.session_state["enabled-pages"])


def test_product_pages_exist_only_with_product_distribution(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    assert {"vorplanung", "produkte", "produktliste"} <= page_keys(start(data_dir, monkeypatch))
    set_features(data_dir, products=False)
    off = page_keys(start(data_dir, monkeypatch))
    assert not {"vorplanung", "produkte", "produktliste"} & off
    assert {"fehltage", "planning", "review", "forecast", "personen"} <= off


def test_step_bar_has_three_steps_without_the_products_area(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without the Products feature area, PO pre-planning is dropped: absences, Planning, Review."""
    at = goto(start(data_dir, monkeypatch), "planning")
    assert [key for key, _, _ in nav_steps(at)] == ["fehltage", "vorplanung", "planning", "review"]
    set_features(data_dir, products=False)
    at = start(data_dir, monkeypatch)
    for page in ("fehltage", "planning", "review"):
        goto(at, page)
        steps = nav_steps(at)
        assert [key for key, _, _ in steps] == ["fehltage", "planning", "review"]
        assert [key for key, _, active in steps if active] == [page]


def test_planning_and_review_ignore_products_when_distribution_is_off(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    set_features(data_dir, products=False, production=False)
    at = start(data_dir, monkeypatch)
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value("2026.22").run()
    at.radio(key="planning-step").set_value(1).run()
    assert not at.exception, at.exception
    assert not any("Einplanung je Produkt" in s.value for s in at.subheader)
    goto(at, "review")
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    assert not at.exception, at.exception
    assert not any("Erledigt je Produkt" in m.value for m in at.markdown)


def test_po_sums_and_production_hint_follow_their_switches(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    def products_page(at: AppTest) -> str:
        goto(at, "produkte")
        at.selectbox(key="products-sprint").set_value("2026.20").run()
        return " ".join([*(m.value for m in at.markdown), *(c.value for c in at.caption)])

    mark_production_access(data_dir)
    on = products_page(start(data_dir, monkeypatch))
    assert "Je PO" in on and "Produktionszugriff:" in on
    set_features(data_dir, po=False)
    assert "Je PO" not in products_page(start(data_dir, monkeypatch))
    set_features(data_dir, po=True, production=False)
    off = products_page(start(data_dir, monkeypatch))
    assert "Je PO" in off and "Produktionszugriff:" not in off


def test_planning_step_two_splits_capacity_by_production_access(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    def captions(at: AppTest) -> str:
        goto(at, "planning")
        at.selectbox(key="planning-sprint").set_value("2026.22").run()
        at.radio(key="planning-step").set_value(1).run()
        assert not at.exception, at.exception
        return " ".join(c.value for c in at.caption)

    mark_production_access(data_dir)
    assert "PT mit Produktionszugriff" in captions(start(data_dir, monkeypatch))
    set_features(data_dir, production=False)
    assert "PT mit Produktionszugriff" not in captions(start(data_dir, monkeypatch))


def test_planning_minutes_follow_the_product_distribution_switch(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without the Products feature area, the Planning minutes have no product section, even
    if the product catalog is kept in the files."""

    def planning_minutes(products: bool) -> str:
        set_features(data_dir, products=products)
        at = goto(start(data_dir, monkeypatch), "planning")
        at.selectbox(key="planning-sprint").set_value("2026.22").run()
        at.radio(key="planning-step").set_value(2).run()
        at.number_input(key="fist-2026.22").set_value(10.0 + (1 if products else 0))
        click(at, "Planning speichern")
        # Two saves in the same second: the names then sort by fingerprint, so choose by
        # write time.
        files = (data_dir / TEAM / "protokolle").glob("2026.22-planning-*.md")
        return max(files, key=lambda p: p.stat().st_mtime_ns).read_text(encoding="utf-8")

    assert "Je Produkt" not in planning_minutes(products=False)
    assert "Je Produkt" in planning_minutes(products=True)


def test_production_split_uses_the_current_plan_for_both_amounts(data_dir: Path):
    """If the Forecast PLAN is frozen and differs from the current one, both quantities split
    the current plan (no negative remainder)."""
    from sprintforecast.forecast import build_forecast
    from sprintforecast.storage import Repository
    from sprintforecast.web import ui

    mark_production_access(data_dir)
    data = Repository(data_dir).load(TEAM)
    sprint = next(s for s in data.sprints if s.end > date(2026, 10, 15))
    sprint.forecast_plan = 500.0  # much larger than the current plan
    fc = build_forecast(data, date(2026, 10, 15))
    entry = fc.entry(sprint.id)
    text = ui._production_split_note(fc, entry, data, "PT")
    assert text is not None
    plan, share = entry.result.plan, ui.distribution(fc, entry).production_share
    assert f"bis zu {ui.fmt(plan * share, 1)} PT" in text
    assert f"{ui.fmt(plan - plan * share, 1)} PT für" in text


def test_new_team_form_explains_the_areas_and_saves_them_off(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    goto(at, "neues_team")
    at.text_input[0].set_value("team-b").run()
    assert any("**Optionale Bereiche:**" in m.value for m in at.markdown)
    for key in ("features.products", "features.po", "features.production"):
        assert at.selectbox(key=f"new-team-b-{key}").value == "off"
    at.text_input(key="new-team-b-sprint.first_id").set_value("2026.15")
    click(at, "Team anlegen")
    saved = yaml.safe_load((data_dir / "team-b" / "team.yaml").read_text())
    assert saved["features"] == {"products": False, "po": False, "production": False}


def test_settings_page_switches_areas_independently(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    set_features(data_dir, products=False, po=False, production=False)
    at = start(data_dir, monkeypatch)
    goto(at, "einstellungen")
    at.selectbox(key=f"settings-{TEAM}-features.production").set_value("on")
    click(at, "Speichern")
    saved = yaml.safe_load((data_dir / TEAM / "team.yaml").read_text())
    assert saved["features"] == {"products": False, "po": False, "production": True}


# --- Production access without product distribution ---------------------------------------------


def test_production_without_products_is_recorded_per_sprint(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    set_features(data_dir, products=False, po=False, production=True)
    at = start(data_dir, monkeypatch)
    goto(at, "planning")
    at.selectbox(key="planning-sprint").set_value("2026.22").run()
    at.radio(key="planning-step").set_value(1).run()
    assert any("Themen mit Produktionszugriff" in s.value for s in at.subheader)
    at.number_input(key="production-planned-2026.22").set_value(2.0).run()
    click(at, "Speichern und weiter")
    sprint = Repository(data_dir).load(TEAM).sprint("2026.22")
    assert sprint.production_planned == 2.0
    goto(at, "review")
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    at.number_input(key="production-done-2026.21").set_value(1.5)
    at.number_input(key="velocity-2026.21").set_value(9.0)
    click(at, "Review speichern")
    assert Repository(data_dir).load(TEAM).sprint("2026.21").production_done == 1.5


def test_sprint_level_production_values_roundtrip_and_validate(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load(TEAM)
    sprint = data.sprint("2026.22")
    sprint.production_planned = 2.0
    repo.save_sprint(TEAM, sprint)
    assert repo.load(TEAM).sprint("2026.22").production_planned == 2.0
    sprint.production_planned = -1.0
    errors = [i.message for i in check_team(repo.load(TEAM), date(2026, 10, 15))]
    assert not any("production_planned" in m for m in errors)  # 2.0 was stored
    data.sprints = [s for s in data.sprints if s.id != "2026.22"] + [sprint]
    issues = check_team(data, date(2026, 10, 15))
    assert any("production_planned darf nicht negativ sein" in i.message for i in issues)


def test_distribution_totals_use_sprint_values_without_products():
    from sprintforecast.products import Distribution

    sprint = Sprint("s", date(2026, 1, 1), date(2026, 1, 15))
    sprint.production_planned = 3.0
    d = Distribution(sprint=sprint, plan=10.0, plan_frozen=False, basis=None, available=10.0)
    assert d.total("production_planned") == 3.0
    assert d.total("production_done") is None


# --- Command line -------------------------------------------------------------------------

runner = CliRunner()


def cli(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        cli_app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )


def test_cli_product_commands_need_the_product_distribution(data_dir: Path):
    set_features(data_dir, products=False)
    for command in ("products", "product-list"):
        result = cli(data_dir, command, TEAM)
        assert result.exit_code == 1 and "Produktverteilung" in result.output


def test_cli_distribution_table_hides_po_when_off(data_dir: Path):
    out = cli(data_dir, "products", TEAM, "2026.20")
    assert out.exit_code == 0 and "PO" in out.output
    set_features(data_dir, po=False)
    off = cli(data_dir, "products", TEAM, "2026.20")
    assert off.exit_code == 0
    header = next(
        line for line in off.output.splitlines() if "Produkt" in line and "Standard" in line
    )
    assert " PO " not in header


def test_switch_settings_accept_the_german_words():
    setting = next(s for s in SETTINGS if s.key == "features.po")
    assert setting.parse("an") == "on" and setting.parse("aus") == "off"
