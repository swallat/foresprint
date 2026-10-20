# SPDX-License-Identifier: EUPL-1.2
"""Import of the Excel output: lossless round trip, preview of the changes, error messages."""

import dataclasses
import io
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("xlsxwriter")

import openpyxl

from sprintforecast.excel import LEGACY_SHEETS, SHEET_FORECAST, SHEET_SPRINTS, build_workbook
from sprintforecast.excel_import import (
    apply_import,
    plan_import,
    read_workbook,
    read_workbook_keyed,
)
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


def test_workbooks_with_the_german_sheet_names_of_older_versions_are_read(data_dir: Path):
    def rename(wb):
        for old, new in LEGACY_SHEETS.items():
            if new in wb.sheetnames:
                wb[new].title = old

    repo = Repository(data_dir)
    plan = plan_import(repo, read_workbook(edited(exported(data_dir), rename), "demo"))
    assert plan.changes == [] and plan.files == []


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
    assert restored.sprints == original.sprints  # including absences, product values, forecasts
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

    with pytest.raises(DataError, match=r"Sprint data!B2"):
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
    """All fields of the sprint file, several memberships, product values with production."""
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
    person.memberships[-1].end = person.memberships[-1].end or date(2029, 12, 31)
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
    done = runner.invoke(app, ["excel-import", "demo", str(file), "--apply"])
    assert done.exit_code == 0, done.output
    assert Repository(data_dir).load("demo").sprint(sprint.id).velocity == sprint.velocity + 1


# --- Security and input validation (Codex findings on #86) ---------------------------------


def setting_cell(wb: openpyxl.Workbook, path: str):
    """The value cell (column B) of the setting ``path`` on the Settings sheet."""
    ws = wb["Settings"]
    for row in ws.iter_rows(min_row=3):
        if row[2].value == path:
            return row[1]
    raise AssertionError(path)


@pytest.mark.parametrize("key", ["../outside", "..", "a/b", "a\\b", "/abs", "C:evil", ".", ""])
def test_unsafe_team_keys_are_refused_before_any_path_is_resolved(data_dir: Path, key: str):
    from sprintforecast.excel_import import check_team_key

    repo = Repository(data_dir)
    with pytest.raises(DataError):
        check_team_key(repo, key)


def test_a_new_team_key_must_be_valid_and_not_clash(data_dir: Path):
    from sprintforecast.excel_import import check_team_key

    repo = Repository(data_dir)
    check_team_key(repo, "demo")  # existing team: fine
    check_team_key(repo, "neues-team")
    if not repo.exists("DEMO"):  # Linux/macOS are case-sensitive: a different folder
        with pytest.raises(DataError):
            check_team_key(repo, "DEMO")
    with pytest.raises(DataError):
        check_team_key(repo, "con")  # reserved for devices on Windows
    with pytest.raises(DataError):
        check_team_key(repo, "Großes Team")


