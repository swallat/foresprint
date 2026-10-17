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
    result = run(data_dir, "review", "demo", "2026.21", input="y\n9,5\n0.1\nn\n")
    assert result.exit_code == 0, result.output
    sprint = load(path)
    assert sprint["capacity"] == 25.5
    assert sprint["velocity"] == 9.5
    assert sprint["scope_creep"] == 0.1


def test_planning_reports_delta(data_dir: Path):
    # Fehltage prüfen? n · Planning je Produkt? n · Kontrollrechnung? y …
    result = run(data_dir, "planning", "demo", "2026.21", input="n\nn\ny\n1\n8\n0.5\n9\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["forecast_ist"] == 9
    assert sprint["planning"] == {"carryover": 1, "backlog": 8, "corrections": [0.5]}
    assert "Delta 1,00" in result.output  # Forecast PLAN 9,5 − Planning 8,5


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
        "Team A", "PT", "", "", "", "", "by", "", "10", "", "", "14", "yearly", "2026-10-14", "2026.20",
        "40", "", "", "", "", "", "",
    ]  # fmt: skip
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["capacity"] == {"overhead_share": 0.1, "region": "BY", "rounding": 1}
    assert team["sprint"]["first"] == {"id": "2026.20", "start": date(2026, 10, 14)}
    assert team["forecast"]["reference_capacity"] == 40
    assert run(tmp_path, "pruefen").exit_code == 0


