# SPDX-License-Identifier: EUPL-1.2
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from gitrepos import git
from typer.testing import CliRunner

from sprintforecast import cli
from sprintforecast.cli import app
from sprintforecast.guide import COMMAND_ALIASES, COMMANDS
from sprintforecast.storage import Repository

runner = CliRunner(env={"COLUMNS": "200"})


def run(data_dir: Path, *args: str, input: str | None = None):
    result = runner.invoke(
        app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args], input=input
    )
    return result


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_forecast_and_report(data_dir: Path):
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert "2026.24" in result.output and "Trend" in result.output

    result = run(data_dir, "bericht", "demo")
    assert result.exit_code == 0, result.output
    report = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    assert "# Sprint-Forecast Demo-Team" in report
    assert "| 2026.21 |" in report and "**laufend**" in report
    assert "```mermaid" in report


def test_forecast_table_has_a_range_column(data_dir: Path):
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert "Spanne" in result.output
    rows = {
        line.split("│")[1].strip(): line
        for line in result.output.splitlines()
        if line.startswith("│ 2026.")
    }
    # 2026.21 läuft, 2026.22 bis .24 sind geplant; abgeschlossene Sprints haben keine Spanne
    for sprint, expected in {
        "2026.21": "8,5–10,5",
        "2026.22": "10,0–12,3",
        "2026.23": "10,2–12,5",
        "2026.24": "10,2–12,5",
    }.items():
        assert expected in rows[sprint], rows[sprint]
    assert not re.search(r"\d,\d+–\d", rows["2026.20"]), rows["2026.20"]

    report = run(data_dir, "bericht", "demo", "-o", "-").output
    assert "**Forecast PLAN** (PT) | Spanne |" in report
    forecast_rows = {}
    for line in report.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| 2026.") and len(cells) == 9:  # Prognosetabelle
            forecast_rows[cells[0]] = cells
    assert forecast_rows["2026.22"][5:7] == ["**11,2**", "10,0–12,3"]
    assert forecast_rows["2026.21"][5:7] == ["**9,5**", "8,5–10,5"]


@pytest.mark.parametrize(
    "args",
    [
        ["--rest", "nan"],
        ["--rest", "inf"],
        ["--rest", "1e999"],
        ["--rest", "10", "--anteil", "nan"],
    ],
)
def test_analyse_rejects_non_finite_options(data_dir: Path, args: list[str]):
    result = run(data_dir, "analyse", "demo", *args)
    assert result.exit_code == 2, result.output
    assert "endliche Zahl" in result.output


def test_kapazitaet_without_sprint_file_names_calendar_and_people_with_people_list(
    data_dir: Path,
):
    result = run(data_dir, "kapazitaet", "demo", "2026.25")
    assert result.exit_code == 0, result.output
    assert "Noch keine Sprintdatei" in result.output
    assert "Kalender und Personenliste" in result.output
    text = " ".join(result.output.split())  # Umbrüche der Konsole
    assert "Fehltage werden nach der Historie geschätzt (ohne Historie ohne Abzug)" in text
    assert "Trend" not in result.output


def test_kapazitaet_without_sprint_file_names_trend_without_people_list(data_dir: Path):
    (data_dir / "demo" / "people.yaml").unlink()
    result = run(data_dir, "kapazitaet", "demo", "2026.25")
    assert result.exit_code == 0, result.output
    assert "Noch keine Sprintdatei" in result.output
    assert "Kapazitäts-Trend" in result.output


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


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999"])
def test_fehltage_rejects_non_finite_number(data_dir: Path, raw: str):
    result = run(data_dir, "fehltage", "demo", "2026.23", input=f"{raw}\n1\n0\n0\n0\n")
    assert result.exit_code == 0, result.output
    assert "Bitte eine endliche Zahl eingeben" in result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert sprint["absences"] == {"anna": 1}


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


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999", "0.5 nan"])
def test_planning_rejects_non_finite_corrections(data_dir: Path, raw: str):
    result = run(data_dir, "planning", "demo", "2026.21", input=f"n\nn\ny\n1\n8\n{raw}\n0.5\n9\n")
    assert result.exit_code == 0, result.output
    assert "Bitte eine endliche Zahl eingeben" in result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["planning"] == {"carryover": 1, "backlog": 8, "corrections": [0.5]}


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
    path.write_text(
        path.read_text(encoding="utf-8").replace("cem: 5", "unbekannt: 5"), encoding="utf-8"
    )
    result = run(data_dir, "pruefen")
    assert result.exit_code == 1
    assert "unbekannte Person" in result.output


