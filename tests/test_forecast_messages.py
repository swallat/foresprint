# SPDX-License-Identifier: EUPL-1.2
"""Forecast without a first sprint or with a mismatching sprint ID: a message with instructions
instead of a raw ValueError."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.calendar import id_fits_numbering, next_id
from sprintforecast.cli import app as cli_app
from sprintforecast.model import Numbering
from sprintforecast.storage import AS_OF_ENV, DATA_ENV, DataError, Repository
from sprintforecast.validate import Level, check_team

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
runner = CliRunner(env={"COLUMNS": "200"})
TODAY = date(2026, 10, 15)
YEARLY, SEQUENTIAL = Numbering.YEARLY, Numbering.SEQUENTIAL


def without_first_sprint(data_dir: Path) -> None:
    """Neither sprint files nor the start and ID of the first sprint in team.yaml."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    for sprint in data.sprints:
        repo.delete_sprint("demo", sprint.id)
    data.team.sprint.first_id = data.team.sprint.first_start = None
    repo.save_team(data.team)


def rename_sprint(data_dir: Path, old_id: str, new_id: str, numbering: Numbering = YEARLY) -> None:
    """The sprint has a hand-assigned ID, as after an import (the last one is 2026.22)."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprint(old_id)
    repo.delete_sprint("demo", old_id)
    sprint.id = new_id
    repo.save_sprint("demo", sprint)
    data.team.sprint.numbering = numbering
    repo.save_team(data.team)


def messages(data_dir: Path) -> list[tuple[Level, str, str]]:
    data = Repository(data_dir).load("demo")
    return [(i.level, i.where, i.message) for i in check_team(data, TODAY)]


def numbering_errors(data_dir: Path) -> list[tuple[str, str]]:
    return [
        (where, message)
        for level, where, message in messages(data_dir)
        if level is Level.ERROR and "Nummerierung" in message
    ]


# --- next_id and following_sprint --------------------------------------------------------------


@pytest.mark.parametrize(
    ("previous", "start", "numbering"),
    [
        ("2026.22b", date(2026, 10, 28), YEARLY),
        ("2026.", date(2026, 10, 28), YEARLY),
        ("S12", date(2026, 10, 28), SEQUENTIAL),
        ("", date(2026, 10, 28), SEQUENTIAL),
        ("nan", date(2026, 10, 28), SEQUENTIAL),
        ("inf", date(2026, 10, 28), SEQUENTIAL),
    ],
)
def test_next_id_outside_the_numbering_is_a_data_error(previous, start, numbering):
    with pytest.raises(DataError, match="passt nicht zur Nummerierung") as caught:
        next_id(previous, start, numbering)
    assert f"'{previous}'" in str(caught.value)


def test_next_id_error_names_the_expected_form():
    with pytest.raises(DataError, match=r"JJJJ\.N"):
        next_id("2026.22b", date(2026, 10, 28), YEARLY)
    with pytest.raises(DataError, match="eine Zahl"):
        next_id("S12", date(2026, 10, 28), SEQUENTIAL)


@pytest.mark.parametrize(
    ("previous", "start", "numbering", "expected"),
    [
        ("2026.22", date(2026, 10, 28), YEARLY, "2026.23"),
        ("2026.22", date(2027, 1, 6), YEARLY, "2027.1"),
        ("39", date(2026, 1, 7), YEARLY, "2026.1"),  # numbering change
        ("S12", date(2026, 1, 7), YEARLY, "2026.1"),
        # the counter only counts within the same year
        ("2026.22b", date(2027, 1, 6), YEARLY, "2027.1"),
        ("22", date(2026, 10, 28), SEQUENTIAL, "23"),
        ("22.0", date(2026, 10, 28), SEQUENTIAL, "23"),
    ],
)
def test_next_id_keeps_the_ids_it_always_produced(previous, start, numbering, expected):
    assert next_id(previous, start, numbering) == expected


@pytest.mark.parametrize(
    "sprint_id",
    [
        "2026.22",
        "2026.22b",
        "2026.",
        "2026.2.1",
        "39",
        "S12",
        "S",
        "",
        "12.0",
        "nan",
        "inf",
        "²",
        "²2.5",
    ],
)
@pytest.mark.parametrize("numbering", [YEARLY, SEQUENTIAL])
@pytest.mark.parametrize("start", [date(2026, 10, 28), date(2027, 1, 6)])
def test_fits_numbering_agrees_with_next_id(sprint_id, numbering, start):
    """The check reports exactly the IDs from which next_id cannot form an ID for this start of
    the following sprint (with YYYY.N the counter only continues in the following sprint's year)."""
    try:
        next_id(sprint_id, start, numbering)
        works = True
    except DataError:
        works = False
    assert id_fits_numbering(sprint_id, start, numbering) is works


def test_fits_numbering_accepts_a_letter_suffix_when_the_year_changes():
    assert not id_fits_numbering("2026.22b", date(2026, 12, 23), YEARLY)
    assert id_fits_numbering("2026.22b", date(2027, 1, 6), YEARLY)  # becomes 2027.1


# --- Check (validate) --------------------------------------------------------------------------


def test_check_flags_a_last_sprint_id_that_does_not_fit_yearly(data_dir: Path):
    rename_sprint(data_dir, "2026.22", "2026.22b")
    [(where, message)] = numbering_errors(data_dir)
    assert where == "sprints/2026.22b.yaml"
    assert "ID passt nicht zur Nummerierung" in message and "JJJJ.N" in message


def test_check_flags_a_last_sprint_id_that_does_not_fit_sequential(data_dir: Path):
    rename_sprint(data_dir, "2026.22", "S12", SEQUENTIAL)
    [(where, message)] = numbering_errors(data_dir)
    assert where == "sprints/S12.yaml"
    assert "ID passt nicht zur Nummerierung" in message and "eine Zahl" in message


def test_check_accepts_the_demo_data_and_a_switch_of_the_numbering(data_dir: Path):
    assert numbering_errors(data_dir) == []
    rename_sprint(data_dir, "2026.22", "39")  # continuous ID, yearly numbering: allowed
    assert numbering_errors(data_dir) == []
    rename_sprint(data_dir, "39", "40", SEQUENTIAL)
    assert numbering_errors(data_dir) == []


def test_check_follows_the_chain_from_the_running_sprint(data_dir: Path):
    """Calendar and absences form the following IDs from the current sprint (2026.21)."""
    rename_sprint(data_dir, "2026.21", "2026.21b")
    [(where, _)] = numbering_errors(data_dir)
    assert where == "sprints/2026.21b.yaml"


def test_check_ignores_finished_sprints_before_the_last(data_dir: Path):
    rename_sprint(data_dir, "2026.19", "2026.19b")
    assert numbering_errors(data_dir) == []


def test_check_accepts_a_suffix_when_the_next_sprint_starts_in_the_next_year(data_dir: Path):
    """2026.22b only ends in 2027: next_id forms 2027.1, the forecast runs, the check is silent."""
    from sprintforecast.forecast import build_forecast

    rename_sprint(data_dir, "2026.22", "2026.22b")
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprint("2026.22b")
    sprint.start, sprint.end = date(2026, 12, 23), date(2027, 1, 6)
    repo.save_sprint("demo", sprint)
    assert numbering_errors(data_dir) == []
    ids = [e.sprint.id for e in build_forecast(repo.load("demo"), TODAY).entries]
    assert "2027.1" in ids


def test_check_flags_the_first_id_while_there_are_no_sprint_files(data_dir: Path):
    without_first_sprint(data_dir)
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.sprint.first_id, data.team.sprint.first_start = "S12", date(2026, 10, 14)
    data.team.sprint.numbering = SEQUENTIAL
    repo.save_team(data.team)
    [(where, _)] = numbering_errors(data_dir)
    assert where == "team.yaml"


# --- Command line ------------------------------------------------------------------------------


def run(data_dir: Path, *args: str):
    return runner.invoke(cli_app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args])


