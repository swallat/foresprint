# SPDX-License-Identifier: EUPL-1.2
"""Import der Excel-Ausgabe: Rundlauf ohne Verlust, Vorschau der Änderungen, Fehlermeldungen."""

import io
import shutil
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("xlsxwriter")

import openpyxl

from sprintforecast.excel import SHEET_FORECAST, SHEET_SPRINTS, build_workbook
from sprintforecast.excel_import import apply_import, plan_import, read_workbook
from sprintforecast.forecast import build_forecast
from sprintforecast.storage import DataError, Repository

TODAY = date(2026, 10, 15)


def exported(data_dir: Path) -> bytes:
    data = Repository(data_dir).load("demo")
    return build_workbook(build_forecast(data, TODAY))


def edited(content: bytes, edit) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    edit(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_roundtrip_has_no_changes(data_dir: Path):
    repo = Repository(data_dir)
    data = read_workbook(exported(data_dir), "demo")
    plan = plan_import(repo, data)
    assert plan.changes == [], plan.changes[:5]
    assert plan.files == []
    original = repo.load("demo")
    assert [s.id for s in data.sprints] == [s.id for s in original.sprints]
    assert [p.id for p in data.people] == [p.id for p in original.people]


def test_roundtrip_into_an_empty_data_folder_restores_every_file(data_dir: Path, tmp_path: Path):
    content = exported(data_dir)
    target = Repository(tmp_path / "neu")
    data = read_workbook(content, "demo")
    plan = plan_import(target, data)
    assert "team.yaml" in plan.files and any(f.startswith("sprints/") for f in plan.files)
    apply_import(target, plan)
    again = plan_import(target, read_workbook(content, "demo"))
    assert again.changes == []
    original = Repository(data_dir).load("demo")
    restored = target.load("demo")
    assert restored.sprints == original.sprints  # inklusive Fehltage, Produktwerte, Prognosen
    assert restored.people == original.people
    assert restored.products == original.products
    assert restored.team == original.team


def test_a_changed_value_is_listed_and_written(data_dir: Path):
    repo = Repository(data_dir)
    sprint = next(s for s in repo.load("demo").sprints if s.velocity is not None)

    def edit(wb: openpyxl.Workbook) -> None:
        ws = wb[SHEET_FORECAST]
        for row in ws.iter_rows(min_row=4):
            if row[0].value == sprint.id:
                row[4].value = (sprint.velocity or 0) + 3
                return
        raise AssertionError("Sprint nicht gefunden")

    data = read_workbook(edited(exported(data_dir), edit), "demo")
    plan = plan_import(repo, data)
    assert [(c.file, c.path) for c in plan.changes] == [(f"sprints/{sprint.id}.yaml", "velocity")]
    assert plan.changes[0].new == sprint.velocity + 3
    apply_import(repo, plan)
    assert repo.load("demo").sprint(sprint.id).velocity == sprint.velocity + 3


def test_calendar_only_rows_do_not_create_sprint_files(data_dir: Path):
    data = read_workbook(exported(data_dir), "demo")
    recorded = {s.id for s in Repository(data_dir).load("demo").sprints}
    assert {s.id for s in data.sprints} == recorded


def test_foreign_workbook_is_refused(tmp_path: Path):
    wb = openpyxl.Workbook()
    path = tmp_path / "x.xlsx"
    wb.save(path)
    with pytest.raises(DataError, match="Blatt"):
        read_workbook(path, "demo")


def test_errors_name_sheet_and_cell(data_dir: Path):
    def edit(wb: openpyxl.Workbook) -> None:
        wb[SHEET_FORECAST]["E4"].value = "viel"

    with pytest.raises(DataError, match=r"Forecast!E4"):
        read_workbook(edited(exported(data_dir), edit), "demo")


def test_unknown_absence_state_is_reported(data_dir: Path):
    def edit(wb: openpyxl.Workbook) -> None:
        wb[SHEET_SPRINTS]["B2"].value = "vielleicht"

    with pytest.raises(DataError, match=r"Sprintdaten!B2"):
        read_workbook(edited(exported(data_dir), edit), "demo")


def test_existing_sprint_files_missing_in_the_workbook_stay_untouched(
    data_dir: Path, tmp_path: Path
):
    content = exported(data_dir)
    copy = tmp_path / "kopie"
    shutil.copytree(data_dir, copy)
    extra = copy / "demo" / "sprints" / "2099.01.yaml"
    extra.write_text('id: "2099.01"\nstart: 2099-01-01\nend: 2099-01-15\n', encoding="utf-8")
    plan = plan_import(Repository(copy), read_workbook(content, "demo"))
    assert plan.untouched == ["sprints/2099.01.yaml"]


def test_roundtrip_keeps_every_field_of_a_fully_filled_team(data_dir: Path, tmp_path: Path):
    """Alle Felder der Sprintdatei, mehrere Mitgliedschaften, Produktwerte mit Produktion."""
    from datetime import datetime

    from sprintforecast.model import (
        AbsenceState,
        Membership,
        Planning,
        ProductValues,
        Prognosis,
    )

    repo = Repository(data_dir)
    data = repo.load("demo")
    data.team.features.products = True
    data.team.features.production = True
    repo.save_team(data.team)
    person = data.people[0]
    person.production_access = True
    person.country, person.region, person.workweek = "AT", "9", "mon,tue,wed,thu"
    person.memberships.append(Membership(start=date(2030, 1, 1), end=None, fte=0.5))
    repo.save_people("demo", data.people)
    sprint = next(s for s in data.sprints if s.velocity is not None)
    other = data.people[1].id
    sprint.absence_state = AbsenceState.CONFIRMED
    sprint.absences = {person.id: 2.5}
    sprint.expected_absences = {other: 1.0}
    sprint.planning = Planning(carryover=3.5, backlog=4.0, corrections=[1.0, 0.5])
    sprint.forecast_plan, sprint.note = 17.4, "Notiz mit Ümlaut | und Strich"
    sprint.not_done, sprint.additional_done = 1.5, 2.0
    sprint.production_planned, sprint.production_done = 3.0, 2.0
    ids = [p.id for p in data.products[:2]] or ["kwg"]
    sprint.products = {pid: ProductValues(1.0, 2.0, 3.0, 0.5, 0.25) for pid in ids}
    sprint.prognoses = [
        Prognosis(
            at=datetime(2026, 10, 16, 14, 43, 5),
            comment="Daily",
            forecast_ist=15.7,
            not_done=1.0,
            additional_done=0.5,
            expected_done=15.2,
            target=sprint.id,
            plan=22.4,
            preplanned={ids[0]: 2.0},
        )
    ]
    repo.save_sprint("demo", sprint)
    content = build_workbook(build_forecast(repo.load("demo"), TODAY))
    target = Repository(tmp_path / "neu")
    plan = plan_import(target, read_workbook(content, "demo"))
    apply_import(target, plan)
    original, restored = repo.load("demo"), target.load("demo")
    assert restored.sprints == original.sprints
    assert restored.people == original.people
    assert restored.team == original.team
    assert plan_import(target, read_workbook(content, "demo")).changes == []


def test_command_previews_then_applies(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from sprintforecast.cli import app
    from sprintforecast.storage import DATA_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    sprint = next(s for s in Repository(data_dir).load("demo").sprints if s.velocity is not None)

    def edit(wb: openpyxl.Workbook) -> None:
        for row in wb[SHEET_FORECAST].iter_rows(min_row=4):
            if row[0].value == sprint.id:
                row[4].value = sprint.velocity + 1

    file = tmp_path / "in.xlsx"
    file.write_bytes(edited(exported(data_dir), edit))
    runner = CliRunner()
    preview = runner.invoke(app, ["excel-import", "demo", str(file)])
    assert preview.exit_code == 0, preview.output
    assert "velocity" in preview.output
    assert Repository(data_dir).load("demo").sprint(sprint.id).velocity == sprint.velocity
    done = runner.invoke(app, ["excel-import", "demo", str(file), "--uebernehmen"])
    assert done.exit_code == 0, done.output
    assert Repository(data_dir).load("demo").sprint(sprint.id).velocity == sprint.velocity + 1