def test_init_new_team(tmp_path: Path):
    answers = [
        "Team A", "PT", "", "", "", "",
        "by", "", "10", "", "", "14", "yearly", "2026-10-14", "2026.20",
        "40", "", "", "", "", "", "",
    ]  # fmt: skip
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["capacity"] == {"overhead_share": 0.1, "region": "BY", "rounding": 1}
    assert team["sprint"]["first"] == {"id": "2026.20", "start": date(2026, 10, 14)}
    assert team["forecast"]["reference_capacity"] == 40
    assert run(tmp_path, "pruefen").exit_code == 0


@pytest.mark.parametrize("key", ["../x", "a/b", "..", " x", "Team-A", "con", "nul", "a" * 65])
def test_init_rejects_invalid_key(tmp_path: Path, key: str):
    data_dir = tmp_path / "teams"
    data_dir.mkdir()
    result = run(data_dir, "init", key)
    assert result.exit_code == 1
    assert "Kürzel" in result.output
    assert "Neues Team" not in result.output  # es wird gar nicht erst gefragt
    assert list(tmp_path.rglob("*")) == [data_dir]  # weder darin noch daneben etwas angelegt


@pytest.mark.parametrize(
    ("key", "expected"), [("Alt.Team_X", "existiert bereits."), ("alt.team_x", "(als 'Alt.Team_X'")]
)
def test_init_names_an_existing_team_before_complaining_about_the_key(
    data_dir: Path, key: str, expected: str
):
    """Ein Altteam mit Großbuchstaben oder Punkt: „existiert bereits“ statt der Kürzelregel,
    auch wenn nur die Schreibweise abweicht (auf Windows und macOS derselbe Ordner)."""
    shutil.copytree(data_dir / "demo", data_dir / "Alt.Team_X")
    result = run(data_dir, "init", key)
    assert result.exit_code == 1
    assert "existiert bereits" in result.output and expected in result.output
    assert "Kürzel" not in result.output
    assert sorted(p.name for p in data_dir.iterdir()) == ["Alt.Team_X", "demo"]


def test_existing_team_with_unusual_name_still_works_in_cli(data_dir: Path):
    shutil.copytree(data_dir / "demo", data_dir / "Alt.Team_X")
    result = run(data_dir, "forecast", "Alt.Team_X")
    assert result.exit_code == 0, result.output
    assert "Trend" in result.output


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
    before = (data_dir / "demo" / "team.yaml").read_text(encoding="utf-8")
    result = run(data_dir, "einstellungen", "demo", input="\n" * 20)
    assert result.exit_code == 0, result.output
    assert "Keine Änderungen" in result.output
    assert (data_dir / "demo" / "team.yaml").read_text(encoding="utf-8") == before


def test_review_shows_plausibility_warning(data_dir: Path):
    result = run(data_dir, "review", "demo", "2026.21", input="y\n9.5\n30\nn\n")
    assert result.exit_code == 0, result.output
    assert "scope_creep 30" in result.output


def test_commit_refused_on_errors(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.22.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("cem: 5", "unbekannt: 5"), encoding="utf-8"
    )
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


