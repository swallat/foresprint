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
from sprintforecast.guide import COMMANDS
from sprintforecast.storage import Repository

runner = CliRunner(env={"COLUMNS": "200"})


def run(data_dir: Path, *args: str, input: str | None = None):
    result = runner.invoke(
        app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )
    return result


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_forecast_and_report(data_dir: Path):
    result = run(data_dir, "forecast", "demo")
    assert result.exit_code == 0, result.output
    assert "2026.24" in result.output and "Trend" in result.output

    result = run(data_dir, "report", "demo")
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
    # 2026.21 is running, 2026.22 to .24 are planned; completed sprints have no range
    for sprint, expected in {
        "2026.21": "8,5–10,5",
        "2026.22": "10,0–12,3",
        "2026.23": "10,2–12,5",
        "2026.24": "10,2–12,5",
    }.items():
        assert expected in rows[sprint], rows[sprint]
    assert not re.search(r"\d,\d+–\d", rows["2026.20"]), rows["2026.20"]

    report = run(data_dir, "report", "demo", "-o", "-").output
    assert "**Forecast PLAN** (PT) | Spanne |" in report
    forecast_rows = {}
    for line in report.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| 2026.") and len(cells) == 9:  # forecast table
            forecast_rows[cells[0]] = cells
    assert forecast_rows["2026.22"][5:7] == ["**11,2**", "10,0–12,3"]
    assert forecast_rows["2026.21"][5:7] == ["**9,5**", "8,5–10,5"]


@pytest.mark.parametrize(
    "args",
    [
        ["--remaining", "nan"],
        ["--remaining", "inf"],
        ["--remaining", "1e999"],
        ["--remaining", "10", "--share", "nan"],
    ],
)
def test_analyse_rejects_non_finite_options(data_dir: Path, args: list[str]):
    result = run(data_dir, "analysis", "demo", *args)
    assert result.exit_code == 2, result.output
    assert "endliche Zahl" in result.output


def test_capacity_without_sprint_file_names_calendar_and_people_with_people_list(
    data_dir: Path,
):
    result = run(data_dir, "capacity", "demo", "2026.25")
    assert result.exit_code == 0, result.output
    assert "Noch keine Sprintdatei" in result.output
    assert "Kalender und Personenliste" in result.output
    text = " ".join(result.output.split())  # console line breaks
    assert "Fehltage werden nach der Historie geschätzt (ohne Historie ohne Abzug)" in text
    assert "Trend" not in result.output


def test_capacity_without_sprint_file_names_trend_without_people_list(data_dir: Path):
    (data_dir / "demo" / "people.yaml").unlink()
    result = run(data_dir, "capacity", "demo", "2026.25")
    assert result.exit_code == 0, result.output
    assert "Noch keine Sprintdatei" in result.output
    assert "Kapazitäts-Trend" in result.output