def text(result) -> str:
    """Output without the console's line breaks."""
    return " ".join(result.output.split())


def test_cli_forecast_without_first_sprint_is_a_message(data_dir: Path):
    without_first_sprint(data_dir)
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # no ValueError
    assert "Team demo: Es ist noch kein Sprint erfasst" in text(result)
    assert "Start und ID des ersten Sprints eintragen" in text(result)
    assert "Traceback" not in result.output


def test_cli_forecast_with_unfitting_id_is_a_message(data_dir: Path):
    rename_sprint(data_dir, "2026.22", "2026.22b")
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert "Sprint-ID '2026.22b' passt nicht zur Nummerierung" in text(result)
    assert "Traceback" not in result.output


def test_cli_check_reports_the_unfitting_id(data_dir: Path):
    rename_sprint(data_dir, "2026.22", "S12", SEQUENTIAL)
    result = run(data_dir, "check")
    assert result.exit_code == 1, result.output
    assert "sprints/S12.yaml: ID passt nicht zur Nummerierung" in text(result)


# --- Web UI ------------------------------------------------------------------------------------


def start(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def test_web_without_first_sprint_shows_the_message(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    without_first_sprint(data_dir)
    app = start(data_dir, monkeypatch)
    [error] = app.error
    assert "Es ist noch kein Sprint erfasst" in error.value
    assert "Start und ID des ersten Sprints eintragen" in error.value
    for page in ("forecast", "personen"):
        goto(app, page)


def test_web_first_sprint_can_be_entered_in_the_settings(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    without_first_sprint(data_dir)
    app = goto(start(data_dir, monkeypatch), "einstellungen")
    assert not app.error
    app.date_input(key="settings-demo-sprint.first_start").set_value(date(2026, 10, 14))
    app.text_input(key="settings-demo-sprint.first_id").set_value("2026.20")
    next(b for b in app.button if b.label == "Speichern").click().run()
    assert not app.exception, app.exception
    goto(app, "start")
    assert not app.error


def test_web_unfitting_id_shows_the_message(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    rename_sprint(data_dir, "2026.22", "2026.22b")
    app = start(data_dir, monkeypatch)
    [error] = app.error
    assert "Sprint-ID '2026.22b' passt nicht zur Nummerierung" in error.value
    assert "JJJJ.N" in error.value
    goto(app, "forecast")
    assert any("passt nicht zur Nummerierung" in e.value for e in app.error)
    for page in ("einstellungen", "personen"):  # reachable without a forecast
        goto(app, page)
        assert not app.error, (page, [e.value for e in app.error])


def test_web_unfitting_id_of_an_earlier_sprint_shows_the_message(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """The absences page forms the following IDs from the current sprint (2026.21) itself."""
    rename_sprint(data_dir, "2026.21", "2026.21b")
    app = goto(start(data_dir, monkeypatch), "fehltage")
    [error] = app.error
    assert "Sprint-ID '2026.21b' passt nicht zur Nummerierung" in error.value


def test_cli_report_names_the_team_with_the_unfitting_id(data_dir: Path):
    import shutil

    shutil.copytree(data_dir / "demo", data_dir / "aaa")
    repo = Repository(data_dir)
    data = repo.load("aaa")
    sprint = data.sprint("2026.22")
    repo.delete_sprint("aaa", "2026.22")
    sprint.id = "2026.22b"
    repo.save_sprint("aaa", sprint)
    result = run(data_dir, "report")
    assert result.exit_code == 1, result.output
    assert "Team aaa: Sprint-ID '2026.22b' passt nicht zur Nummerierung" in text(result)