@pytest.mark.parametrize("option", ["--stichtag", "--as-of"])
def test_invalid_stichtag_is_a_usage_error(data_dir: Path, option: str):
    args = ["--daten", str(data_dir), option, "2026-13-45", "forecast", "demo"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    assert "Datum im Format JJJJ-MM-TT erwartet" in result.output
    assert isinstance(result.exception, SystemExit)  # Nutzungsfehler, kein ungefangener ValueError


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
    text = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    assert text.index("## Prognose") < text.index("## Ergänzend: Bandbreite")


def test_analyse_with_project_share(data_dir: Path):
    full = run(data_dir, "analyse", "demo", "--rest", "40")
    half = run(data_dir, "analyse", "demo", "--rest", "40", "--anteil", "50")
    assert half.exit_code == 0, half.output
    assert "Projektanteil 50 % = 40 % des Forecasts" in half.output
    assert "je Sprint" in half.output and full.output != half.output


def keep_first_sprints(data_dir: Path, count: int) -> None:
    """Nur die ersten ``count`` Sprints des Demo-Teams behalten (wenige Werte für die Analyse)."""
    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > count:
            path.unlink()


@pytest.mark.parametrize(("count", "warned"), [(2, True), (4, True), (5, False)])
def test_analyse_rest_warns_about_few_samples(data_dir: Path, count: int, warned: bool):
    """Die Simulation rechnet schon ab 2 Werten; unter 5 Sprints kommt dieselbe Warnung wie in
    der Weboberfläche."""
    keep_first_sprints(data_dir, count)
    result = run(data_dir, "analyse", "demo", "--rest", "40")
    assert result.exit_code == 0, result.output
    assert f"Stichprobe {count} Sprints" in result.output
    note = f"Wenig Daten: Die Simulation zieht aus nur {count} Sprints (ab 5 sind Aussagen"
    assert (note in result.output) is warned


def test_analyse_rest_without_few_samples_has_no_warning(data_dir: Path):
    result = run(data_dir, "analyse", "demo", "--rest", "40")
    assert result.exit_code == 0, result.output
    assert "Wenig Daten" not in result.output


def test_analyse_without_rest_has_no_simulation_warning(data_dir: Path):
    keep_first_sprints(data_dir, 3)
    result = run(data_dir, "analyse", "demo")
    assert result.exit_code == 0, result.output
    assert "Wenig Daten" not in result.output


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


def drop_done(data_dir: Path, product: str, *sprint_ids: str) -> None:
    """Entfernt „Erledigt“ des Produkts in den Sprints (nicht erfasst, nicht 0)."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    for sprint_id in sprint_ids:
        sprint = data.sprint(sprint_id)
        sprint.products[product].done = None
        repo.save_sprint("demo", sprint)


def balance_table(output: str) -> str:
    return output.split("Saldo: Σ Erledigt − Σ Standard")[1]


def test_produkte_balance_hides_products_without_value_and_shows_missing(data_dir: Path):
    plain = run(data_dir, "produkte", "demo", "2026.20", "--verlauf", "6")
    assert "ohne Wert" not in balance_table(plain.output)  # alles erfasst: keine Spalte

    drop_done(data_dir, "app", "2026.20")
    # Fenster nur mit dem Sprint ohne Wert: keine Zeile „0 | 0,00 | 0,00 | 0,00“
    only = run(data_dir, "produkte", "demo", "2026.20", "--verlauf", "1")
    assert only.exit_code == 0, only.output
    table = balance_table(only.output)
    assert "Webshop" in table and "Mobile App" not in table
    # Das ausgeblendete Produkt hat einen fehlenden Wert, die angezeigten haben keinen: keine Spalte
    assert "ohne Wert" not in table

    # sonst bleibt das Produkt mit seinen übrigen Sprints, die fehlenden stehen daneben
    result = run(data_dir, "produkte", "demo", "2026.20", "--verlauf", "6")
    assert result.exit_code == 0, result.output
    table = balance_table(result.output)
    assert "ohne Wert" in table
    app_row = next(line for line in table.splitlines() if "Mobile App" in line)
    cells = [c.strip() for c in app_row.strip("│").split("│")]
    assert cells[1] == "3" and cells[-1] == "1"
    webshop_row = next(line for line in table.splitlines() if "Webshop" in line)
    assert webshop_row.strip("│").split("│")[-1].strip() == "0"


def test_report_balance_hides_products_without_value_and_shows_missing(data_dir: Path):
    def balance_section() -> str:
        assert run(data_dir, "bericht", "demo").exit_code == 0
        report = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
        return report.split("**Saldo**")[1].split("\n## ")[0]

    assert "ohne Wert" not in balance_section()

    drop_done(data_dir, "app", "2026.20")
    section = balance_section()
    rows = {line.split("|")[1].strip(): line for line in section.splitlines() if "|" in line}
    assert "ohne Wert" in rows["Produkt"]
    cells = [c.strip() for c in rows["Mobile App"].strip("|").split("|")]
    assert cells[1] == "3" and cells[-1] == "1"
    assert rows["Webshop"].strip("|").split("|")[-1].strip() == "0"

    # Ein einziger Sprint mit Wert genügt, die Zeile bleibt
    drop_done(data_dir, "app", "2026.17", "2026.18")
    assert "Mobile App" in balance_section()

    # In keinem Sprint des Fensters ein Wert: das Produkt entfällt statt als Nullzeile zu stehen,
    # und das ausgeblendete Produkt schaltet die Spalte nicht ein (wie in der Weboberfläche)
    drop_done(data_dir, "app", "2026.19")
    section = balance_section()
    assert "Mobile App" not in section and "ohne Wert" not in section


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
    assert "16,8433 / 45 × 30 = 11,229" in result.output


def test_datenordner(tmp_path: Path, data_dir: Path):
    import subprocess

    assert run(data_dir, "datenordner", str(tmp_path)).exit_code == 1  # kein Git
    subprocess.run(["git", "init", "-q", str(data_dir)], check=True)
    result = run(data_dir, "datenordner", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Datenordner gemerkt" in result.output
    assert "Gemerkt:" in run(data_dir, "datenordner").output


def one_line(output: str) -> str:
    """Ausgabe ohne Zeilenumbrüche der Konsole (Rich bricht lange Zeilen um)."""
    return " ".join(output.split())


@pytest.fixture
def without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git ist auf diesem Rechner nicht installiert (nicht im PATH)."""
    leer = tmp_path / "ohne-git"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))


