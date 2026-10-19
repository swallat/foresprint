# SPDX-License-Identifier: EUPL-1.2
"""Jeder übersetzbare Text hat eine englische Fassung mit denselben Platzhaltern."""

import ast
import string
from pathlib import Path

import pytest

from sprintforecast import i18n
from sprintforecast.locale_en import EN

SRC = Path(__file__).parent.parent / "src" / "sprintforecast"


def literal_calls() -> list[tuple[str, int, str]]:
    """Alle t("…")-Aufrufe mit konstantem Text: (Datei, Zeile, Text)."""
    found = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"t", "_t"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append((path.name, node.lineno, node.args[0].value))
    return found


def static_texts() -> list[str]:
    """Texte aus Datenstrukturen, die erst bei der Anzeige übersetzt werden."""
    from sprintforecast.i18n_texts import all_static_texts

    return all_static_texts()


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_every_text_is_translated():
    missing = sorted({text for _, _, text in literal_calls() if text not in EN})
    missing += sorted(text for text in static_texts() if text not in EN)
    assert not missing, "Ohne Übersetzung:\n" + "\n".join(missing)


def test_placeholders_match():
    wrong = [de for de, en in EN.items() if fields(de) != fields(en)]
    assert not wrong, wrong


def test_switch_language(monkeypatch: pytest.MonkeyPatch):
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, "en")
    assert i18n.t("Datei fehlt: {path}", path="x") == "File missing: x"
    monkeypatch.setenv(i18n.LANG_ENV, "de")
    assert i18n.t("Datei fehlt: {path}", path="x") == "Datei fehlt: x"
    monkeypatch.delenv(i18n.LANG_ENV)
    i18n.save_language("en")
    assert i18n.language() == "en"


def test_default_language_is_english(tmp_path: Path):
    """Ohne Umgebungsvariable und ohne gespeicherte Einstellung ist die Oberfläche englisch.
    (Die Testsuite selbst setzt die Vorgabe in conftest.py auf Deutsch, daher ein eigener
    Prozess.)"""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("SPRINTFORECAST_")}
    env |= {"XDG_CONFIG_HOME": str(tmp_path), "APPDATA": str(tmp_path)}
    code = (
        "from sprintforecast import i18n; "
        "print(i18n.DEFAULT, i18n.language(), i18n.t('Datei fehlt: {path}', path='x'))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert done.stdout.split() == ["en", "en", "File", "missing:", "x"]


def test_german_texts_name_the_english_commands(data_dir: Path):
    """Auch die deutsche Oberfläche nennt die Befehle und Optionen englisch."""
    from typer.testing import CliRunner

    from sprintforecast.cli import app

    runner = CliRunner(env={"COLUMNS": "200"})
    result = runner.invoke(
        app, ["--data", str(data_dir), "--as-of", "2026-10-15", "help", "commands"]
    )
    assert result.exit_code == 0, result.output
    assert "sprintforecast absences TEAM [SPRINT]" in result.output
    assert "Weitere Themen: workflow, terms, fields, team (sprintforecast help TOPIC)" in (
        result.output
    )
    assert "fehltage" not in result.output


def test_cli_in_english(data_dir: Path, english):
    from typer.testing import CliRunner

    from sprintforecast.cli import app

    runner = CliRunner(env={"COLUMNS": "200"})
    base = ["--data", str(data_dir), "--as-of", "2026-10-15"]
    result = runner.invoke(app, [*base, "forecast", "demo", "--explain", "2026.22"])
    assert result.exit_code == 0, result.output
    assert "Calculation sprint 2026.22" in result.output
    assert "11.229" in result.output  # Dezimalpunkt
    assert "Small items" in result.output
    result = runner.invoke(app, [*base, "help", "commands"])
    assert "sprintforecast absences TEAM [SPRINT]" in result.output
    assert runner.invoke(app, [*base, "check"]).exit_code == 0
    result = runner.invoke(app, [*base, "report", "demo", "-o", "-"])
    assert "## History (last" in result.output and "Small items" in result.output


def test_capacity_in_english(data_dir: Path, english):
    from datetime import date

    from sprintforecast.forecast import build_forecast
    from sprintforecast.formulas import plain_explanation, step
    from sprintforecast.report import fmt_capacity
    from sprintforecast.storage import Repository

    assert fmt_capacity(25.25) == "25.3"  # kaufmännisch gerundet, Dezimalpunkt
    assert fmt_capacity(1234.25) == "1,234.3"
    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    e = fc.entry("2026.23")  # Kapazität 30,4375 (erwartete Fehltage: aus der Historie geschätzt)
    assert "30.4 PT are available" in plain_explanation(fc, e)
    assert "16.8433 / 45 × 30.4375 = 11.393" in plain_explanation(fc, e)
    assert step(fc, e, "plan").calculation == "16.8433 / 45 × 30.4375 = 11.393 → 11.3 PT"
    assert step(fc, e, "capacity").calculation == "= 30.4 PT"


def test_language_command(data_dir: Path):
    from typer.testing import CliRunner

    from sprintforecast.cli import app

    i18n.set_language(None)
    result = CliRunner().invoke(app, ["--daten", str(data_dir), "sprache", "en"])
    assert result.exit_code == 0, result.output
    assert "Language: English" in result.output
    assert i18n.language() == "en"
    i18n.set_language(None)
    i18n.save_language("de")


def test_web_pages_in_english(data_dir: Path, english, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import DATA_ENV, STICHTAG_ENV
    from sprintforecast.web.ui import PAGE_INFO

    i18n.save_language("en")
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    app_file = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app_file), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert at.header[0].value == "What would you like to do?"
    for page in sorted(PAGE_INFO):
        at.switch_page(f"seiten/{page}.py").run()
        assert not at.exception, (page, at.exception)
    at.switch_page("seiten/planning.py").run()
    assert at.radio(key="planning-step").options == [
        "1 · Absences", "2 · Forecast PLAN & planning", "3 · Commitment",
    ]  # fmt: skip
