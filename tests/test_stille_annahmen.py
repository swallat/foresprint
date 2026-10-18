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


def messages(text: str) -> list[str]:
    return [i.message for i in check_yaml_text(text, "x.yaml")]


def test_leerer_wert_in_expected_absences_und_preplanned():
    assert any("expected_absences.anna" in m for m in messages("expected_absences:\n  anna:\n"))
    text = "prognoses:\n- at: 2026-10-01T10:00:00\n  preplanned:\n    app:\n"
    assert any("prognoses[0].preplanned.app" in m for m in messages(text))


def test_zwei_merge_keys_in_einem_mapping_sind_kein_duplikat():
    text = "a: &a {x: 1}\nb: &b {y: 2}\nc:\n  <<: *a\n  <<: *b\n  z: 3\nd:\n  <<: [*a, *b]\n"
    assert messages(text) == []


def test_leerer_wert_ueber_anker_und_merge_wird_unter_jedem_pfad_gemeldet():
    text = (
        "people:\n- id: a\n  memberships:\n  - &m {from: 2025-01-01, fte: }\n  - *m\n"
        "- id: b\n  memberships:\n  - <<: *m\n    from: 2025-02-01\n"
    )
    found = " ".join(messages(text))
    for path in ("people[0].memberships[0].fte", "people[0].memberships[1].fte"):
        assert path in found
    assert "people[1].memberships[0].fte" in found


def test_rekursiver_anker_bricht_nicht_ab():
    assert messages("a: &x [*x, 1]\nb: &y {k: *y}\n") == []


def test_anker_bombe_wird_begrenzt_und_gemeldet():
    lines = ["l0: &l0 [x, x, x, x, x, x, x, x, x]"]
    for n in range(1, 12):
        lines.append(f"l{n}: &l{n} [{', '.join([f'*l{n - 1}'] * 9)}]")
    [found] = messages("\n".join(lines) + "\n")
    assert "nicht vollständig geprüft" in found


def test_extreme_verschachtelung_stuerzt_nicht_ab():
    depth = 5000
    text = "a: " + "[" * depth + "]" * depth + "\n"
    check_yaml_text(text, "x.yaml")  # darf keine Ausnahme werfen
    block = "".join("  " * i + "- \n" for i in range(depth))
    check_yaml_text("a:\n" + block, "x.yaml")


def test_schluessel_typ_unterscheidet_ausser_bei_kuerzeln():
    # Kürzel werden mit str() gelesen: 1 und "1" sind dort derselbe Schlüssel ...
    assert any("absences.1" in m for m in messages('absences:\n  1: 2\n  "1": 3\n'))
    assert any("products.1" in m for m in messages('products:\n  1: {}\n  "1": {}\n'))
    # ... sonst behält der Lader beide Einträge
    assert messages('1: a\n"1": b\n') == []
    assert messages("x: 1\ntrue: a\n'True': b\n") == []
    assert any("'True'" in m for m in messages("true: a\ntrue: b\n"))


def test_duplikat_in_einer_zeile_nennt_die_spalten():
    [found] = messages("absences: {anna: 1, anna: 2}\n")
    assert "alle in Zeile 1, Spalten 12, 21" in found
    assert "letzten Eintrag (Zeile 1, Spalte 21)" in found


def test_kommandozeile_maskiert_markup_aus_dateien(data_dir: Path):
    edit(data_dir, SPRINT, "  anna: 5\n", "  '[red]x[/red]': 1\n  '[red]x[/red]': 2\n  anna: 5\n")
    env = {DATA_ENV: str(data_dir), STICHTAG_ENV: TODAY.isoformat()}
    result = runner.invoke(cli_app, ["pruefen"], env=env)
    assert "[red]x[/red]" in result.output


def test_weboberflaeche_zeigt_schluesselnamen_nie_als_markdown(data_dir: Path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    evil = "[Klick](http://evil.example) www.evil.example **fett**"
    edit(data_dir, SPRINT, "  anna: 5\n", f"  '{evil}': 1\n  '{evil}': 2\n  anna: 5\n")
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, TODAY.isoformat())
    app_file = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app_file), default_timeout=30)
    at.run()
    at.switch_page("seiten/pruefung.py").run()
    assert not at.exception, at.exception
    shown = [w.value for w in at.warning if "mehrfach" in w.value]
    assert shown
    text = "\n".join(shown)
    # Jedes Satzzeichen aus der Datei trägt einen Backslash: Markdown deutet nichts davon
    assert "\\[Klick\\]\\(http\\:\\/\\/evil\\.example\\)" in text
    assert "\\*\\*fett\\*\\*" in text
    assert "www.evil" not in text