def test_einstellungen_changes_and_validates(data_dir: Path):
    # Reihenfolge: Name, Einheit, Produktverteilung, PO, Produktionszugriff, Land, Bundesland,
    # Overhead, Länge, Nummerierung, Referenz, Fenster, Trend, Roadmap, Horizont, Rundung,
    # Produktbasis, Speichern?
    answers = [
        "",
        "SP",
        "",
        "",
        "",
        "",
        "xx",
        "he",
        "",
        "",
        "",
        "",
        "",
        "",
        "-5",
        "50",
        "",
        "flat",
        "75",
        "",
        "",
        "",
        "y",
    ]
    result = run(data_dir, "einstellungen", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Unbekannter Regionscode" in result.output  # Region xx
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
    result = run(data_dir, "einstellungen", "demo", input="\n" * 20)
    assert result.exit_code == 0, result.output
    assert "Keine Änderungen" in result.output
    assert (data_dir / "demo" / "team.yaml").read_text() == before


def test_review_shows_plausibility_warning(data_dir: Path):
    result = run(data_dir, "review", "demo", "2026.21", input="y\n9.5\n30\nn\n")
    assert result.exit_code == 0, result.output
    assert "scope_creep 30" in result.output


def test_commit_refused_on_errors(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    path.write_text(path.read_text().replace("cem: 5", "unbekannt: 5"))
    result = run(data_dir, "planning", "demo", "2026.22", "--commit", input="n\nn\nn\n10\n")
    assert result.exit_code == 1
    assert "Nicht committet" in result.output


def test_planning_prefills_forecast_ist(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    result = run(data_dir, "planning", "demo", "2026.22", input="n\nn\ny\n1.5\n11\n\n\n")
    assert result.exit_code == 0, result.output
    assert "Vorbelegt mit Überkipper + Backlog" in result.output
    sprint = load(path)
    assert sprint["forecast_ist"] == 12.5
    assert sprint["planning"] == {"carryover": 1.5, "backlog": 11, "corrections": []}


def test_planning_without_control_calculation(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    result = run(data_dir, "planning", "demo", "2026.22", input="n\nn\nn\n11\n")
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


def test_teams_subdirectory_is_found(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Start im Wurzelordner eines Daten-Repos mit Unterordner teams/."""
    import shutil

    root = tmp_path / "sprint-daten"
    shutil.copytree(data_dir, root / "teams")
    monkeypatch.delenv("SPRINTFORECAST_DATEN", raising=False)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["--stichtag", "2026-10-15", "forecast", "demo"])
    assert result.exit_code == 0, result.output
    # Liegen Teams direkt im aktuellen Verzeichnis, haben diese Vorrang
    monkeypatch.chdir(root / "teams")
    assert runner.invoke(app, ["--stichtag", "2026-10-15", "forecast", "demo"]).exit_code == 0


def test_analyse(data_dir: Path):
    result = run(data_dir, "analyse", "demo", "--rest", "40")
    assert result.exit_code == 0, result.output
    for text in ("Bandbreite", "konservativ", "Fokusfaktor", "Puffer", "Fertigstellung von 40"):
        assert text in result.output
    report = run(data_dir, "bericht", "demo")
    assert report.exit_code == 0
    text = (data_dir / "demo" / "FORECAST.md").read_text()
    assert text.index("## Prognose") < text.index("## Ergänzend: Bandbreite")


def test_analyse_with_project_share(data_dir: Path):
    full = run(data_dir, "analyse", "demo", "--rest", "40")
    half = run(data_dir, "analyse", "demo", "--rest", "40", "--anteil", "50")
    assert half.exit_code == 0, half.output
    assert "Projektanteil 50 % = 40 % des Forecasts" in half.output
    assert "je Sprint" in half.output and full.output != half.output


def test_planning_flow_next_sprint(data_dir: Path):
    # Standard: nächstes Planning (2026.22). Fehltage: Anna 1, Ben 0, Cem 5, Dana 0;
    # Planning je Produkt: Webshop 4, App 3, Portal 3; ohne Kontrollrechnung; Commitment 10
    answers = ["y", "1", "0", "5", "0", "y", "4", "3", "3", "n", "10"]
    result = run(data_dir, "planning", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Planning 2026.22 – Schritt 3" in result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["absences"] == {"anna": 1, "cem": 5}
    assert sprint["products"]["webshop"] == {"preplanned": 3, "planned": 4}
    assert sprint["forecast_ist"] == 10
    assert sprint["forecast_plan"] is not None


def test_produkte_and_vorplanung(data_dir: Path):
    result = run(data_dir, "produkte", "demo", "2026.23", "--vorplanung", input="2\n2\n2\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert sprint["products"] == {p: {"preplanned": 2} for p in ("webshop", "app", "portal")}
    assert "Saldo" in result.output


def test_produktliste_add_and_end(data_dir: Path):
    answers = ["n", "Neues Produkt", "Cleo", "2026-11-01", "e", "mobile app", "2026-12-31", "q"]
    result = run(data_dir, "produktliste", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    products = load(data_dir / "demo" / "products.yaml")["products"]
    assert products[-1] == {
        "id": "neues-produkt", "name": "Neues Produkt", "po": "Cleo",
        "from": date(2026, 11, 1), "to": None,
    }  # fmt: skip
    assert products[1]["to"] == date(2026, 12, 31)


def test_aktualisieren_outside_uv_tool(data_dir: Path):
    result = run(data_dir, "aktualisieren", "--pruefen")
    assert result.exit_code == 1
    assert "nicht mit `uv tool install` installiert" in result.output


def test_sprints_calendar_and_longer_sprint(data_dir: Path):
    result = run(data_dir, "sprints", "demo")
    assert result.exit_code == 0, result.output
    assert "Di 27.10.2026" in result.output  # letzter Tag von 2026.21
    # 2026.25 drei Wochen bis Di 12.01.2027 → 2026.26 entfällt, danach 2027.1
    result = run(data_dir, "sprints", "demo", "--ende", "2026.25=2027-01-12", "--anlegen")
    assert result.exit_code == 0, result.output
    s25 = load(data_dir / "demo" / "sprints" / "2026.25.yaml")
    assert s25["end"] == date(2027, 1, 13)
    nxt = load(data_dir / "demo" / "sprints" / "2027.1.yaml")
    assert nxt["start"] == date(2027, 1, 13)
    assert run(data_dir, "pruefen").exit_code == 0


def test_forecast_rechenweg(data_dir: Path):
    result = run(data_dir, "forecast", "demo", "--rechenweg", "2026.22")
    assert result.exit_code == 0, result.output
    assert "Rechenweg Sprint 2026.22" in result.output
    assert "11,229" in result.output  # 16,84 / 45 × 30,0


def test_datenordner(tmp_path: Path, data_dir: Path):
    import subprocess

    assert run(data_dir, "datenordner", str(tmp_path)).exit_code == 1  # kein Git
    subprocess.run(["git", "init", "-q", str(data_dir)], check=True)
    result = run(data_dir, "datenordner", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Datenordner gemerkt" in result.output
    assert "Gemerkt:" in run(data_dir, "datenordner").output


def test_forecast_warns_for_noise_extrapolating_trend_mode(data_dir: Path):
    plain = run(data_dir, "forecast", "demo")
    assert "schreibt Schwankungen fort" not in plain.output  # Standard flat: keine Warnung
    team = data_dir / "demo" / "team.yaml"
    team.write_text(team.read_text().replace("trend_mode: flat", "trend_mode: classic"))
    result = run(data_dir, "forecast", "demo")
    assert "Trend-Modus classic" in result.output and "schreibt Schwankungen fort" in result.output
    report = run(data_dir, "bericht", "demo", "-o", "-")
    assert "Trend-Modus classic" in report.output
