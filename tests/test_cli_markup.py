# SPDX-License-Identifier: EUPL-1.2
"""Freitext aus den Daten (Namen, Sprint-IDs, Pfade) wird in der Kommandozeile nicht als
Rich-Markup ausgewertet: „[x]“ bleibt stehen, „[/x]“ bricht die Ausgabe nicht ab."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprintforecast.cli import app

runner = CliRunner(env={"COLUMNS": "200"})


def run(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args], input=input
    )


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.fixture
def klammern(data_dir: Path) -> Path:
    """Demo-Daten, deren Namen wie Rich-Markup aussehen."""
    team = data_dir / "demo"
    replace(team / "team.yaml", "name: Demo-Team", "name: '[/x] Team'")
    replace(team / "people.yaml", "name: Anna", "name: 'Eva [x]'")
    replace(team / "people.yaml", "name: Ben", "name: 'Ben [/x]'")
    replace(team / "products.yaml", "name: Webshop", "name: 'Shop [/x]'")
    replace(team / "products.yaml", "po: Alex", "po: 'Alex [x]'")
    return data_dir


@pytest.mark.parametrize(
    ("args", "input", "expected"),
    [
        pytest.param(["forecast", "demo"], None, ["[/x] Team"], id="forecast"),
        pytest.param(["analyse", "demo"], None, ["[/x] Team"], id="analyse"),
        pytest.param(["sprints", "demo"], None, ["[/x] Team"], id="sprints"),
        pytest.param(["personen", "demo"], "q\n", ["Eva [x]", "Ben [/x]"], id="personen"),
        pytest.param(["kapazitaet", "demo"], None, ["Eva [x]", "Ben [/x]"], id="kapazitaet"),
        pytest.param(["produkte", "demo"], None, ["Shop [/x]", "Alex [x]"], id="produkte"),
        pytest.param(["produktliste", "demo"], "q\n", ["Shop [/x]", "Alex [x]"], id="produktliste"),
        pytest.param(
            ["fehltage", "demo", "2026.23"],
            "0\n0\n0\n0\n",
            ["Eva [x]", "Ben [/x]"],
            id="fehltage",
        ),
        pytest.param(
            ["personen", "demo"],
            "f\nEva\n2026-11-01\n0.8\nq\n",
            ["Personen: Eva [x], Ben [/x]"],
            id="personen-auswahl",
        ),
    ],
)
def test_names_with_brackets_are_shown_literally(
    klammern: Path, args: list[str], input: str | None, expected: list[str]
):
    result = run(klammern, *args, input=input)
    assert result.exit_code == 0, result.output
    for text in expected:
        assert text in result.output


def test_sprint_id_with_brackets(data_dir: Path):
    neu = data_dir / "neu"
    neu.mkdir()
    team = {
        "name": "Neu",
        "unit": "PT",
        "sprint": {"length_days": 14, "first": {"id": "[x]", "start": date(2026, 10, 7)}},
    }
    person = {"id": "eva", "name": "Eva", "memberships": [{"from": date(2025, 1, 1)}]}
    people = {"people": [person]}
    (neu / "team.yaml").write_text(yaml.safe_dump(team), encoding="utf-8")
    (neu / "people.yaml").write_text(yaml.safe_dump(people), encoding="utf-8")

    for args in (["sprints", "neu"], ["forecast", "neu"]):
        result = run(data_dir, *args)
        assert result.exit_code == 0, result.output
        assert "[x]" in result.output

    result = run(data_dir, "fehltage", "neu", "[/x]")
    assert result.exit_code == 1
    assert "Sprint [/x] liegt nicht in der Sprintfolge des Teams." in result.output
    result = run(data_dir, "forecast", "neu", "--rechenweg", "[/x]")
    assert result.exit_code == 1
    assert "Sprint [/x] nicht in der Prognose." in result.output


def test_unknown_team_with_brackets(data_dir: Path):
    for team in ("[x]", "[/x]"):
        result = run(data_dir, "forecast", team)
        assert result.exit_code == 1, result.output
        assert f"Team '{team}' nicht gefunden" in result.output


def test_check_messages_with_brackets(data_dir: Path):
    demo = data_dir / "demo"
    replace(demo / "people.yaml", "people:\n", "people:\n- id: '[x]'\n  name: Zoe\n")
    sprint = demo / "sprints" / "2026.21.yaml"
    replace(sprint, "absences:\n", "absences:\n  '[/x]': 1\n")

    result = run(data_dir, "pruefen")
    assert result.exit_code == 1
    assert "people.yaml: [x]: keine Zugehörigkeit" in result.output
    assert "Fehltage für unbekannte Person '[/x]'" in result.output


def test_path_with_brackets_and_backslashes(data_dir: Path):
    folder = Path(r"C:\daten\[y]")
    result = run(data_dir, "datenordner", str(folder))
    assert result.exit_code == 1
    assert f"Ordner nicht gefunden: {folder}" in result.output
