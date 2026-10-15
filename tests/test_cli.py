# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprintforecast.cli import app

runner = CliRunner(env={"COLUMNS": "200"})


def run(data_dir: Path, *args: str, input: str | None = None):
    result = runner.invoke(
        app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args], input=input
    )
    return result


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_forecast_and_report(data_dir: Path):
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert "2026.24" in result.output and "Trend" in result.output

    result = run(data_dir, "bericht", "demo")
    assert result.exit_code == 0, result.output
    report = (data_dir / "demo" / "FORECAST.md").read_text()
    assert "# Sprint-Forecast Demo-Team" in report
    assert "| 2026.21 |" in report and "**laufend**" in report
    assert "```mermaid" in report


def test_fehltage_for_future_sprint_creates_file(data_dir: Path):
    # Sprint 2026.23 hat noch keine Datei; aktive Personen: Anna, Ben, Cem, Dana
    result = run(data_dir, "fehltage", "demo", "2026.23", input="2\n0\n1,5\n0\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert sprint["absences"] == {"anna": 2, "cem": 1.5}
    assert sprint["start"].isoformat() == "2026-11-11"
    assert "Prognose Sprint 2026.23" in result.output
    # Kapazität: Anna 8 + Ben 5 + Cem 8.5 + Dana 10
    assert "31,5" in result.output


def test_fehltage_rejects_invalid_number(data_dir: Path):
    result = run(data_dir, "fehltage", "demo", "2026.23", input="abc\n1\n0\n0\n0\n")
    assert result.exit_code == 0, result.output
    assert "Bitte eine Zahl eingeben" in result.output


def test_review_freezes_capacity(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    result = run(data_dir, "review", "demo", "2026.21", input="y\n9,5\n0.1\n")
    assert result.exit_code == 0, result.output
    sprint = load(path)
    assert sprint["capacity"] == 25.5
    assert sprint["velocity"] == 9.5
    assert sprint["scope_creep"] == 0.1


def test_planning_reports_delta(data_dir: Path):
    result = run(data_dir, "planning", "demo", input="y\n1\n8\n0.5\n9\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["forecast_ist"] == 9
    assert sprint["planning"] == {"carryover": 1, "backlog": 8, "corrections": [0.5]}
    assert "Delta 0,50" in result.output  # Forecast PLAN 9,0 − Planning 8,5


def test_personen_change_fte(data_dir: Path):
    result = run(data_dir, "personen", "demo", input="f\nanna\n2026-11-01\n0.8\nq\n")
    assert result.exit_code == 0, result.output
    assert "n = neue Person, f = FTE ändern, a = Austritt, q = fertig" in result.output
    anna = load(data_dir / "demo" / "people.yaml")["people"][0]
    assert anna["memberships"][-2]["to"].isoformat() == "2026-10-31"
    assert anna["memberships"][-1] == {
        "from": anna["memberships"][-1]["from"],
        "to": None,
        "fte": 0.8,
    }


def test_pruefen_fails_on_error(data_dir: Path):
    assert run(data_dir, "pruefen").exit_code == 0
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    path.write_text(path.read_text().replace("cem: 5", "unbekannt: 5"))
    result = run(data_dir, "pruefen")
    assert result.exit_code == 1
    assert "unbekannte Person" in result.output


def test_init_new_team(tmp_path: Path):
    answers = [
        "Team A", "PT", "by", "10", "14", "yearly", "2026-10-14", "2026.20",
        "40", "", "", "", "", "",
    ]  # fmt: skip
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["capacity"] == {"overhead_share": 0.1, "region": "BY", "rounding": 1}
    assert team["sprint"]["first"] == {"id": "2026.20", "start": date(2026, 10, 14)}
    assert team["forecast"]["reference_capacity"] == 40
    assert run(tmp_path, "pruefen").exit_code == 0


def test_einstellungen_changes_and_validates(data_dir: Path):
    # Reihenfolge: Name, Einheit, Bundesland, Overhead, Länge, Nummerierung,
    # Referenz, Fenster, Trend, Roadmap, Horizont, Rundung, Speichern?
    answers = ["", "SP", "xx", "he", "", "", "", "-5", "50", "", "flat", "75", "", "", "y"]
    result = run(data_dir, "einstellungen", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Erlaubt:" in result.output  # Bundesland xx
    assert "muss ≥ 1" in result.output  # Referenz -5
    assert "rückwirkend" in result.output
    team = load(data_dir / "demo" / "team.yaml")
    assert team["unit"] == "SP"
    assert team["capacity"]["region"] == "HE"
    assert team["forecast"]["reference_capacity"] == 50
    assert team["forecast"]["trend_mode"] == "flat"
    assert team["forecast"]["roadmap_share"] == 0.75
    assert "first" in team["sprint"]  # unverändert übernommen


def test_einstellungen_without_changes(data_dir: Path):
    before = (data_dir / "demo" / "team.yaml").read_text()
    result = run(data_dir, "einstellungen", "demo", input="\n" * 12)
    assert result.exit_code == 0, result.output
    assert "Keine Änderungen" in result.output
    assert (data_dir / "demo" / "team.yaml").read_text() == before


def test_review_shows_plausibility_warning(data_dir: Path):
    result = run(data_dir, "review", "demo", "2026.21", input="y\n9.5\n30\n")
    assert result.exit_code == 0, result.output
    assert "scope_creep 30" in result.output


def test_commit_refused_on_errors(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    path.write_text(path.read_text().replace("cem: 5", "unbekannt: 5"))
    result = run(data_dir, "planning", "demo", "2026.22", "--commit", input="n\n10\n")
    assert result.exit_code == 1
    assert "Nicht committet" in result.output


def test_planning_prefills_forecast_ist(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    result = run(data_dir, "planning", "demo", "2026.22", input="y\n1.5\n11\n\n\n")
    assert result.exit_code == 0, result.output
    assert "Vorbelegt mit Überkipper + Backlog" in result.output
    sprint = load(path)
    assert sprint["forecast_ist"] == 12.5
    assert sprint["planning"] == {"carryover": 1.5, "backlog": 11, "corrections": []}


def test_planning_without_control_calculation(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    result = run(data_dir, "planning", "demo", "2026.22", input="n\n11\n")
    assert result.exit_code == 0, result.output
    sprint = load(path)
    assert sprint["forecast_ist"] == 11
    assert "planning" not in sprint


def test_personen_new_person_gets_id_and_former_hidden(data_dir: Path):
    result = run(data_dir, "personen", "demo", input="n\nJörg Müller\n\n2026-11-01\n1\nq\n")
    assert result.exit_code == 0, result.output
    assert "Emil" not in result.output  # ausgeschieden → ausgeblendet
    assert "ehemalige Person(en) ausgeblendet" in result.output
    people = load(data_dir / "demo" / "people.yaml")["people"]
    assert people[-1]["id"] == "joerg-mueller"
    assert people[-1]["name"] == "Jörg Müller"
    shown = run(data_dir, "personen", "demo", "--ehemalige", input="q\n")
    assert "Emil" in shown.output


def test_default_data_dir_is_current_directory(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPRINTFORECAST_DATEN", raising=False)
    monkeypatch.chdir(data_dir)
    result = runner.invoke(app, ["--stichtag", "2026-10-15", "forecast", "demo"])
    assert result.exit_code == 0, result.output
    assert "Demo-Team" in result.output


def test_version_and_help_without_command():
    from sprintforecast import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output
    result = runner.invoke(app, [])
    assert result.exit_code == 0 and "forecast" in result.output
