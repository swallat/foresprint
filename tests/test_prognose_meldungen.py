# SPDX-License-Identifier: EUPL-1.2
"""Prognose ohne ersten Sprint oder mit unpassender Sprint-ID: Meldung mit Handlungsanweisung
statt rohem ValueError."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.calendar import id_fits_numbering, next_id
from sprintforecast.cli import app as cli_app
from sprintforecast.model import Numbering
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, DataError, Repository
from sprintforecast.validate import Level, check_team

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
runner = CliRunner(env={"COLUMNS": "200"})
TODAY = date(2026, 10, 15)
YEARLY, SEQUENTIAL = Numbering.YEARLY, Numbering.SEQUENTIAL


def without_first_sprint(data_dir: Path) -> None:
    """Weder Sprintdateien noch Start und ID des ersten Sprints in team.yaml."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    for sprint in data.sprints:
        repo.delete_sprint("demo", sprint.id)
    data.team.sprint.first_id = data.team.sprint.first_start = None
    repo.save_team(data.team)


def rename_sprint(data_dir: Path, old_id: str, new_id: str, numbering: Numbering = YEARLY) -> None:
    """Der Sprint trägt eine hand vergebene ID, wie nach einem Import (der letzte ist 2026.22)."""
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


# --- next_id und following_sprint --------------------------------------------------------------


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
        ("39", date(2026, 1, 7), YEARLY, "2026.1"),  # Wechsel der Nummerierung
        ("S12", date(2026, 1, 7), YEARLY, "2026.1"),
        ("2026.22b", date(2027, 1, 6), YEARLY, "2027.1"),  # Zähler zählt nur im selben Jahr
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
def test_fits_numbering_agrees_with_next_id(sprint_id, numbering):
    """Die Prüfung meldet genau die IDs, aus denen next_id keine Folge-ID bilden kann (bei
    JJJJ.N unabhängig vom Datum: im Jahr der ID selbst)."""
    year = sprint_id.partition(".")[0]
    start = date(int(year), 10, 28) if year.isdigit() and year.isascii() else date(2026, 10, 28)
    try:
        next_id(sprint_id, start, numbering)
        works = True
    except DataError:
        works = False
    assert id_fits_numbering(sprint_id, numbering) is works


# --- Prüfung (validate) ------------------------------------------------------------------------


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
    rename_sprint(data_dir, "2026.22", "39")  # fortlaufende ID, jährliche Nummerierung: erlaubt
    assert numbering_errors(data_dir) == []
    rename_sprint(data_dir, "39", "40", SEQUENTIAL)
    assert numbering_errors(data_dir) == []


def test_check_looks_only_at_the_last_sprint(data_dir: Path):
    rename_sprint(data_dir, "2026.21", "2026.21b")
    assert numbering_errors(data_dir) == []


def test_check_flags_the_first_id_while_there_are_no_sprint_files(data_dir: Path):
    without_first_sprint(data_dir)
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.sprint.first_id, data.team.sprint.first_start = "S12", date(2026, 10, 14)
    data.team.sprint.numbering = SEQUENTIAL
    repo.save_team(data.team)
    [(where, _)] = numbering_errors(data_dir)
    assert where == "team.yaml"


# --- Kommandozeile -----------------------------------------------------------------------------


def run(data_dir: Path, *args: str):
    return runner.invoke(cli_app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args])


def text(result) -> str:
    """Ausgabe ohne Zeilenumbrüche der Konsole."""
    return " ".join(result.output.split())


def test_cli_forecast_without_first_sprint_is_a_message(data_dir: Path):
    without_first_sprint(data_dir)
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # kein ValueError
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
    result = run(data_dir, "pruefen")
    assert result.exit_code == 1, result.output
    assert "sprints/S12.yaml: ID passt nicht zur Nummerierung" in text(result)


# --- Weboberfläche -----------------------------------------------------------------------------


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
    for page in ("forecast", "einstellungen"):
        goto(app, page)


def test_web_unfitting_id_of_an_earlier_sprint_shows_the_message(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Die Fehltage-Seite bildet die Folge-IDs ab dem laufenden Sprint (2026.21) selbst."""
    rename_sprint(data_dir, "2026.21", "2026.21b")
    app = goto(start(data_dir, monkeypatch), "fehltage")
    [error] = app.error
    assert "Sprint-ID '2026.21b' passt nicht zur Nummerierung" in error.value
