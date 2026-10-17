# SPDX-License-Identifier: EUPL-1.2
"""Falsche Typen und Strukturen in den YAML-Dateien: Meldung mit Dateiname statt Absturz."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.cli import app as cli_app
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, DataError, Repository
from sprintforecast.validate import Level, check_all

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
TODAY = date(2026, 10, 15)
runner = CliRunner(env={"COLUMNS": "200"})

TEAM = "team.yaml"
PEOPLE = "people.yaml"
PRODUCTS = "products.yaml"
SPRINT = "sprints/2026.21.yaml"


def edit(data_dir: Path, name: str, change: Callable[[dict], None]) -> Path:
    path = data_dir / "demo" / name
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(content)
    path.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    return path


def setting(key: str, value) -> Callable[[dict], None]:
    return lambda d: d.__setitem__(key, value)


def nested(outer: str, key: str, value) -> Callable[[dict], None]:
    return lambda d: d[outer].__setitem__(key, value)


def person(**fields) -> Callable[[dict], None]:
    return lambda d: d.__setitem__("people", [{"id": "x", "name": "X", **fields}])


def product_share(value) -> Callable[[dict], None]:
    return lambda d: d["products"][0].__setitem__("share", value)


def first_prognosis(**fields) -> Callable[[dict], None]:
    return lambda d: d.__setitem__("prognoses", [{"at": "2026-10-01T10:00:00", **fields}])


CASES = [
    pytest.param(TEAM, setting("sprint", "foo"), id="team-sprint-text"),
    pytest.param(TEAM, setting("forecast", [1, 2]), id="team-forecast-list"),
    pytest.param(TEAM, setting("capacity", 5), id="team-capacity-number"),
    pytest.param(TEAM, setting("features", "ja"), id="team-features-text"),
    pytest.param(TEAM, setting("features", True), id="team-features-bool"),
    pytest.param(TEAM, nested("sprint", "first", 5), id="team-sprint-first-number"),
    pytest.param(PEOPLE, setting("people", 5), id="people-number"),
    pytest.param(PEOPLE, setting("people", [1, 2]), id="people-entries-numbers"),
    pytest.param(PEOPLE, person(memberships="foo"), id="people-memberships-text"),
    pytest.param(PEOPLE, person(memberships=[5]), id="people-membership-number"),
    pytest.param(PRODUCTS, setting("products", "foo"), id="products-text"),
    pytest.param(PRODUCTS, product_share("50%"), id="products-share-percent-text"),
    pytest.param(PRODUCTS, product_share("abc"), id="products-share-text"),
    pytest.param(PRODUCTS, product_share([1]), id="products-share-list"),
    pytest.param(SPRINT, setting("absences", [{"anna": 2}]), id="sprint-absences-list"),
    pytest.param(SPRINT, setting("products", [{"app": 1}]), id="sprint-products-list"),
    pytest.param(SPRINT, setting("expected_absences", "foo"), id="sprint-expected-text"),
    pytest.param(SPRINT, setting("planning", "foo"), id="sprint-planning-text"),
    pytest.param(SPRINT, nested("planning", "corrections", 5), id="sprint-corrections-number"),
    pytest.param(SPRINT, setting("prognoses", "foo"), id="sprint-prognoses-text"),
    pytest.param(SPRINT, setting("prognoses", [5]), id="sprint-prognosis-number"),
    pytest.param(SPRINT, first_prognosis(preplanned="foo"), id="sprint-preplanned-text"),
]


@pytest.mark.parametrize(("name", "change"), CASES)
def test_wrong_structure_is_a_data_error_naming_the_file(
    data_dir: Path, name: str, change: Callable[[dict], None]
):
    path = edit(data_dir, name, change)
    with pytest.raises(DataError) as caught:
        Repository(data_dir).load("demo")
    assert str(path) in str(caught.value)


@pytest.mark.parametrize(("name", "change"), CASES[:3] + CASES[7:8] + CASES[14:15])
def test_check_reports_the_file_instead_of_failing(
    data_dir: Path, name: str, change: Callable[[dict], None]
):
    path = edit(data_dir, name, change)
    issues = check_all(Repository(data_dir), TODAY)["demo"]
    assert [i.level for i in issues] == [Level.ERROR]
    assert str(path) in issues[0].message


def test_cli_shows_a_message_with_exit_code_1(data_dir: Path):
    path = edit(data_dir, TEAM, setting("sprint", "foo"))
    result = runner.invoke(
        cli_app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", "forecast", "demo"]
    )
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert path.name in result.output.replace("\n", "")


def test_web_shows_the_message_for_a_broken_team_file(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Auch die Navigation (enabled_pages) und der Seitenaufbau stürzen nicht ab."""
    path = edit(data_dir, TEAM, setting("sprint", "foo"))
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    at.switch_page("seiten/forecast.py").run()
    assert not at.exception, at.exception
    assert any(path.name in e.value for e in at.error)


def test_valid_files_with_empty_sections_still_load(data_dir: Path):
    """Leere Abschnitte (``sprint:`` ohne Inhalt, ``absences: {}``) bleiben gültig."""
    edit(data_dir, TEAM, setting("features", None))
    edit(data_dir, SPRINT, lambda d: d.update(absences=None, products=None, prognoses=[]))
    data = Repository(data_dir).load("demo")
    assert data.sprint("2026.21").absences == {}


def test_quoted_share_number_is_still_accepted(data_dir: Path):
    edit(data_dir, PRODUCTS, product_share("0.25"))
    products = Repository(data_dir).load("demo").products
    assert products[0].share == 0.25