def test_a_traversing_team_key_writes_nothing_outside_the_data_folder(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from sprintforecast.cli import app
    from sprintforecast.storage import DATA_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    file = tmp_path / "in.xlsx"
    file.write_bytes(exported(data_dir))
    outside = data_dir.parent / "outside"
    result = CliRunner().invoke(app, ["excel-import", "../outside", str(file), "--apply"])
    assert result.exit_code != 0
    assert not outside.exists()


def test_the_preview_refuses_an_unsafe_key_without_reading_outside(data_dir: Path):
    import dataclasses

    repo = Repository(data_dir)
    data = read_workbook(exported(data_dir), "demo")
    evil = dataclasses.replace(data, team=dataclasses.replace(data.team, key="../outside"))
    with pytest.raises(DataError, match="Ordnername"):
        plan_import(repo, evil, TODAY)


def test_apply_refuses_a_hand_built_plan_with_an_unsafe_key(data_dir: Path):
    import dataclasses

    from sprintforecast.excel_import import ImportPlan

    repo = Repository(data_dir)
    data = read_workbook(exported(data_dir), "demo")
    evil = dataclasses.replace(data, team=dataclasses.replace(data.team, key="../outside"))
    with pytest.raises(DataError):
        apply_import(repo, ImportPlan(data=evil, files=["team.yaml"]))
    assert not (data_dir.parent / "outside").exists()


@pytest.mark.parametrize(
    "bad",
    [
        "../../../victim",
        "..",
        "a/b",
        "a\\b",
        ".versteckt",
        "x" * 81,
        "nul",
        "COM1",
        "nul.1",
        "a:b",
        "C:evil",
        "a:stream",
        "ende.",
        "zeile\numbruch",
        "tab\tulator",
    ],
)
def test_sprint_ids_from_cells_cannot_become_paths(data_dir: Path, bad: str):
    def edit(wb: openpyxl.Workbook) -> None:
        wb[SHEET_FORECAST]["A4"].value = bad

    with pytest.raises(DataError, match=r"Forecast!A4"):
        read_workbook(edited(exported(data_dir), edit), "demo")


def test_invalid_settings_are_refused_before_anything_is_written(data_dir: Path):
    repo = Repository(data_dir)

    def edit(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "forecast.window").value = 0

    data = read_workbook(edited(exported(data_dir), edit), "demo")
    with pytest.raises(DataError, match="ungültige Einstellungen"):
        plan_import(repo, data, TODAY)
    assert Repository(data_dir).load("demo").team.forecast.window != 0


@pytest.mark.parametrize("bad", ["NaN", "nan", "inf", "-inf", "1e999", "Infinity"])
def test_non_finite_numbers_are_refused_with_the_cell(data_dir: Path, bad: str):
    def edit(wb: openpyxl.Workbook) -> None:
        wb[SHEET_FORECAST]["E4"].value = bad

    with pytest.raises(DataError, match=r"Forecast!E4"):
        read_workbook(edited(exported(data_dir), edit), "demo")


def test_setting_values_need_their_type(data_dir: Path):
    def not_whole(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "forecast.window").value = 5.5

    def maybe(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "features.production").value = "vielleicht"

    def unknown(wb: openpyxl.Workbook) -> None:
        wb["Settings"]["A30"].value = "x"
        wb["Settings"]["B30"].value = 1
        wb["Settings"]["C30"].value = "forecast.unbekannt"

    with pytest.raises(DataError, match=r"Settings!B"):
        read_workbook(edited(exported(data_dir), not_whole), "demo")
    with pytest.raises(DataError, match=r"Settings!B"):
        read_workbook(edited(exported(data_dir), maybe), "demo")
    with pytest.raises(DataError, match=r"Settings!C30"):
        read_workbook(edited(exported(data_dir), unknown), "demo")


def test_yes_no_words_work_for_switches_and_text_off_is_not_true(data_dir: Path):
    def off(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "features.production").value = "aus"

    def on(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "features.production").value = "Ja"

    assert not read_workbook(edited(exported(data_dir), off), "demo").team.features.production
    assert read_workbook(edited(exported(data_dir), on), "demo").team.features.production


# --- Findings of the independent hardening review -------------------------------------------


def cell_sheet():
    from sprintforecast.excel_import import _Sheet

    return _Sheet(openpyxl.Workbook().active)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 10**400, 1e12, True])
def test_number_cells_refuse_non_finite_huge_and_boolean_values(value):
    with pytest.raises(DataError):
        cell_sheet().number(4, (value,), 0)


def test_number_cells_accept_ordinary_values():
    sheet = cell_sheet()
    assert sheet.number(4, (5,), 0) == 5.0
    assert sheet.number(4, ("2,5",), 0) == 2.5
    assert sheet.number(4, (None,), 0) is None


@pytest.mark.parametrize("year", [1, 1800, 2200, 9999])
def test_dates_outside_a_plausible_range_are_refused(year: int):
    from datetime import datetime

    with pytest.raises(DataError, match="außerhalb"):
        cell_sheet().day(4, (datetime(year, 1, 1),), 0)


def test_first_sprint_id_setting_cannot_become_a_path(data_dir: Path):
    outside = data_dir.parent / "outside"

    def edit(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, "sprint.first.id").value = "../../../outside/evil"
        setting_cell(wb, "sprint.first.start").value = datetime(2026, 10, 12)

    with pytest.raises(DataError, match=r"nicht zulässig"):
        read_workbook(edited(exported(data_dir), edit), "demo")
    assert not outside.exists()


def test_the_settings_form_does_not_accept_an_id_the_loader_would_reject():
    """What is rejected on load (unsafe first sprint ID) must not be saveable."""
    from sprintforecast.settings import SETTINGS

    setting = next(s for s in SETTINGS if s.key == "sprint.first_id")
    for bad in ("../x", "a/b", "ende."):
        with pytest.raises(ValueError, match="Dateiname"):
            setting.parse(bad)
    assert setting.parse("2026.20") == "2026.20"
    assert setting.parse("") is None  # optional