@pytest.fixture
def data_repo(data_dir: Path, tmp_path: Path) -> Path:
    """Das Datenverzeichnis liegt in einem Git-Repository (Wurzel ist ``tmp_path``)."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "T")
    git(tmp_path, "config", "user.email", "t@example.org")
    return tmp_path


def commit_planning(data_dir: Path):
    return run(data_dir, "planning", "demo", "2026.22", "--commit", input="n\nn\nn\n10\n")


def test_commit_without_repository_says_so_instead_of_showing_git_output(data_dir: Path):
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Kein Git-Repository" in text
    assert "liegt in keinem Git-Repository" in text
    assert "`git init`" in text and "`git clone`" in text
    assert "fatal" not in text
    assert "Gespeichert:" in result.output  # die Daten sind geschrieben, nur nicht committet


def test_commit_without_git_installed_says_so(data_dir: Path, without_git: None):
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Git ist nicht installiert" in text
    assert "git ist nicht installiert oder nicht im PATH" in text
    assert "Git installieren" in text
    assert "Git:" not in text


def test_commit_without_git_identity_names_the_command_line_way(
    data_dir: Path, data_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    git(data_repo, "config", "--unset", "user.name")
    git(data_repo, "config", "--unset", "user.email")
    git(data_repo, "config", "user.useConfigOnly", "true")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "EMAIL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    # Keine Benutzereinstellungen des Rechners (unter Windows: USERPROFILE statt HOME): Git
    # fände dort sonst einen Namen.
    leer = tmp_path.parent / f"{tmp_path.name}-leer.gitconfig"
    leer.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(leer))
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "leer"))
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Name und E-Mail-Adresse fehlen" in text
    assert "git config --global user.name" in text and "git config --global user.email" in text
    assert "Dein Name" in text  # der Hinweis der Kommandozeile, nicht nur Gits eigene Meldung
    assert "Seitenleiste" not in text


def test_commit_with_an_existing_tag_does_not_offer_the_choice_of_a_name(
    data_dir: Path, data_repo: Path
):
    review = ("review", "demo", "2026.21", "--commit")
    first = run(data_dir, *review, input="y\n9,5\n0.1\nn\n")
    assert first.exit_code == 0, first.output
    assert git(data_repo, "tag") == "demo/2026.21"
    result = run(data_dir, *review, input="y\n9,5\n0.2\nn\n")
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Tag-Name ist schon vergeben" in text
    assert "Der Tag demo/2026.21 gibt es auf diesem Rechner schon" in text
    assert "git tag -d" in text and "--commit" in text
    assert "anderen Namen" not in text


def test_commit_of_a_file_with_conflict_markers_does_not_point_to_a_page(
    data_dir: Path, data_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    real = cli.commit

    def with_markers(paths: list[Path], message: str, tag: str | None = None) -> str:
        paths[0].write_text("<<<<<<< a\nx: 1\n=======\nx: 2\n>>>>>>> b\n", encoding="utf-8")
        return real(paths, message, tag)

    monkeypatch.setattr(cli, "commit", with_markers)
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Konflikt beim Zusammenführen" in text
    assert "2026.22.yaml" in text
    assert "im Editor entfernen" in text
    assert "„Konflikte lösen“" not in text


def test_git_problem_escapes_square_brackets_of_the_git_message(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast.git import GitError

    def refused(*_: object) -> str:
        raise GitError(
            " ! [rejected]        main -> main (fetch first)", "rejected", "Zuerst [holen]."
        )

    monkeypatch.setattr(cli, "commit", refused)
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "! [rejected] main -> main (fetch first)" in text
    assert "Zuerst [holen]." in text


def test_datenordner_without_git_installed_says_so(
    tmp_path: Path, data_dir: Path, without_git: None
):
    result = run(data_dir, "datenordner", str(data_dir))
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Git ist nicht installiert" in text
    assert "Git installieren" in text
    assert "liegt in keinem Git-Repository" not in text
    assert "Kein Datenordner gemerkt." in run(data_dir, "datenordner").output


def test_datenordner_names_a_folder_without_repository(tmp_path: Path, data_dir: Path):
    result = run(data_dir, "datenordner", str(tmp_path))
    assert result.exit_code == 1
    assert "liegt in keinem Git-Repository (git init bzw. git clone)" in one_line(result.output)
    assert "Git ist nicht installiert" not in result.output


@pytest.mark.parametrize("parts", [("x[a]",), ("x[", "y]", "b")])
def test_datenordner_messages_keep_brackets_in_the_path(
    tmp_path: Path, data_dir: Path, parts: tuple[str, ...]
):
    """Rich liest eckige Klammern als Auszeichnung: Der Pfad wird maskiert und steht vollständig
    in der Meldung (ein „[/y]“ ohne Gegenstück brach vorher den Befehl ab)."""
    folder = tmp_path.joinpath(*parts)
    folder.mkdir(parents=True)
    shown = "/".join(parts)  # Rich bricht lange Pfade um: nur die Namen prüfen
    result = run(data_dir, "datenordner", str(folder))
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert shown in one_line(result.output).replace("\\", "/")
    missing = run(data_dir, "datenordner", str(folder / "fehlt"))
    assert missing.exit_code == 1
    assert shown in one_line(missing.output).replace("\\", "/")


def test_forecast_warns_for_noise_extrapolating_trend_mode(data_dir: Path):
    plain = run(data_dir, "forecast", "demo")
    assert "schreibt Schwankungen fort" not in plain.output  # Standard flat: keine Warnung
    team = data_dir / "demo" / "team.yaml"
    team.write_text(
        team.read_text(encoding="utf-8").replace("trend_mode: flat", "trend_mode: classic"),
        encoding="utf-8",
    )
    result = run(data_dir, "forecast", "demo")
    assert "Trend-Modus classic" in result.output and "schreibt Schwankungen fort" in result.output
    report = run(data_dir, "bericht", "demo", "-o", "-")
    assert "Trend-Modus classic" in report.output


def test_cli_reports_unwritable_settings_without_traceback(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast import cli
    from sprintforecast.config import SettingsError

    def broken(*_: object) -> None:
        raise SettingsError(
            "Die Einstellungen konnten nicht gespeichert werden: Zugriff verweigert"
        )

    from sprintforecast import storage

    monkeypatch.setattr(storage, "save_data_dir", broken)
    monkeypatch.setattr(cli, "save_language", broken)
    for args in (["datenordner", str(repo)], ["sprache", "en"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert "Zugriff verweigert" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_help_command_list_covers_every_cli_command():
    """Jeder Befehl der CLI steht in guide.COMMANDS, und dort steht kein unbekannter Befehl."""
    english = set(COMMAND_ALIASES.values())
    registered = {
        info.name
        for info in app.registered_commands
        if info.name not in english and info.callback.__module__ == "sprintforecast.cli"
    }
    listed = {m[1] for left, _ in COMMANDS if (m := re.match(r"sprintforecast (\w+)", left))}
    assert not registered - listed, f"Fehlt in guide.COMMANDS: {registered - listed}"
    assert not listed - registered, f"Kein CLI-Befehl: {listed - registered}"
