# SPDX-License-Identifier: EUPL-1.2
"""Excel import on the settings page: preview first, written only after confirming (AppTest)."""

import io
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
openpyxl = pytest.importorskip("openpyxl")
pytest.importorskip("xlsxwriter")

from streamlit.testing.v1 import AppTest  # noqa: E402

from foresprint.excel import SHEET_FORECAST, build_workbook  # noqa: E402
from foresprint.forecast import build_forecast  # noqa: E402
from foresprint.storage import AS_OF_ENV, DATA_ENV, Repository  # noqa: E402

APP = Path(__file__).parent.parent / "src" / "foresprint" / "web" / "app.py"
UPLOADER = "excel-import-demo-file-0"
APPLY = "Änderungen übernehmen"


def exported(data_dir: Path) -> bytes:
    return build_workbook(build_forecast(Repository(data_dir).load("demo"), date(2026, 10, 15)))


def edited(content: bytes, edit) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    edit(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def settings_page(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page("page_scripts/settings.py").run()
    assert not at.exception, at.exception
    return at


def bump_velocity(data_dir: Path) -> tuple[bytes, str, float]:
    sprint = next(s for s in Repository(data_dir).load("demo").sprints if s.velocity is not None)

    def edit(wb: openpyxl.Workbook) -> None:
        for row in wb[SHEET_FORECAST].iter_rows(min_row=4):
            if row[0].value == sprint.id:
                row[4].value = sprint.velocity + 3
                return
        raise AssertionError("sprint not found")

    return edited(exported(data_dir), edit), sprint.id, sprint.velocity


def upload(at: AppTest, content: bytes) -> None:
    at.file_uploader(key=UPLOADER).upload("demo.xlsx", content).run()


def test_unchanged_workbook_reports_no_changes(data_dir: Path, monkeypatch):
    at = settings_page(data_dir, monkeypatch)
    upload(at, exported(data_dir))
    assert not at.exception, at.exception
    assert any("Keine Änderungen gegenüber" in i.value for i in at.info)
    assert not [b for b in at.button if b.label == APPLY]


def test_preview_writes_nothing_until_confirmed(data_dir: Path, monkeypatch):
    content, sprint_id, old = bump_velocity(data_dir)
    at = settings_page(data_dir, monkeypatch)
    upload(at, content)
    assert not at.exception, at.exception
    frame = at.dataframe[-1].value
    assert list(frame.columns) == ["Datei", "Wert", "bisher", "neu"]
    assert frame.to_dict("records")[0]["Datei"] == f"sprints/{sprint_id}.yaml"
    assert Repository(data_dir).load("demo").sprint(sprint_id).velocity == old

    next(b for b in at.button if b.label == APPLY).click().run()
    assert not at.exception, at.exception
    assert any(f"{sprint_id}.yaml" in s.value for s in at.success)
    assert Repository(data_dir).load("demo").sprint(sprint_id).velocity == old + 3


def test_foreign_file_is_refused_without_writing(data_dir: Path, monkeypatch):
    before = {p: p.read_bytes() for p in data_dir.rglob("*.yaml")}
    at = settings_page(data_dir, monkeypatch)
    upload(at, b"not a workbook")
    assert not at.exception, at.exception
    assert at.error
    assert not [b for b in at.button if b.label == APPLY]
    assert {p: p.read_bytes() for p in data_dir.rglob("*.yaml")} == before


def test_settings_form_shows_imported_values_after_apply(data_dir: Path, monkeypatch):
    team = Repository(data_dir).load("demo").team
    window = team.forecast.window

    def edit(wb: openpyxl.Workbook) -> None:
        for row in wb["Settings"].iter_rows(min_row=3):
            if row[2].value == "forecast.window":
                row[1].value = window + 1
                return
        raise AssertionError("setting not found")

    at = settings_page(data_dir, monkeypatch)
    assert at.number_input(key="settings-demo-forecast.window").value == window
    upload(at, edited(exported(data_dir), edit))
    next(b for b in at.button if b.label == APPLY).click().run()
    assert not at.exception, at.exception
    assert Repository(data_dir).load("demo").team.forecast.window == window + 1
    assert at.number_input(key="settings-demo-forecast.window").value == window + 1
    assert at.file_uploader(key="excel-import-demo-file-1").value is None


def test_workbook_of_another_team_is_refused_without_writing(data_dir: Path, monkeypatch):
    def other_team(wb: openpyxl.Workbook) -> None:
        for prop in wb.custom_doc_props.props:
            if prop.name == "sprintforecast-team":
                prop.value = "other"

    before = {p: p.read_bytes() for p in data_dir.rglob("*.yaml")}
    at = settings_page(data_dir, monkeypatch)
    upload(at, edited(exported(data_dir), other_team))
    assert not at.exception, at.exception
    assert any("'other'" in e.value for e in at.error)
    assert not [b for b in at.button if b.label == APPLY]
    assert {p: p.read_bytes() for p in data_dir.rglob("*.yaml")} == before


def test_workbook_parsed_once_per_upload(data_dir: Path, monkeypatch):
    import foresprint.excel_import as mod

    calls = []
    real = mod.read_workbook_keyed
    monkeypatch.setattr(mod, "read_workbook_keyed", lambda *a: calls.append(1) or real(*a))
    content, _, _ = bump_velocity(data_dir)
    at = settings_page(data_dir, monkeypatch)
    upload(at, content)
    at.run()
    at.run()
    assert len(calls) == 1