def test_the_repository_refuses_unsafe_sprint_ids_as_paths(data_dir: Path):
    import sys

    repo = Repository(data_dir)
    # A bad path on every system: separators and a dot at the edge. Colon and device names only
    # on Windows (ordinary characters elsewhere; existing data stays usable).
    bad_ids = ["../x", "a/b", "..", "ende."]
    if sys.platform == "win32":
        bad_ids += ["nul", "a:b", "a\\b"]
    for bad in bad_ids:
        with pytest.raises(DataError, match="nicht zulässig"):
            repo.sprint_path("demo", bad)
    assert repo.sprint_path("demo", "2026.22b").name == "2026.22b.yaml"
    if sys.platform != "win32":  # existing exotic IDs remain possible there
        assert repo.sprint_path("demo", "[red]\\").name
        assert repo.sprint_path("demo", "a:b").name == "a:b.yaml"


def test_a_traversal_id_cannot_overwrite_an_existing_file_outside(data_dir: Path):
    """A real target outside the data folder stays unchanged (not just not created)."""
    import dataclasses

    from sprintforecast.excel_import import ImportPlan
    from sprintforecast.model import Sprint

    target = data_dir.parent / "victim.yaml"
    target.write_text("original: 1\n", encoding="utf-8")
    repo = Repository(data_dir)
    data = read_workbook(exported(data_dir), "demo")
    evil = Sprint(id="../../victim", start=date(2026, 1, 1), end=date(2026, 1, 15))
    bad = dataclasses.replace(data, sprints=[*data.sprints, evil])
    with pytest.raises(DataError):
        plan_import(repo, bad, TODAY)
    with pytest.raises(DataError):
        apply_import(repo, ImportPlan(data=bad, files=["sprints/../../victim.yaml"]))
    assert target.read_text(encoding="utf-8") == "original: 1\n"


def test_spaces_umlauts_and_long_ids_of_existing_sprints_still_round_trip(
    data_dir: Path, tmp_path: Path
):
    from sprintforecast.storage import file_name_problem

    for ok in ("2026.22b", "Sprint Übung 1", "2026 Q3", "x" * 80, "-1", "_a"):
        assert file_name_problem(ok) is None, ok


def test_free_text_below_the_sprints_is_ignored_not_rejected(data_dir: Path):
    def edit(wb: openpyxl.Workbook) -> None:
        ws = wb[SHEET_FORECAST]
        ws.cell(row=ws.max_row + 2, column=1, value="Summe laut Controlling / Hinweis")

    repo = Repository(data_dir)
    data = read_workbook(edited(exported(data_dir), edit), "demo")
    assert plan_import(repo, data, TODAY).changes == []


def test_duplicate_sprint_ids_are_refused_also_ignoring_case(data_dir: Path):
    def same(wb: openpyxl.Workbook) -> None:
        ws = wb[SHEET_FORECAST]
        ws["A5"].value = ws["A4"].value

    def case(wb: openpyxl.Workbook) -> None:
        ws = wb[SHEET_FORECAST]
        ws["A5"].value = str(ws["A4"].value).upper() + "x"
        ws["A6"].value = str(ws["A4"].value).upper() + "X"

    with pytest.raises(DataError, match="doppelt"):
        read_workbook(edited(exported(data_dir), same), "demo")
    with pytest.raises(DataError, match="doppelt"):
        read_workbook(edited(exported(data_dir), case), "demo")


@pytest.mark.parametrize("bad", ["prod=inf", "prod=nan", "prod=1e999", "prod=1e12", "prod"])
def test_prognoses_refuse_non_finite_values(data_dir: Path, bad: str):
    from datetime import datetime

    sprint_id = next(s.id for s in Repository(data_dir).load("demo").sprints)

    def edit(wb: openpyxl.Workbook) -> None:
        wb["Prognoses"].append([sprint_id, datetime(2026, 10, 1, 9), None] + [None] * 6 + [bad])

    with pytest.raises(DataError, match=r"Prognoses!J"):
        read_workbook(edited(exported(data_dir), edit), "demo")


