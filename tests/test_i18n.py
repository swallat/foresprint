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


@pytest.fixture
def english(monkeypatch: pytest.MonkeyPatch):
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, "en")
    yield
    i18n.set_language(None)


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
    assert any("Upcoming events" in c.value for c in at.caption)
    for page in sorted(PAGE_INFO):
        at.switch_page(f"seiten/{page}.py").run()
        assert not at.exception, (page, at.exception)
    at.switch_page("seiten/planning.py").run()
    assert at.radio(key="planning-step").options == [
        "1 · Absences", "2 · Forecast PLAN & planning", "3 · Commitment",
    ]  # fmt: skip
