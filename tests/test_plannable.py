# SPDX-License-Identifier: EUPL-1.2
"""Display name "Plannable share" (formerly "Roadmap"): only the label changes.

The storage key ``forecast.roadmap_share`` (and ``product_basis: roadmap``) stays so that existing
files remain readable and changes remain mergeable.

Deliberately still called "roadmap" (and therefore not checked here):
- the YAML key ``roadmap_share`` and the value ``product_basis: roadmap`` (storage format),
- the key column of the Excel workbook and the named range ``Roadmap_Anteil`` in the formulas
  (old exports must stay importable),
- the value "roadmap" in the selection "Standard distribution per product" (it comes before the
  text),
- the help table "team" of the command line, which shows the key ``forecast.roadmap_share``
  (lowercase; only the capitalized word "Roadmap" is checked).
"""

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from sprintforecast.cli import app
from sprintforecast.forecast import build_forecast
from sprintforecast.i18n import t
from sprintforecast.model import ProductBasis
from sprintforecast.report import render
from sprintforecast.settings import SETTINGS
from sprintforecast.storage import AS_OF_ENV, DATA_ENV, Repository

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
runner = CliRunner(env={"COLUMNS": "250"})
KEY = "roadmap_share"
WORD = "Roadmap"  # capitalized = visible label; keys are lowercase


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


def test_setting_is_called_plannable_share():
    setting = next(s for s in SETTINGS if s.key == "forecast.roadmap_share")
    assert t(setting.label) == "Verplanbarer Anteil (%)"
    assert "Kleinkram" in t(setting.help)
    assert WORD not in setting.label + setting.help


def run(data_dir: Path, *args: str) -> str:
    result = runner.invoke(app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args])
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize(
    "args",
    [
        ("forecast", "demo"),
        ("analysis", "demo", "--remaining", "20"),
        ("analysis", "demo", "--remaining", "20", "--total"),
        ("help",),
        ("help", "terms"),
        ("help", "fields"),
        ("help", "team"),
        ("help", "commands"),
        ("analysis", "--help"),
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
    assert "roadmap" not in output.replace("roadmap_share", "")  # English label


def test_command_line_names_the_column_plannable(data_dir: Path):
    output = run(data_dir, "forecast", "demo")
    assert "Verplanbar" in output
    assert "Kleinkram" in output


def test_report_shows_no_roadmap_label(data_dir: Path):
    fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
    text = render(fc)
    assert "Verplanbar (80 %)" in text
    assert "roadmap" not in text.lower()


@pytest.mark.parametrize("lang", ["de", "en"])
def test_formula_steps_name_the_plannable_share(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, lang: str
):
    from sprintforecast import i18n
    from sprintforecast.formulas import GENERAL, general, steps

    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
        entry = fc.upcoming()[0]
        step_texts = [(s.name, s.formula, s.calculation) for s in steps(fc, entry)]
        explained = [general(key) for key in GENERAL]
    finally:
        i18n.set_language(None)
    flat = " ".join(" ".join(row) for row in step_texts) + " ".join(explained)
    assert "oadmap" not in flat
    titles = [title for title, _, _ in step_texts]
    assert ("Verplanbar" if lang == "de" else "Plannable") in titles


def use_roadmap_basis(data_dir: Path) -> None:
    """Standard distribution per product from the plannable share (value ``roadmap``)."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.forecast.product_basis = ProductBasis.ROADMAP
    repo.save_team(data.team)


def test_planning_panel_keeps_its_separators(data_dir: Path):
    # The metrics row after "planning" (same function as for "absences_command").
    result = runner.invoke(
        app,
        ["--data", str(data_dir), "--as-of", "2026-10-15", "planning", "demo", "2026.20"],
        input="n\nn\nn\nn\n",
    )
    assert re.search(r"\(Verplanbar [\d.,]+ · Kleinkram [\d.,]+\)", result.output), result.output


def test_planning_panel_in_english(data_dir: Path, english):
    result = runner.invoke(
        app,
        ["--data", str(data_dir), "--as-of", "2026-10-15", "planning", "demo", "2026.20"],
        input="n\nn\nn\nn\n",
    )
    assert re.search(r"\(Plannable [\d.,]+ · \S.* [\d.,]+\)", result.output), result.output


@pytest.mark.parametrize("lang", ["de", "en"])
def test_product_distribution_names_the_plannable_share(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, lang: str
):
    from sprintforecast import i18n

    use_roadmap_basis(data_dir)
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        output = run(data_dir, "products", "demo", "2026.20")
    finally:
        i18n.set_language(None)
    assert ("Verplanbarer Anteil" if lang == "de" else "Plannable share") in output
    assert "oadmap" not in output


@pytest.mark.parametrize("lang", ["de", "en"])
def test_excel_labels_are_renamed_but_keys_stay(data_dir: Path, lang: str, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("xlsxwriter")
    from io import BytesIO

    from sprintforecast import i18n
    from sprintforecast.excel import build_workbook

    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        fc = build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15))
        book = openpyxl.load_workbook(BytesIO(build_workbook(fc)))
    finally:
        i18n.set_language(None)
    texts: list[str] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and not value.startswith("="):
                    texts.append(value)
    # Key (import reads it) and named range (formulas) stay unchanged.
    assert "forecast.roadmap_share" in texts
    assert "Roadmap_Anteil" in book.defined_names
    labels = [x for x in texts if x != "forecast.roadmap_share"]
    assert not [x for x in labels if "oadmap" in x]
    assert ("Verplanbarer Anteil" if lang == "de" else "Plannable share") in labels
    assert ("Verplanbar (PT)" if lang == "de" else "Plannable (PT)") in labels


WEB_PAGES = ["forecast", "analyse", "einstellungen", "planning", "produkte", "hilfe", "start"]


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("page", [*WEB_PAGES, "vorplanung"])
def test_web_pages_show_no_roadmap_label(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str, lang: str
):
    from sprintforecast import i18n

    use_roadmap_basis(data_dir)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, "2026-10-15")
    i18n.set_language(None)
    monkeypatch.setenv(i18n.LANG_ENV, lang)
    try:
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        at.switch_page(f"seiten/{page}.py").run()
        if page == "planning":  # step "2 · Forecast PLAN & planning" shows the metrics
            at.radio(key="planning-step").set_value(1).run()
        assert not at.exception, at.exception
        shown = repr(at.main) + repr(at.sidebar)
        # Metric labels and column headers are not in ``repr(at.main)``.
        shown += " ".join(m.label for m in at.metric)
        for frame in at.dataframe:
            shown += " ".join(str(c) for c in frame.value.columns)
    finally:
        i18n.set_language(None)
    if page == "forecast":
        plannable = "Verplanbar" if lang == "de" else "Plannable"
        assert any(plannable in frame.value.columns for frame in at.dataframe)
    if page == "planning":
        assert any(m.label.startswith(("Verplanbar", "Plannable")) for m in at.metric)
    # Widget keys (settings-demo-forecast.roadmap_share) are lowercase and stay.
    assert WORD not in shown
    # The selection "Standard distribution per product" shows the storage value before the text
    # ("roadmap – plannable share only …"); the value stays (storage format).
    rest = shown.replace("roadmap_share", "").replace("'roadmap'", "").replace("roadmap – ", "")
    assert "roadmap" not in rest