def test_prognoses_are_sorted_oldest_first(data_dir: Path):
    from datetime import datetime

    sprint_id = next(s.id for s in Repository(data_dir).load("demo").sprints)

    def edit(wb: openpyxl.Workbook) -> None:
        ws = wb["Prognoses"]
        ws.append([sprint_id, datetime(2026, 10, 3, 9), "später"] + [None] * 7)
        ws.append([sprint_id, datetime(2026, 10, 1, 9), "früher"] + [None] * 7)

    data = read_workbook(edited(exported(data_dir), edit), "demo")
    sprint = next(s for s in data.sprints if s.id == sprint_id)
    assert [p.comment for p in sprint.prognoses][-2:] == ["früher", "später"]
    assert [p.at for p in sprint.prognoses] == sorted(p.at for p in sprint.prognoses)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("forecast.rounding", 400),
        ("forecast.horizon", 100000),
        ("forecast.reference_capacity", 0),
        ("forecast.window", 0),
        ("sprint.length_days", 0),
        ("sprint.length_days", 5000),
        ("capacity.overhead_share", 5),
    ],
)
def test_settings_outside_their_ranges_are_refused_before_writing(
    data_dir: Path, path: str, value: float
):
    def edit(wb: openpyxl.Workbook) -> None:
        setting_cell(wb, path).value = value

    repo = Repository(data_dir)
    before = (data_dir / "demo" / "team.yaml").read_bytes()
    data = read_workbook(edited(exported(data_dir), edit), "demo")
    with pytest.raises(DataError):
        plan_import(repo, data, TODAY)
    assert (data_dir / "demo" / "team.yaml").read_bytes() == before


def test_existing_sprint_files_missing_in_the_workbook_are_part_of_the_check(
    data_dir: Path,
):
    """An existing sprint file that is missing from the workbook is checked too (overall state)."""
    repo = Repository(data_dir)
    data = read_workbook(exported(data_dir), "demo")
    broken = data_dir / "demo" / "sprints" / "2026.50.yaml"
    broken.write_text(
        'id: "2026.50"\nstart: 2026-12-14\nend: 2026-12-28\nvelocity: -5\n', encoding="utf-8"
    )
    from sprintforecast.validate import Level, check_team

    union = repo.load("demo")
    expected_error = any(i.level is Level.ERROR for i in check_team(union, TODAY))
    if expected_error:  # only if check_team actually treats the file as an error
        with pytest.raises(DataError):
            plan_import(repo, data, TODAY)


def test_a_workbook_id_that_differs_from_an_omitted_sprint_file_only_by_case_is_refused(
    data_dir: Path,
):
    """Otherwise save_sprint would overwrite the existing file on Windows/macOS (same file)."""
    import dataclasses

    from sprintforecast.model import Sprint

    repo = Repository(data_dir)
    # before the file Foo: the workbook does not know it
    data = read_workbook(exported(data_dir), "demo")
    repo.save_sprint("demo", Sprint(id="Foo", start=date(2099, 1, 1), end=date(2099, 1, 15)))
    new = Sprint(id="foo", start=date(2099, 2, 1), end=date(2099, 2, 15))
    colliding = dataclasses.replace(data, sprints=[*data.sprints, new])
    with pytest.raises(DataError, match="Groß- und Kleinschreibung"):
        plan_import(repo, colliding, TODAY)
    # the same ID with the same spelling, however, is a normal replacement
    same = Sprint(id="Foo", start=date(2099, 1, 1), end=date(2099, 1, 15))
    plan_import(repo, dataclasses.replace(data, sprints=[*data.sprints, same]), TODAY)


def test_a_symlinked_team_folder_is_accepted(data_dir: Path, tmp_path: Path):
    from sprintforecast.excel_import import check_team_key

    real = tmp_path / "echt"
    shutil.copytree(data_dir / "demo", real)
    root = tmp_path / "wurzel"
    root.mkdir()
    try:
        (root / "team-a").symlink_to(real, target_is_directory=True)
    except OSError as e:
        if getattr(e, "winerror", None) != 1314:
            raise
        pytest.skip("Kein Recht für symbolische Verknüpfungen")
    check_team_key(Repository(root), "team-a")


