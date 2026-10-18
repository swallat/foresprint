# SPDX-License-Identifier: EUPL-1.2
"""Prüfung meldet stille Annahmen beim Laden (doppelte Schlüssel, leere Zahlenfelder) als
Hinweis mit Datei, Zeile und Schlüsselpfad. Laden und Rechnen bleiben unverändert."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprintforecast.cli import app as cli_app
from sprintforecast.forecast import build_forecast
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository
from sprintforecast.validate import Level, check_all, check_team_files, check_yaml_text

TODAY = date(2026, 10, 15)
runner = CliRunner(env={"COLUMNS": "250"})
SPRINT = "sprints/2026.20.yaml"


def edit(data_dir: Path, name: str, old: str, new: str) -> Path:
    path = data_dir / "demo" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def issues(data_dir: Path):
    """Nur die Befunde zu stillen Annahmen (andere Plausibilitätshinweise bleiben außen vor)."""
    return check_team_files(data_dir / "demo")


def test_mitgelieferte_beispieldaten_ohne_befunde(data_dir: Path):
    assert issues(data_dir) == []
    assert check_all(Repository(data_dir), TODAY)["demo"] == []


def test_doppelter_schluessel_wird_gemeldet(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    [issue] = issues(data_dir)
    assert issue.level is Level.WARNING
    assert issue.where == SPRINT
    assert "'velocity'" in issue.message
    assert "Zeilen 10, 11" in issue.message
    assert "letzten Eintrag (Zeile 11)" in issue.message


def test_verschachtelter_doppelter_schluessel_nennt_den_pfad(data_dir: Path):
    edit(data_dir, SPRINT, "  anna: 5\n", "  anna: 5\n  anna: 3\n")
    [issue] = issues(data_dir)
    assert issue.where == SPRINT
    assert "absences.anna" in issue.message


def test_doppelter_schluessel_in_liste_nennt_den_listenpfad(data_dir: Path):
    edit(data_dir, "people.yaml", "    fte: 0.5\n", "    fte: 0.5\n    fte: 0.6\n")
    [issue] = issues(data_dir)
    assert issue.where == "people.yaml"
    assert "people[1].memberships[1].fte" in issue.message


def test_zwei_dateien_mit_je_einem_duplikat(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    edit(data_dir, "team.yaml", "name: ", "name: Eins\nname: ")
    found = issues(data_dir)
    assert sorted(i.where for i in found) == [SPRINT, "team.yaml"]
    assert all(i.level is Level.WARNING for i in found)


def test_leerer_wert_fte_wird_gemeldet(data_dir: Path):
    edit(data_dir, "people.yaml", "    fte: 0.5\n", "    fte:\n")
    [issue] = issues(data_dir)
    assert issue.level is Level.WARNING
    assert issue.where == "people.yaml"
    assert "people[1].memberships[1].fte" in issue.message
    assert "Zeile 18" in issue.message
    assert "mit 0" in issue.message


@pytest.mark.parametrize("raw", ["", "null", "~", '""'])
def test_leere_schreibweisen(data_dir: Path, raw: str):
    edit(data_dir, SPRINT, "  anna: 5\n", f"  anna: {raw}\n")
    [issue] = issues(data_dir)
    assert "absences.anna" in issue.message


@pytest.mark.parametrize(
    ("old", "field"),
    [
        ("  carryover: 2.25\n", "planning.carryover"),
        ("  backlog: 9.75\n", "planning.backlog"),
        ("  - 0.75\n", "planning.corrections[0]"),
    ],
)
def test_leere_planungswerte(data_dir: Path, old: str, field: str):
    new = old.split(":")[0] + ":\n" if ":" in old else "  -\n"
    edit(data_dir, SPRINT, old, new)
    [issue] = issues(data_dir)
    assert field in issue.message


def test_legitime_leerwerte_ohne_meldung(data_dir: Path):
    # to: null (Mitgliedschaft ohne Ende), unerfasste Sprintwerte und Region sind gewollt leer
    edit(data_dir, SPRINT, "forecast_ist: 12\n", "forecast_ist:\n")
    edit(data_dir, SPRINT, "capacity: 29\n", "capacity: null\n")
    edit(data_dir, SPRINT, "    done: 3\n", "    done:\n")
    edit(data_dir, "products.yaml", "to: null", "to:")
    assert issues(data_dir) == []


def test_leere_dateien_ohne_meldung(data_dir: Path):
    (data_dir / "demo" / "products.yaml").write_text("", encoding="utf-8")
    (data_dir / "demo" / "people.yaml").write_text("# nur Kommentar\n", encoding="utf-8")
    assert issues(data_dir) == []


def test_ungueltiges_yaml_bleibt_ein_fehler(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: [\n")
    assert issues(data_dir) == []  # keine Folgemeldungen aus der kaputten Datei
    [issue] = check_all(Repository(data_dir), TODAY)["demo"]
    assert issue.level is Level.ERROR


def test_ankerverweise_und_merge_keys_sind_keine_duplikate():
    text = "base: &b\n  x: 1\nother:\n  <<: *b\n  x: 2\nagain: *b\n"
    assert check_yaml_text(text, "x.yaml") == []


def test_rechnung_mit_duplikat_und_leerwert_bleibt_gleich(data_dir: Path, tmp_path: Path):
    clean = tmp_path / "clean"
    shutil.copytree(data_dir, clean)
    # Duplikat: der letzte Wert gewinnt (wie bisher); Leerwert: gilt als 0
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 5\nvelocity: 9.75\n")
    edit(data_dir, SPRINT, "  anna: 5\n", "  anna:\n")
    edit(clean, SPRINT, "  anna: 5\n", "  anna: 0\n")

    loaded = Repository(data_dir).load("demo")
    reference = Repository(clean).load("demo")
    assert loaded == reference
    fc, fc_ref = build_forecast(loaded, TODAY), build_forecast(reference, TODAY)
    assert [(e.sprint.id, e.result) for e in fc.upcoming()] == [
        (e.sprint.id, e.result) for e in fc_ref.upcoming()
    ]
    assert len(issues(data_dir)) == 2  # beides wird gemeldet, nichts bricht ab


def test_kommandozeile_und_streng(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    env = {DATA_ENV: str(data_dir), STICHTAG_ENV: TODAY.isoformat()}
    result = runner.invoke(cli_app, ["pruefen"], env=env)
    assert result.exit_code == 0
    assert "Hinweis sprints/2026.20.yaml" in result.output
    assert "'velocity' steht mehrfach" in result.output
    assert runner.invoke(cli_app, ["pruefen", "--streng"], env=env).exit_code == 1