def test_absences_for_future_sprint_creates_file(data_dir: Path):
    # Sprint 2026.23 has no file yet; active people: Anna, Ben, Cem, Dana
    result = run(data_dir, "absences", "demo", "2026.23", input="2\n0\n1,5\n0\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert sprint["absences"] == {"anna": 2, "cem": 1.5}
    assert sprint["start"].isoformat() == "2026-11-11"
    assert "Prognose Sprint 2026.23" in result.output
    # Capacity: Anna 8 + Ben 5 + Cem 8.5 + Dana 10
    assert "31,5" in result.output


def test_absences_rejects_invalid_number(data_dir: Path):
    result = run(data_dir, "absences", "demo", "2026.23", input="abc\n1\n0\n0\n0\n")
    assert result.exit_code == 0, result.output
    assert "Bitte eine Zahl eingeben" in result.output


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999"])
def test_absences_rejects_non_finite_number(data_dir: Path, raw: str):
    result = run(data_dir, "absences", "demo", "2026.23", input=f"{raw}\n1\n0\n0\n0\n")
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
    # Check absences? n · Planning per product? n · Cross-check? y …
    result = run(data_dir, "planning", "demo", "2026.21", input="n\nn\ny\n1\n8\n0.5\n9\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["forecast_ist"] == 9
    assert sprint["planning"] == {"carryover": 1, "backlog": 8, "corrections": [0.5]}
    assert "Delta 1,00" in result.output  # Forecast PLAN 9.5 − Planning 8.5


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999", "0.5 nan"])
def test_planning_rejects_non_finite_corrections(data_dir: Path, raw: str):
    result = run(data_dir, "planning", "demo", "2026.21", input=f"n\nn\ny\n1\n8\n{raw}\n0.5\n9\n")
    assert result.exit_code == 0, result.output
    assert "Bitte eine endliche Zahl eingeben" in result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.21.yaml")
    assert sprint["planning"] == {"carryover": 1, "backlog": 8, "corrections": [0.5]}


def test_people_change_fte(data_dir: Path):
    result = run(data_dir, "people", "demo", input="f\nanna\n2026-11-01\n0.8\nq\n")
    assert result.exit_code == 0, result.output
    assert "n = neue Person, f = FTE ändern, a = Austritt, q = fertig" in result.output
    anna = load(data_dir / "demo" / "people.yaml")["people"][0]
    assert anna["memberships"][-2]["to"].isoformat() == "2026-10-31"
    assert anna["memberships"][-1] == {
        "from": anna["memberships"][-1]["from"],
        "to": None,
        "fte": 0.8,
    }


def test_check_fails_on_error(data_dir: Path):
    assert run(data_dir, "check").exit_code == 0
    path = data_dir / "demo" / "sprints" / "2026.21.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("cem: 5", "unbekannt: 5"), encoding="utf-8"
    )
    result = run(data_dir, "check")
    assert result.exit_code == 1
    assert "unbekannte Person" in result.output


def test_init_new_team(tmp_path: Path):
    # Order: name, then the first sprint (numbering, start, ID), then everything else.
    answers = [
        "Team A", "yearly", "2026-10-14", "2026.20",
        "PT", "", "", "", "", "", "by", "", "10", "", "", "14",
        "40", "", "", "", "", "", "",
    ]  # fmt: skip
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert result.output.index("Erster Sprint") < result.output.index("Schätzeinheit")
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["capacity"] == {"overhead_share": 0.1, "region": "BY", "rounding": 1}
    assert team["sprint"]["first"] == {"id": "2026.20", "start": date(2026, 10, 14)}
    assert team["forecast"]["reference_capacity"] == 40
    assert run(tmp_path, "check").exit_code == 0


def test_init_has_no_default_for_the_first_sprint_id(tmp_path: Path):
    """Enter does not accept an ID: the team knows its running sprint, the program does not."""
    answers = ["Team A", "", "2026-10-14", "", "", "2026.15"] + [""] * 19
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("Bitte einen Wert eingeben.") == 2
    assert "2026.1" not in result.output.split("ID des ersten Sprints")[1].split("\n")[0]
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["sprint"]["first"] == {"id": "2026.15", "start": date(2026, 10, 14)}


def test_init_asks_again_for_an_id_that_does_not_fit_the_numbering(tmp_path: Path):
    answers = ["Team A", "sequential", "2026-10-14", "abc", "15"] + [""] * 19
    result = run(tmp_path, "init", "team-a", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "'abc' passt nicht zur Nummerierung (erwartet eine Zahl" in result.output
    team = load(tmp_path / "team-a" / "team.yaml")
    assert team["sprint"] == {"first": {"id": "15", "start": date(2026, 10, 14)},
                              "length_days": 14, "numbering": "sequential"}  # fmt: skip


@pytest.mark.parametrize("key", ["../x", "a/b", "..", " x", "Team-A", "con", "nul", "a" * 65])
def test_init_rejects_invalid_key(tmp_path: Path, key: str):
    data_dir = tmp_path / "teams"
    data_dir.mkdir()
    result = run(data_dir, "init", key)
    assert result.exit_code == 1
    assert "Kürzel" in result.output
    assert "Neues Team" not in result.output  # it is not even asked
    assert list(tmp_path.rglob("*")) == [data_dir]  # nothing created inside or next to it


@pytest.mark.parametrize(
    ("key", "expected"), [("Alt.Team_X", "existiert bereits."), ("alt.team_x", "(als 'Alt.Team_X'")]
)
def test_init_names_an_existing_team_before_complaining_about_the_key(
    data_dir: Path, key: str, expected: str
):
    """A legacy team with uppercase letters or a dot: "already exists" instead of the key rule,
    even if only the spelling differs (the same folder on Windows and macOS)."""
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


def test_settings_changes_and_validates(data_dir: Path):
    # Order: name, unit, product distribution, PO, production access, ticket pre-planning,
    # country, state, overhead, length, numbering, reference, window, trend, roadmap,
    # horizon, rounding, product basis, save?
    answers = [
        "",
        "SP",
        "",
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
    result = run(data_dir, "settings", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Unbekannter Regionscode" in result.output  # region xx
    assert "muss ≥ 1" in result.output  # reference -5
    assert "rückwirkend" in result.output
    team = load(data_dir / "demo" / "team.yaml")
    assert team["unit"] == "SP"
    assert team["capacity"]["region"] == "HE"
    assert team["forecast"]["reference_capacity"] == 50
    assert team["forecast"]["trend_mode"] == "flat"
    assert team["forecast"]["roadmap_share"] == 0.75
    assert "first" in team["sprint"]  # adopted unchanged


def test_settings_without_changes(data_dir: Path):
    before = (data_dir / "demo" / "team.yaml").read_text(encoding="utf-8")
    result = run(data_dir, "settings", "demo", input="\n" * 21)
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


def test_planning_prefills_commitment(data_dir: Path):
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


def test_people_new_person_gets_id_and_former_hidden(data_dir: Path):
    result = run(data_dir, "people", "demo", input="n\nJörg Müller\n\n2026-11-01\n1\nq\n")
    assert result.exit_code == 0, result.output
    assert "Emil" not in result.output  # left → hidden
    assert "ehemalige Person(en) ausgeblendet" in result.output
    people = load(data_dir / "demo" / "people.yaml")["people"]
    assert people[-1]["id"] == "joerg-mueller"
    assert people[-1]["name"] == "Jörg Müller"
    shown = run(data_dir, "people", "demo", "--former", input="q\n")
    assert "Emil" in shown.output


def test_default_data_dir_is_current_directory(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SPRINTFORECAST_DATA", raising=False)
    monkeypatch.chdir(data_dir)
    result = runner.invoke(app, ["--as-of", "2026-10-15", "forecast", "demo"])
    assert result.exit_code == 0, result.output
    assert "Demo-Team" in result.output


@pytest.mark.parametrize("option", ["--as-of", "--as-of"])
def test_invalid_as_of_is_a_usage_error(data_dir: Path, option: str):
    args = ["--data", str(data_dir), option, "2026-13-45", "forecast", "demo"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    assert "Datum im Format JJJJ-MM-TT erwartet" in result.output
    assert isinstance(result.exception, SystemExit)  # usage error, not an uncaught ValueError


def test_version_and_help_without_command():
    from sprintforecast import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output
    result = runner.invoke(app, [])
    assert result.exit_code == 0 and "forecast" in result.output


def test_teams_subdirectory_is_found(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Start in the root folder of a data repo with a teams/ subfolder."""
    import shutil

    root = tmp_path / "sprint-daten"
    shutil.copytree(data_dir, root / "teams")
    monkeypatch.delenv("SPRINTFORECAST_DATA", raising=False)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["--as-of", "2026-10-15", "forecast", "demo"])
    assert result.exit_code == 0, result.output
    # If teams lie directly in the current directory, they take precedence
    monkeypatch.chdir(root / "teams")
    assert runner.invoke(app, ["--as-of", "2026-10-15", "forecast", "demo"]).exit_code == 0


def test_analyse(data_dir: Path):
    result = run(data_dir, "analysis", "demo", "--remaining", "40")
    assert result.exit_code == 0, result.output
    for text in ("Bandbreite", "konservativ", "Fokusfaktor", "Puffer", "Fertigstellung von 40"):
        assert text in result.output
    report = run(data_dir, "report", "demo")
    assert report.exit_code == 0
    text = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    assert text.index("## Prognose") < text.index("## Ergänzend: Bandbreite")


def test_analyse_with_project_share(data_dir: Path):
    full = run(data_dir, "analysis", "demo", "--remaining", "40")
    half = run(data_dir, "analysis", "demo", "--remaining", "40", "--share", "50")
    assert half.exit_code == 0, half.output
    assert "Projektanteil 50 % = 40 % des Forecasts" in half.output
    assert "je Sprint" in half.output and full.output != half.output


def keep_first_sprints(data_dir: Path, count: int) -> None:
    """Keep only the first ``count`` sprints of the demo team (few values for the analysis)."""
    for path in (data_dir / "demo" / "sprints").glob("*.yaml"):
        if int(path.stem.rsplit(".", 1)[1]) > count:
            path.unlink()


@pytest.mark.parametrize(("count", "warned"), [(2, True), (4, True), (5, False)])
def test_analyse_rest_warns_about_few_samples(data_dir: Path, count: int, warned: bool):
    """The simulation already calculates from 2 values; below 5 sprints the same warning appears as
    in the web UI."""
    keep_first_sprints(data_dir, count)
    result = run(data_dir, "analysis", "demo", "--remaining", "40")
    assert result.exit_code == 0, result.output
    assert f"Stichprobe {count} Sprints" in result.output
    note = f"Wenig Daten: Die Simulation zieht aus nur {count} Sprints (ab 5 sind Aussagen"
    assert (note in result.output) is warned


def test_analyse_rest_with_a_small_window_caps_the_sample_and_explains_it(data_dir: Path):
    """The sample is capped at the window; the threshold stays 5, the notice names the
    window."""
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = 3
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    result = run(data_dir, "analysis", "demo", "--remaining", "40")
    assert result.exit_code == 0, result.output
    assert "Stichprobe 3 Sprints" in result.output
    text = " ".join(result.output.split())
    assert "Wenig Daten: Die Simulation zieht aus nur 3 Sprints (ab 5 sind Aussagen" in text
    assert "Das Prognosefenster ist auf 3 Sprints gestellt" in text
    assert "mehr Werte in Spanne und Simulation ein" in text


def test_analyse_rest_with_a_small_window_but_no_more_values_has_no_window_hint(data_dir: Path):
    """Window 3, only 2 values: the window caps nothing, so no window notice."""
    keep_first_sprints(data_dir, 2)
    team_file = data_dir / "demo" / "team.yaml"
    raw = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    raw.setdefault("forecast", {})["window"] = 3
    team_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    result = run(data_dir, "analysis", "demo", "--remaining", "40")
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "Wenig Daten: Die Simulation zieht aus nur 2 Sprints (ab 5 sind Aussagen" in text
    assert "Prognosefenster" not in text


def test_analyse_rest_without_few_samples_has_no_warning(data_dir: Path):
    result = run(data_dir, "analysis", "demo", "--remaining", "40")
    assert result.exit_code == 0, result.output
    assert "Wenig Daten" not in result.output


def test_analyse_without_rest_has_no_simulation_warning(data_dir: Path):
    keep_first_sprints(data_dir, 3)
    result = run(data_dir, "analysis", "demo")
    assert result.exit_code == 0, result.output
    assert "Wenig Daten" not in result.output


def test_planning_flow_next_sprint(data_dir: Path):
    # Default: next planning (2026.22). Absences: Anna 1, Ben 0, Cem 5, Dana 0;
    # planning per product: Webshop 4, App 3, Portal 3; no cross-check; commitment 10
    answers = ["y", "1", "0", "5", "0", "y", "4", "3", "3", "n", "10"]
    result = run(data_dir, "planning", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Planning 2026.22 – Schritt 3" in result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.22.yaml")
    assert sprint["absences"] == {"anna": 1, "cem": 5}
    assert sprint["products"]["webshop"] == {"preplanned": 3, "planned": 4}
    assert sprint["forecast_ist"] == 10
    assert sprint["forecast_plan"] is not None


def test_products_and_preplanning(data_dir: Path):
    result = run(data_dir, "products", "demo", "2026.23", "--preplanning", input="2\n2\n2\n")
    assert result.exit_code == 0, result.output
    sprint = load(data_dir / "demo" / "sprints" / "2026.23.yaml")
    assert sprint["products"] == {p: {"preplanned": 2} for p in ("webshop", "app", "portal")}
    assert "Saldo" in result.output


def drop_done(data_dir: Path, product: str, *sprint_ids: str) -> None:
    """Removes the product's "Done" in the sprints (not recorded, not 0)."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    for sprint_id in sprint_ids:
        sprint = data.sprint(sprint_id)
        sprint.products[product].done = None
        repo.save_sprint("demo", sprint)


FOOTNOTE = (
    "„ohne Wert“: Sprints, in denen das Produkt betreut wurde, aber kein Erledigt erfasst "
    "ist, obwohl es für andere Produkte erfasst ist (leer, nicht 0). Sie zählen im Saldo "
    "nicht mit; bitte den Wert im Sprint nachtragen. Sprints ohne jeden Erledigt-Wert "
    "(z. B. der laufende) und Sprints außerhalb der Laufzeit des Produkts bleiben außen vor."
)


def balance_table(output: str) -> str:
    return output.split("Saldo: Σ Erledigt − Σ Standard")[1]


def test_products_balance_hides_products_without_value_and_shows_missing(data_dir: Path):
    plain = run(data_dir, "products", "demo", "2026.20", "--history", "6")
    assert "ohne Wert" not in balance_table(plain.output)  # everything recorded: no column
    assert FOOTNOTE not in " ".join(plain.output.split())

    drop_done(data_dir, "app", "2026.20")
    # Window with only the sprint without a value: no row "0 | 0,00 | 0,00 | 0,00"
    only = run(data_dir, "products", "demo", "2026.20", "--history", "1")
    assert only.exit_code == 0, only.output
    table = balance_table(only.output)
    assert "Webshop" in table and "Mobile App" not in table
    # The hidden product has a missing value, the shown ones do not: no column
    assert "ohne Wert" not in table and FOOTNOTE not in " ".join(table.split())

    # otherwise the product stays with its other sprints, the missing ones appear next to them
    result = run(data_dir, "products", "demo", "2026.20", "--history", "6")
    assert result.exit_code == 0, result.output
    table = balance_table(result.output)
    assert "ohne Wert" in table
    # footnote explains the column (line breaks do not matter)
    assert FOOTNOTE in " ".join(table.split())
    app_row = next(line for line in table.splitlines() if "Mobile App" in line)
    cells = [c.strip() for c in app_row.strip("│").split("│")]
    assert cells[1] == "3" and cells[-1] == "1"
    webshop_row = next(line for line in table.splitlines() if "Webshop" in line)
    assert webshop_row.strip("│").split("│")[-1].strip() == "0"


def test_report_balance_hides_products_without_value_and_shows_missing(data_dir: Path):
    def balance_section() -> str:
        assert run(data_dir, "report", "demo").exit_code == 0
        report = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
        return report.split("**Saldo**")[1].split("\n## ")[0]

    assert "ohne Wert" not in balance_section()
    assert FOOTNOTE not in balance_section()

    drop_done(data_dir, "app", "2026.20")
    section = balance_section()
    assert f"*{FOOTNOTE}*" in section  # footnote below the table, only for missing values
    rows = {line.split("|")[1].strip(): line for line in section.splitlines() if "|" in line}
    assert "ohne Wert" in rows["Produkt"]
    cells = [c.strip() for c in rows["Mobile App"].strip("|").split("|")]
    assert cells[1] == "3" and cells[-1] == "1"
    assert rows["Webshop"].strip("|").split("|")[-1].strip() == "0"

    # A single sprint with a value is enough, the row stays
    drop_done(data_dir, "app", "2026.17", "2026.18")
    assert "Mobile App" in balance_section()

    # No value in any sprint of the window: the product is dropped instead of showing as a zero row,
    # and the hidden product does not switch the column on (as in the web UI)
    drop_done(data_dir, "app", "2026.19")
    section = balance_section()
    assert "Mobile App" not in section and "ohne Wert" not in section
    assert FOOTNOTE not in section


def test_balance_missing_ignores_sprints_without_any_done_value(data_dir: Path):
    # Sprint without any "Done" value (like the running one): counts nowhere, not even in "no value"
    drop_done(data_dir, "webshop", "2026.20")
    drop_done(data_dir, "app", "2026.20")
    drop_done(data_dir, "portal", "2026.20")
    drop_done(data_dir, "app", "2026.19")  # only here it is missing for a single product
    assert run(data_dir, "report", "demo").exit_code == 0
    report = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    section = report.split("**Saldo**")[1].split("\n## ")[0]
    rows = {line.split("|")[1].strip(): line for line in section.splitlines() if "|" in line}
    assert rows["Mobile App"].strip("|").split("|")[-1].strip() == "1"
    assert rows["Webshop"].strip("|").split("|")[-1].strip() == "0"


def test_balance_missing_ignores_sprints_outside_product_period(data_dir: Path):
    # "Mobile App" is only maintained from 2026.19; before that it is neither active nor recorded
    path = data_dir / "demo" / "products.yaml"
    content = load(path)
    next(p for p in content["products"] if p["id"] == "app")["from"] = date(2026, 9, 16)
    path.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")
    drop_done(data_dir, "app", "2026.17", "2026.18", "2026.19")
    assert run(data_dir, "report", "demo").exit_code == 0
    report = (data_dir / "demo" / "FORECAST.md").read_text(encoding="utf-8")
    section = report.split("**Saldo**")[1].split("\n## ")[0]
    rows = {line.split("|")[1].strip(): line for line in section.splitlines() if "|" in line}
    cells = [c.strip() for c in rows["Mobile App"].strip("|").split("|")]
    # only 2026.19 (maintained, no value) counts as missing, 2026.17/.18 are before the start
    assert cells[1] == "1" and cells[-1] == "1"


def test_product_list_add_and_end(data_dir: Path):
    answers = ["n", "Neues Produkt", "Cleo", "2026-11-01", "e", "mobile app", "2026-12-31", "q"]
    result = run(data_dir, "product-list", "demo", input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    products = load(data_dir / "demo" / "products.yaml")["products"]
    assert products[-1] == {
        "id": "neues-produkt", "name": "Neues Produkt", "po": "Cleo",
        "from": date(2026, 11, 1), "to": None,
    }  # fmt: skip
    assert products[1]["to"] == date(2026, 12, 31)


def test_update_outside_uv_tool(data_dir: Path):
    result = run(data_dir, "update", "--check")
    assert result.exit_code == 1
    assert "nicht mit `uv tool install` installiert" in result.output


def test_sprints_calendar_and_longer_sprint(data_dir: Path):
    result = run(data_dir, "sprints", "demo")
    assert result.exit_code == 0, result.output
    assert "Di 27.10.2026" in result.output  # last day of 2026.21
    # 2026.25 three weeks until Tue 12.01.2027 → 2026.26 is dropped, then 2027.1
    result = run(data_dir, "sprints", "demo", "--end", "2026.25=2027-01-12", "--create")
    assert result.exit_code == 0, result.output
    s25 = load(data_dir / "demo" / "sprints" / "2026.25.yaml")
    assert s25["end"] == date(2027, 1, 13)
    nxt = load(data_dir / "demo" / "sprints" / "2027.1.yaml")
    assert nxt["start"] == date(2027, 1, 13)
    assert run(data_dir, "check").exit_code == 0


def test_forecast_derivation(data_dir: Path):
    result = run(data_dir, "forecast", "demo", "--explain", "2026.22")
    assert result.exit_code == 0, result.output
    assert "Rechenweg Sprint 2026.22" in result.output
    assert "16,8433 / 45 × 30 = 11,229" in result.output


def test_data_folder(tmp_path: Path, data_dir: Path):
    import subprocess

    assert run(data_dir, "data-dir", str(tmp_path)).exit_code == 1  # no Git
    subprocess.run(["git", "init", "-q", str(data_dir)], check=True)
    result = run(data_dir, "data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Datenordner gemerkt" in result.output
    assert "Gemerkt:" in run(data_dir, "data-dir").output


def test_data_folder_names_the_reason_for_an_unsafe_folder(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    import subprocess

    from gitrepos import assume_foreign_owner

    subprocess.run(["git", "init", "-q", str(data_dir)], check=True)
    assume_foreign_owner(monkeypatch, data_dir)
    result = run(data_dir, "data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "dubious ownership" in result.output  # the message from Git
    assert "Git-Einstellungen" in " ".join(result.output.split())  # the hint
    assert "liegt in keinem Git-Repository" not in result.output
    assert "Git hält den Ordner für unsicher" in result.output  # the heading
    # The app never advises a configuration change, not even with Git's wording.
    assert "safe.directory" not in result.output and "git config" not in result.output


def one_line(output: str) -> str:
    """Output without console line breaks (Rich wraps long lines)."""
    return " ".join(output.split())


@pytest.fixture
def without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git is not installed on this machine (not in PATH)."""
    empty = tmp_path / "ohne-git"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


@pytest.fixture
def data_repo(data_dir: Path, tmp_path: Path) -> Path:
    """The data directory is in a Git repository (root is ``tmp_path``)."""
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
    assert "Gespeichert:" in result.output  # the data is written, just not committed


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
    # No user settings of the machine (on Windows: USERPROFILE instead of HOME): otherwise Git
    # would find a name there.
    empty = tmp_path.parent / f"{tmp_path.name}-leer.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "leer"))
    result = commit_planning(data_dir)
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Name und E-Mail-Adresse fehlen" in text
    assert "git config --global user.name" in text and "git config --global user.email" in text
    assert "Dein Name" in text  # the command-line hint, not only Git's own message
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


def test_data_folder_without_git_installed_says_so(
    tmp_path: Path, data_dir: Path, without_git: None
):
    result = run(data_dir, "data-dir", str(data_dir))
    assert result.exit_code == 1
    text = one_line(result.output)
    assert "Git ist nicht installiert" in text
    assert "Git installieren" in text
    assert "liegt in keinem Git-Repository" not in text
    assert "Kein Datenordner gemerkt." in run(data_dir, "data-dir").output


def test_data_folder_names_a_folder_without_repository(tmp_path: Path, data_dir: Path):
    result = run(data_dir, "data-dir", str(tmp_path))
    assert result.exit_code == 1
    assert "liegt in keinem Git-Repository (git init bzw. git clone)" in one_line(result.output)
    assert "Git ist nicht installiert" not in result.output


@pytest.mark.parametrize("parts", [("x[a]",), ("x[", "y]", "b")])
def test_data_folder_messages_keep_brackets_in_the_path(
    tmp_path: Path, data_dir: Path, parts: tuple[str, ...]
):
    """Rich reads square brackets as markup: the path is escaped and appears completely in the
    message (an unmatched "[/y]" used to abort the command)."""
    folder = tmp_path.joinpath(*parts)
    folder.mkdir(parents=True)
    shown = "/".join(parts)  # Rich wraps long paths: check only the names
    result = run(data_dir, "data-dir", str(folder))
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert shown in one_line(result.output).replace("\\", "/")
    missing = run(data_dir, "data-dir", str(folder / "fehlt"))
    assert missing.exit_code == 1
    assert shown in one_line(missing.output).replace("\\", "/")


def test_forecast_warns_for_noise_extrapolating_trend_mode(data_dir: Path):
    plain = run(data_dir, "forecast", "demo")
    assert "schreibt Schwankungen fort" not in plain.output  # default flat: no warning
    team = data_dir / "demo" / "team.yaml"
    team.write_text(
        team.read_text(encoding="utf-8").replace("trend_mode: flat", "trend_mode: classic"),
        encoding="utf-8",
    )
    result = run(data_dir, "forecast", "demo")
    assert "Trend-Modus classic" in result.output and "schreibt Schwankungen fort" in result.output
    report = run(data_dir, "report", "demo", "-o", "-")
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
    for args in (["data-dir", str(repo)], ["language", "en"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert "Zugriff verweigert" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_help_command_list_covers_every_cli_command():
    """Every CLI command is in guide.COMMANDS, and no unknown command is listed there."""
    registered = {
        info.name
        for info in app.registered_commands
        if info.callback.__module__ == "sprintforecast.cli"
    }
    listed = {
        m[1] for left, _ in COMMANDS if (m := re.match(r"sprintforecast ([a-z][\w-]*)", left))
    }
    assert not registered - listed, f"Fehlt in guide.COMMANDS: {registered - listed}"
    assert not listed - registered, f"Kein CLI-Befehl: {listed - registered}"


GERMAN_COMMANDS = [
    "hilfe", "fehltage", "personen", "einstellungen", "analyse", "bericht", "pruefen",
    "kapazitaet", "produkte", "produktliste", "aktualisieren", "verknuepfung", "datenordner",
    "sprache",
]  # fmt: skip


def _no_ansi(text: str) -> str:
    """Strip color codes: in CI (FORCE_COLOR) Rich colors the help."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.mark.parametrize("lang", ["de", "en"])
def test_help_shows_only_english_names(monkeypatch: pytest.MonkeyPatch, lang: str):
    """Commands, options and environment variables have English names in both languages."""
    from sprintforecast import i18n

    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    output = _no_ansi(runner.invoke(app, ["--help"]).output)
    for english in ("help", "absences", "people", "check", "report", "data-dir", "language"):
        assert re.search(rf"│ {english}\s", output), english
    for german in GERMAN_COMMANDS:
        assert not re.search(rf"│ {german}\s", output), german
    assert "--data" in output and "--as-of" in output
    assert "--daten" not in output and "--stichtag" not in output
    assert "SPRINTFORECAST_DATA" in output and "SPRINTFORECAST_DATEN" not in output
    output = _no_ansi(runner.invoke(app, ["forecast", "--help"]).output)
    assert "--explain" in output and "--rechenweg" not in output
    assert "--history" in output and "--verlauf" not in output
    output = _no_ansi(runner.invoke(app, ["help", "--help"]).output)
    assert "[TOPIC]" in output and "THEMA" not in output
    assert "workflow, terms, fields, team, commands" in output


@pytest.mark.parametrize("german", GERMAN_COMMANDS)
def test_german_command_names_are_gone(data_dir: Path, german: str):
    result = run(data_dir, german)
    assert result.exit_code == 2, result.output
    assert f"No such command '{german}'" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--daten", "x", "forecast", "demo"],
        ["--stichtag", "2026-10-15", "forecast", "demo"],
        ["forecast", "demo", "--rechenweg", "2026.22"],
        ["analysis", "demo", "--rest", "20"],
        ["people", "demo", "--ehemalige"],
        ["sprints", "demo", "--anlegen"],
        ["check", "--streng"],
        ["update", "--pruefen"],
    ],
)
def test_german_option_names_are_gone(data_dir: Path, args: list[str]):
    result = runner.invoke(app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args])
    assert result.exit_code == 2, result.output
    assert "No such option" in result.output


def test_german_help_topics_are_gone(data_dir: Path):
    result = run(data_dir, "help", "workflow")
    assert result.exit_code == 0 and "sprintforecast absences TEAM [SPRINT]" in result.output
    result = run(data_dir, "help", "commands")
    assert "sprintforecast check [--strict]" in result.output
    assert "sprintforecast --data PATH …" in result.output
    assert "Weitere Themen: workflow, terms, fields, team (sprintforecast help TOPIC)" in (
        result.output
    )
    for german in ("ablauf", "begriffe", "felder", "befehle"):
        result = run(data_dir, "help", german)
        assert result.exit_code == 1
        assert "Verfügbar: workflow, terms, fields, team, commands" in result.output


def test_legacy_env_names_are_ignored(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast import storage

    empty = tmp_path / "leer"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.delenv(storage.DATA_ENV, raising=False)
    monkeypatch.setenv("SPRINTFORECAST_DATEN", str(data_dir))
    assert storage.default_data_dir() == Path(".")
    monkeypatch.setenv(storage.DATA_ENV, str(data_dir))
    assert storage.default_data_dir() == data_dir
    result = runner.invoke(app, ["--as-of", "2026-10-15", "forecast", "demo"])
    assert result.exit_code == 0, result.output
    assert "Demo-Team" in result.output


def test_auto_update_takes_english_values_only(monkeypatch: pytest.MonkeyPatch):
    from sprintforecast import updater

    saved: list[str] = []
    monkeypatch.setattr(updater, "update_state", lambda **kw: saved.append(kw["mode"]))
    monkeypatch.delenv(updater.MODE_ENV, raising=False)
    for value in ("on", "notice", "off"):
        result = runner.invoke(app, ["update", "--auto", value])
        assert result.exit_code == 0, result.output
    assert saved == ["on", "notice", "off"]
    for value in ("hinweis", "egal"):
        result = runner.invoke(app, ["update", "--auto", value])
        assert result.exit_code == 1 and "--auto: on, notice oder off" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["forecast", "demo", "--history", "-1"],
        ["sprints", "demo", "--count", "0"],
        ["sprints", "demo", "--count", "100000", "--create"],
        ["web", "--port", "0"],
        ["web", "--port", "70000"],
        ["products", "demo", "--history", "0"],
    ],
)
def test_option_ranges_are_checked_before_anything_runs(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output


def test_zero_history_is_empty_not_everything():
    from datetime import date

    from sprintforecast.forecast import Forecast

    class Entry:
        class sprint:
            end = date(2026, 1, 1)

    fc = Forecast.__new__(Forecast)
    fc.entries = [Entry(), Entry(), Entry()]
    fc.today = date(2026, 6, 1)
    assert fc.history(0) == []
    assert len(fc.history(2)) == 2
    assert len(fc.history()) == 3


def test_invalid_state_is_refused_before_writing(data_dir: Path):
    import copy
    from types import SimpleNamespace

    import typer

    data = Repository(data_dir).load("demo")
    ctx = SimpleNamespace(today=date(2026, 10, 15))
    cli._refuse_invalid(ctx, data, data, "team.yaml")  # a valid state passes
    broken = copy.copy(data)
    broken.team = copy.deepcopy(data.team)
    broken.team.forecast.window = 0
    with pytest.raises(typer.Exit):
        cli._refuse_invalid(ctx, data, broken, "team.yaml")
    cli._refuse_invalid(
        ctx, data, broken, "people.yaml"
    )  # errors in other files do not matter here


def test_refusal_sees_errors_of_an_in_place_edit(data_dir: Path):
    """The settings command edits ``data.team`` in place; the old state is its deep copy."""
    import copy
    from types import SimpleNamespace

    import typer

    data = Repository(data_dir).load("demo")
    before = copy.deepcopy(data.team)
    data.team.forecast.window = 0  # in place, like _ask_setting
    after = copy.copy(data)
    old = copy.copy(data)
    old.team = before
    with pytest.raises(typer.Exit):
        cli._refuse_invalid(SimpleNamespace(today=date(2026, 10, 15)), old, after, "team.yaml")


def test_new_person_with_invalid_region_is_refused_at_once(data_dir: Path):
    # An unknown person region is refused right at the input and the session goes on.
    people = data_dir / "demo" / "people.yaml"
    before = people.read_text(encoding="utf-8")
    result = run(data_dir, "people", "demo", input="n\nNeu Person\nZZ\n2026-11-01\n1\nq\n")
    assert result.exit_code == 0, result.output
    assert people.read_text(encoding="utf-8") == before
    assert "Region 'ZZ'" in result.output


def test_new_person_is_not_blamed_for_an_earlier_edit_of_the_session(data_dir: Path):
    # The FTE 1.5 of Anna is invalid, but that belongs to the earlier step: the valid new
    # person must not be refused for it (the final check at the end still refuses the save).
    result = run(
        data_dir,
        "people",
        "demo",
        input="f\nAnna\n2026-11-01\n1.5\nn\nNeu Person\n\n2026-11-01\n1\nq\n",
    )
    assert result.exit_code == 1, result.output
    assert "fte 1.5" in result.output
    assert result.output.count("fte 1.5") == 1  # reported once, at the save
