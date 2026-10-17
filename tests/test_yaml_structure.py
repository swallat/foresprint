# SPDX-License-Identifier: EUPL-1.2
"""Falsche Typen und Strukturen in den YAML-Dateien: Meldung mit Dateiname statt Absturz."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

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


EXPECTED = {
    "team-sprint-text": "'sprint'",
    "team-forecast-list": "'forecast'",
    "team-capacity-number": "'capacity'",
    "team-features-text": "'features'",
    "team-features-bool": "'features'",
    "team-sprint-first-number": "'sprint.first'",
    "people-number": "'people'",
    "people-entries-numbers": "Feld 'id' fehlt",
    "people-memberships-text": "'memberships'",
    "people-membership-number": "memberships[0]",
    "products-text": "'products'",
    "products-share-percent-text": "share: Zahl erwartet",
    "products-share-text": "share: Zahl erwartet",
    "products-share-list": "share: Zahl erwartet",
    "sprint-absences-list": "'absences'",
    "sprint-products-list": "'products'",
    "sprint-expected-text": "'expected_absences'",
    "sprint-planning-text": "'planning'",
    "sprint-corrections-number": "'corrections'",
    "sprint-prognoses-text": "'prognoses'",
    "sprint-prognosis-number": "Feld 'at' fehlt",
    "sprint-preplanned-text": "'preplanned'",
}


@pytest.mark.parametrize(("name", "change"), CASES)
def test_wrong_structure_is_a_data_error_naming_the_file_and_the_field(
    data_dir: Path, name: str, change: Callable[[dict], None], request: pytest.FixtureRequest
):
    path = edit(data_dir, name, change)
    with pytest.raises(DataError) as caught:
        Repository(data_dir).load("demo")
    assert str(path) in str(caught.value)
    # Das Feld steht in der Meldung: Es kommt aus der Einzelprüfung, nicht aus dem Auffangnetz.
    assert EXPECTED[request.node.callspec.id] in str(caught.value), str(caught.value)
    assert "Aufbau der Datei ungültig" not in str(caught.value)


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


def test_catch_all_turns_unexpected_structure_errors_into_a_data_error(tmp_path: Path):
    """Das Auffangnetz um die Einzelprüfungen: Typ-, Attribut-, Schlüssel- und Überlauffehler
    kommen mit dem Dateinamen als DataError an."""
    from sprintforecast.storage import _well_formed

    for error in (AttributeError("a"), TypeError("b"), KeyError("c"), ValueError("d")):
        with (
            pytest.raises(DataError, match="Aufbau der Datei ungültig") as caught,
            _well_formed("x.yaml"),
        ):
            raise error
        assert str(caught.value).startswith("x.yaml:")
    with pytest.raises(DataError, match="Aufbau der Datei ungültig"), _well_formed("x.yaml"):
        raise OverflowError("e")
    with pytest.raises(DataError, match="schon ein DataError"), _well_formed("x.yaml"):
        raise DataError("schon ein DataError")  # bleibt unverändert


def set_capacity(**fields) -> Callable[[dict], None]:
    return lambda d: d["capacity"].update(fields)


@pytest.mark.parametrize(
    ("name", "change", "fragment"),
    [
        (TEAM, set_capacity(region=["NW"]), "capacity.region"),
        (TEAM, set_capacity(region={"a": 1}), "capacity.region"),
        (TEAM, set_capacity(country=["DE"]), "capacity.country"),
        (TEAM, set_capacity(country=False), "Anführungszeichen"),  # unquotiert NO = Norwegen
        (PEOPLE, person(region=["BY"]), "region"),
        (PEOPLE, person(country=False), "Anführungszeichen"),
    ],
)
def test_country_and_region_must_be_text(
    data_dir: Path, name: str, change: Callable[[dict], None], fragment: str
):
    """Eine Liste als Region ließ die Feiertagsberechnung später mit TypeError abstürzen
    („unhashable type“), obwohl Laden und Prüfung durchliefen."""
    edit(data_dir, name, change)
    with pytest.raises(DataError, match=fragment):
        Repository(data_dir).load("demo")


@pytest.mark.parametrize("raw", ["2026-10-14 00:00:00", "2026-10-14T08:00:00"])
def test_timestamps_are_read_as_dates(data_dir: Path, raw: str):
    """YAML liest ein Datum mit Uhrzeit als datetime; es wird zum Datum (sonst TypeError beim
    Sortieren und Vergleichen)."""
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    text = path.read_text(encoding="utf-8")
    assert "start: 2026-10-14\n" in text
    path.write_text(text.replace("start: 2026-10-14\n", f"start: {raw}\n"), encoding="utf-8")
    sprint = Repository(data_dir).load("demo").sprint("2026.21")
    assert sprint.start == date(2026, 10, 14) and type(sprint.start) is date
    assert check_all(Repository(data_dir), TODAY)["demo"] == []


def test_infinite_whole_number_setting_is_a_data_error(data_dir: Path):
    """``int(inf)`` wirft OverflowError, kein ValueError: früher ein Absturz ohne Dateiname."""
    path = data_dir / "demo" / "team.yaml"
    text = path.read_text(encoding="utf-8")
    assert "window: 5" in text
    path.write_text(text.replace("window: 5", "window: .inf"), encoding="utf-8")
    with pytest.raises(DataError, match=r"team\.yaml"):
        Repository(data_dir).load("demo")


def test_huge_share_number_is_a_data_error(data_dir: Path):
    edit(data_dir, PRODUCTS, product_share(10**400))
    with pytest.raises(DataError, match=r"share: Zahl erwartet"):
        Repository(data_dir).load("demo")


def test_unquoted_first_sprint_id_is_explained(data_dir: Path):
    path = data_dir / "demo" / "team.yaml"
    text = path.read_text(encoding="utf-8")
    assert "id: '2026.1'" in text
    path.write_text(text.replace("id: '2026.1'", "id: 2026.1"), encoding="utf-8")
    with pytest.raises(DataError, match="Anführungszeichen"):
        Repository(data_dir).load("demo")


def test_load_errors_compare_equal_across_folders(data_dir: Path, tmp_path: Path):
    """„Speichern und teilen“ vergleicht die Fehler des Arbeitsstands mit denen des Commits, der
    in einem anderen Ordner entpackt wird: Der Ordner steht nicht im Vergleichstext."""
    from sprintforecast.gitsync import _error_set

    edit(data_dir, TEAM, setting("sprint", "foo"))
    other = tmp_path / "anderer-ordner"
    import shutil

    shutil.copytree(data_dir, other)
    here, there = _error_set(data_dir, TODAY), _error_set(other, TODAY)
    assert here and here == there
    assert not any(str(data_dir) in text for _, where, text in here for text in (where, text))