def test_a_clashing_team_key_is_refused_regardless_of_the_file_system(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    from sprintforecast.excel_import import check_team_key

    # An older team with capital letters in the folder name; a new "alpha" would share the
    # same folder on Windows and macOS.
    shutil.copytree(data_dir / "demo", data_dir / "Alpha")
    repo = Repository(data_dir)
    real_exists = repo.exists
    monkeypatch.setattr(repo, "exists", lambda key: False if key == "alpha" else real_exists(key))
    with pytest.raises(DataError, match="existiert bereits"):
        check_team_key(repo, "alpha")


def test_the_person_switch_needs_yes_or_no(data_dir: Path):
    def off(wb: openpyxl.Workbook) -> None:
        wb["People"]["F2"].value = "nein"

    def maybe(wb: openpyxl.Workbook) -> None:
        wb["People"]["F2"].value = "vielleicht"

    assert not read_workbook(edited(exported(data_dir), off), "demo").people[0].production_access
    with pytest.raises(DataError, match=r"People!F2"):
        read_workbook(edited(exported(data_dir), maybe), "demo")


def test_the_command_checks_against_the_reference_day(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    import sprintforecast.excel_import as module
    from sprintforecast.cli import app
    from sprintforecast.storage import DATA_ENV

    seen: list[object] = []
    real = module.plan_import

    def spy(repo, data, today=None):
        seen.append(today)
        return real(repo, data, today)

    monkeypatch.setattr(module, "plan_import", spy)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    file = tmp_path / "in.xlsx"
    file.write_bytes(exported(data_dir))
    result = CliRunner().invoke(app, ["--as-of", "2026-10-15", "excel-import", "demo", str(file)])
    assert result.exit_code == 0, result.output
    assert seen == [date(2026, 10, 15)]


def test_workbook_carries_its_team_key(data_dir: Path):
    _, file_team = read_workbook_keyed(exported(data_dir), "demo")
    assert file_team == "demo"


def test_workbook_of_another_team_is_refused(data_dir: Path):
    with pytest.raises(DataError, match=r"Team 'demo'.*Team 'other'"):
        read_workbook(exported(data_dir), "other")


def test_workbook_without_team_key_is_still_read(data_dir: Path):
    def drop(wb) -> None:
        props = wb.custom_doc_props.props
        wb.custom_doc_props.props[:] = [p for p in props if p.name != "sprintforecast-team"]

    data, file_team = read_workbook_keyed(edited(exported(data_dir), drop), "other")
    assert file_team is None
    assert data.team.key == "other"


@pytest.mark.skipif(sys.platform == "win32", reason="a:b is not a file name on Windows")
def test_export_warns_about_a_sprint_id_the_import_refuses(data_dir: Path):
    from sprintforecast.excel import import_unsafe_sprint_ids

    data = Repository(data_dir).load("demo")
    assert import_unsafe_sprint_ids(data) == []
    odd = dataclasses.replace(data, sprints=[dataclasses.replace(data.sprints[0], id="a:b")])
    (warning,) = import_unsafe_sprint_ids(odd)
    assert "'a:b'" in warning
    with pytest.raises(
        DataError, match=r"Sprint ID 'a:b' is not allowed|Sprint-ID 'a:b' ist nicht"
    ):
        read_workbook(build_workbook(build_forecast(odd, TODAY)), "demo")


def test_export_warns_about_case_only_duplicates_and_an_unsafe_first_id(data_dir: Path):
    from sprintforecast.excel import import_unsafe_sprint_ids

    data = Repository(data_dir).load("demo")
    first = data.sprints[0]
    dup = dataclasses.replace(
        data,
        sprints=[
            dataclasses.replace(first, id="Foo"),
            dataclasses.replace(first, id="foo"),
        ],
    )
    (warning,) = import_unsafe_sprint_ids(dup)
    assert "'foo'" in warning
    team = dataclasses.replace(
        data.team, sprint=dataclasses.replace(data.team.sprint, first_id="a/b")
    )
    (warning,) = import_unsafe_sprint_ids(dataclasses.replace(data, team=team))
    assert "'a/b'" in warning


def test_excel_command_prints_the_import_warning_to_stderr(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from sprintforecast.cli import app
    from sprintforecast.storage import DATA_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    sprints = data_dir / "demo" / "sprints"
    src = sorted(sprints.glob("*.yaml"))[0]
    text = src.read_text(encoding="utf-8")
    sid = src.stem
    for name in ("Zed", "zed"):
        (sprints / f"{name}.yaml").write_text(text.replace(sid, name), encoding="utf-8")
    out = tmp_path / "x.xlsx"
    result = CliRunner().invoke(app, ["excel", "demo", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "'zed'" in result.stderr
    assert out.exists()
