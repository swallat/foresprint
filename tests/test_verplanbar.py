# SPDX-License-Identifier: EUPL-1.2
"""Anzeigename „Verplanbarer Anteil“ (früher „Roadmap“): nur die Beschriftung ändert sich.

Der Speicherschlüssel ``forecast.roadmap_share`` (und ``product_basis: roadmap``) bleibt, damit
bestehende Dateien lesbar und Änderungen zusammenführbar bleiben.

Bewusst weiter „roadmap“ genannt (und deshalb hier nicht geprüft):
- der YAML-Schlüssel ``roadmap_share`` und der Wert ``product_basis: roadmap`` (Speicherformat),
- die Schlüsselspalte der Excel-Mappe und der benannte Bereich ``Roadmap_Anteil`` in den
  Formeln (alte Exporte müssen importierbar bleiben),
- der Wert „roadmap“ in der Auswahl „Standardverteilung je Produkt“ (steht vor dem Text),
- die Hilfetabelle „team“ der Kommandozeile, die den Schlüssel ``forecast.roadmap_share``
  anzeigt (kleingeschrieben; geprüft wird nur das großgeschriebene Wort „Roadmap“).
"""

from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.cli import app
from sprintforecast.forecast import build_forecast
from sprintforecast.report import render
from sprintforecast.settings import SETTINGS
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
runner = CliRunner(env={"COLUMNS": "250"})
KEY = "roadmap_share"
WORD = "Roadmap"  # großgeschrieben = sichtbare Beschriftung; Schlüssel sind kleingeschrieben


def test_roadmap_share_key_is_still_read_and_written(data_dir: Path):
    repo = Repository(data_dir)
    team_yaml = data_dir / "demo" / "team.yaml"
    assert KEY in team_yaml.read_text(encoding="utf-8")
    data = repo.load("demo")
    assert data.team.forecast.roadmap_share == pytest.approx(0.8)
    data.team.forecast.roadmap_share = 0.65
    repo.save_team(data.team)
    raw = yaml.safe_load(team_yaml.read_text(encoding="utf-8"))
    assert raw["forecast"][KEY] == pytest.approx(0.65)
    assert "verplanbar" not in team_yaml.read_text(encoding="utf-8").lower()
    assert repo.load("demo").team.forecast.roadmap_share == pytest.approx(0.65)


def test_setting_is_called_verplanbarer_anteil():
    setting = next(s for s in SETTINGS if s.key == "forecast.roadmap_share")
    assert setting.label == "Verplanbarer Anteil (%)"
    assert "Kleinkram" in setting.help
    assert WORD not in setting.label + setting.help


def run(data_dir: Path, *args: str) -> str:
    result = runner.invoke(app, ["--daten", str(data_dir), "--stichtag", "2026-10-15", *args])
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize(
    "args",
    [
        ("forecast", "demo"),
        ("analyse", "demo", "--rest", "20"),
        ("analyse", "demo", "--rest", "20", "--gesamt"),
        ("hilfe",),
        ("hilfe", "begriffe"),
        ("hilfe", "felder"),
        ("hilfe", "team"),
        ("hilfe", "befehle"),
        ("analyse", "--help"),
    ],
)
@pytest.mark.parametrize("lang", ["de", "en"])
def test_command_line_shows_no_roadmap_label(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], lang: str
):
    from sprintforecast import i18n

    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        output = run(data_dir, *args) if args[-1] != "--help" else runner.invoke(app, args).output
    finally:
        i18n.set_language(None)
    assert WORD not in output
    assert "roadmap" not in output.replace("roadmap_share", "")  # englische Beschriftung


def test_command_line_names_the_column_verplanbar(data_dir: Path):
    output = run(data_dir, "forecast", "demo")
    assert "Verplanbar" in output
    assert "Kleinkram" in output


def test_report_shows_no_roadmap_label(data_dir: Path):
    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    text = render(fc)
    assert "Verplanbar (80 %)" in text
    assert "roadmap" not in text.lower()


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize(
    "page", ["forecast", "analyse", "einstellungen", "planning", "produkte", "hilfe", "start"]
)
def test_web_pages_show_no_roadmap_label(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str, lang: str
):
    from sprintforecast import i18n

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        at.switch_page(f"seiten/{page}.py").run()
        assert not at.exception, at.exception
        shown = repr(at.main) + repr(at.sidebar)
    finally:
        i18n.set_language(None)
    # Widget-Schlüssel (settings-demo-forecast.roadmap_share) sind kleingeschrieben und bleiben.
    assert WORD not in shown
    # Die Auswahl „Standardverteilung je Produkt“ zeigt den Speicherwert vor dem Text
    # („roadmap – nur verplanbarer Anteil …“); der Wert bleibt (Speicherformat).
    rest = shown.replace("roadmap_share", "").replace("'roadmap'", "").replace("roadmap – ", "")
    assert "roadmap" not in rest
