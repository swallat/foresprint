# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from foresprint.forecast import build_forecast
from foresprint.model import AbsenceState, ProductValues, Sprint
from foresprint.storage import Repository
from foresprint.web.logic import (
    absence_matrix,
    absence_sprints,
    apply_product_values,
    board_steps_done,
    edit_absences,
    parse_numbers,
    people_from_table,
    people_table,
    sprints_to_save,
)

TODAY = date(2026, 10, 15)


def test_absence_matrix_roundtrip(data_dir: Path):
    data = Repository(data_dir).load("demo")
    sprints = absence_sprints(data, build_forecast(data, TODAY), 3)
    assert [s.id for s in sprints] == ["2026.21", "2026.22", "2026.23"]
    rows = absence_matrix(data.people, sprints)
    assert [r["id"] for r in rows] == ["anna", "ben", "cem", "dana"]  # emil left
    assert rows[2]["2026.22"] == 5  # cem
    edited = edit_absences(data.people, sprints, rows)
    assert [s.absences for s in edited] == [s.absences for s in sprints]
    # Nothing changed and nothing confirmed: even 2026.23 (without a file) is not created
    assert sprints_to_save(data, sprints, edited) == []
    # "Nobody is absent" confirms explicitly and creates the file
    confirmed = edit_absences(data.people, sprints, rows, confirmed={"2026.23"})
    assert [s.id for s in sprints_to_save(data, sprints, confirmed)] == ["2026.23"]
    assert confirmed[2].absence_state is AbsenceState.CONFIRMED
    # Revoke confirmation: 2026.21 has entries (stays confirmed), 2026.22 likewise
    assert [s.absences_confirmed for s in confirmed[:2]] == [True, True]

    rows[0]["2026.23"] = 2.5  # anna in the sprint without a file
    rows[2]["2026.22"] = None  # cem: empty = no absences
    edited = edit_absences(data.people, sprints, rows)
    to_save = {s.id: s for s in sprints_to_save(data, sprints, edited)}
    assert set(to_save) == {"2026.22", "2026.23"}
    assert to_save["2026.23"].absences == {"anna": 2.5}
    assert "cem" not in to_save["2026.22"].absences


def test_people_table_roundtrip(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=True)
    assert hidden == []
    assert len(rows) == 6  # Ben has two periods
    result = people_from_table(rows, people, hidden)
    assert (result.errors, result.deleted) == ([], [])
    assert result.people == people


def test_former_people_hidden_and_preserved(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    assert [p.name for p in hidden] == ["Emil"]  # until 31.07.2026
    assert "Emil" not in {r["Name"] for r in rows}
    result = people_from_table(rows, people, hidden)
    assert result.deleted == []
    assert result.people == people


def test_new_rows_get_ids_and_join_existing_person(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    anna = next(r for r in rows if r["Name"] == "Anna")
    anna["until"] = date(2026, 10, 31)
    rows += [
        # FTE change: new row, same name, no ID
        {"_id": None, "Name": "Anna", "State": "(Team)", "from": "2026-11-01", "until": None,
         "FTE": 0.5},
        {"_id": float("nan"), "Name": "Jörg Müller", "State": "BY",
         "from": pd.Timestamp("2026-11-01"), "until": pd.NaT, "FTE": float("nan")},
    ]  # fmt: skip
    result = people_from_table(rows, people, hidden)
    assert result.errors == []
    by_name = {p.name: p for p in result.people}
    assert [m.fte for m in by_name["Anna"].memberships] == [1.0, 0.5]
    assert by_name["Anna"].id == "anna"
    joerg = by_name["Jörg Müller"]
    assert (joerg.id, joerg.region, joerg.memberships[0].fte) == ("joerg-mueller", "BY", 1.0)


def test_deleted_rows_are_reported(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    rows = [r for r in rows if r["Name"] != "Dana"]
    rows.remove(next(r for r in rows if r["Name"] == "Ben"))
    result = people_from_table(rows, people, hidden)
    assert result.deleted == ["Ben (Zeitraum)", "Dana"]


def test_people_table_errors(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    ben = [r for r in rows if r["Name"] == "Ben"]
    ben[1]["State"] = "HE"  # second period with a different German state
    rows.append({"_id": None, "Name": "", "State": None, "from": None, "until": None, "FTE": 1})
    rows.append({"_id": None, "Name": "Neu", "State": None, "from": None, "until": None})
    errors = people_from_table(rows, people, hidden).errors
    assert any("unterschiedliche Namen oder Bundesländer" in e for e in errors)
    assert any("Name fehlt" in e for e in errors)
    assert any("(Neu): 'ab' fehlt" in e for e in errors)


def test_parse_numbers():
    assert parse_numbers("4,25 4.5; 1") == [4.25, 4.5, 1.0]
    with pytest.raises(ValueError):
        parse_numbers("4,25 x")


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999", "1 nan"])
def test_parse_numbers_rejects_non_finite(raw: str):
    with pytest.raises(ValueError, match="endliche Zahl"):
        parse_numbers(raw)


def _calendar(data_dir):
    from datetime import date

    from foresprint.forecast import build_forecast
    from foresprint.storage import Repository
    from foresprint.web.logic import absence_sprints, calendar_table

    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, date(2026, 10, 15))
    return data, fc, absence_sprints, calendar_table


def test_calendar_shifts_persisted_sprints_outside_window(data_dir):
    from datetime import date

    from foresprint.validate import Level, check_team
    from foresprint.web.logic import apply_calendar, calendar_to_save, with_sprints

    data, fc, absence_sprints, calendar_table = _calendar(data_dir)
    shown = absence_sprints(data, fc, 1)  # only 2026.21; 2026.22 is saved behind it
    rows = calendar_table(data, shown, fc.today)
    rows[0]["Last day"] = date(2026, 11, 3)
    after, errors = apply_calendar(data, shown, rows)
    assert not errors
    to_save = calendar_to_save(data, shown, after, create_missing=False)
    s22 = next(s for s in to_save if s.id == "2026.22")
    assert s22.start == date(2026, 11, 4)
    issues = check_team(with_sprints(data, to_save), fc.today)
    assert not [i for i in issues if i.level is Level.ERROR]


def test_calendar_rejects_id_collision(data_dir):
    from datetime import date

    from foresprint.storage import Repository
    from foresprint.web.logic import apply_calendar

    data, fc, absence_sprints, calendar_table = _calendar(data_dir)
    repo = Repository(data_dir)
    # saved 2026.25 and 2027.1, generated 2026.26 in between
    for s in absence_sprints(data, fc, 7):
        if s.id in ("2026.25", "2027.1"):
            repo.save_sprint("demo", s)
    data, fc, absence_sprints, calendar_table = _calendar(data_dir)
    shown = absence_sprints(data, fc, 7)
    assert [s.id for s in shown][-3:] == ["2026.25", "2026.26", "2027.1"]
    rows = calendar_table(data, shown, fc.today)
    rows[-3]["Last day"] = date(2027, 1, 12)
    _, errors = apply_calendar(data, shown, rows)
    assert any("2027.1" in e and "doppelt" in e for e in errors)


def test_fte_zero_is_allowed_and_out_of_range_is_reported(data_dir: Path):
    from foresprint.capacity import sprint_capacity
    from foresprint.validate import check_team

    repo = Repository(data_dir)
    data = repo.load("demo")
    rows, hidden = people_table(data.people, TODAY, show_former=True)
    before = sprint_capacity(data.team, data.people, data.sprint("2026.22")).capacity
    rows[0]["FTE"] = 0.0
    result = people_from_table(rows, data.people, hidden)
    assert result.errors == []
    assert result.people[0].memberships[-1].fte == 0.0
    data.people = result.people
    assert [i for i in check_team(data, TODAY) if i.level.value == "Error"] == []
    assert sprint_capacity(data.team, data.people, data.sprint("2026.22")).capacity < before
    for bad in (1.5, -0.5, "abc"):
        rows[0]["FTE"] = bad
        assert people_from_table(rows, data.people, hidden).errors


def test_whatif_velocity_changes_next_plan(data_dir: Path):
    from foresprint.forecast import build_forecast
    from foresprint.web.logic import open_velocity_sprints, whatif_forecast

    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    open_ = open_velocity_sprints(fc)
    assert open_, "der laufende Sprint hat noch keine Velocity"
    current = open_[-1].id
    low = whatif_forecast(fc, {current: 4.0})
    high = whatif_forecast(fc, {current: 14.0})
    nxt = fc.upcoming()[-1].sprint.id
    assert high.entry(nxt).result.plan > low.entry(nxt).result.plan
    assert fc.entry(current).sprint.velocity is None  # nothing changed


def test_reset_future_absences_to_unknown(data_dir: Path):
    from foresprint.forecast import build_forecast
    from foresprint.model import Sprint
    from foresprint.web.logic import resettable_sprints

    repo = Repository(data_dir)
    data = repo.load("demo")
    assert resettable_sprints(data, TODAY) == []
    last = max(data.sprints, key=lambda s: s.start)
    nxt = build_forecast(data, TODAY).entries[-1].sprint
    assert nxt.start > last.start
    repo.save_sprint("demo", Sprint(id=nxt.id, start=nxt.start, end=nxt.end))
    data = repo.load("demo")
    assert [s.id for s in resettable_sprints(data, TODAY)] == [nxt.id]
    repo.delete_sprint("demo", nxt.id)
    assert resettable_sprints(repo.load("demo"), TODAY) == []
    assert repo.load("demo").sprint(nxt.id) is None


def test_prognosis_roundtrip_and_validation(data_dir: Path):
    from datetime import datetime

    from foresprint.validate import check_team
    from foresprint.web.logic import Assumption, record_prognoses

    repo = Repository(data_dir)
    data = repo.load("demo")
    target = data.sprint("2026.22") or build_target(data)
    a = Assumption(10.0, not_done=2.0, additional_done=0.5)
    assert a.expected == 8.5
    sprints = record_prognoses(
        data, target, {"2026.21": a}, 9.9, " Daily ", datetime(2026, 10, 16, 9, 30, 12, 7)
    )
    assert {s.id for s in sprints} == {"2026.22", "2026.21"}
    for s in sprints:
        repo.save_sprint("demo", s)
    p = repo.load("demo").sprint("2026.21").prognoses[-1]
    assert (p.comment, p.expected_done, p.plan, p.target) == ("Daily", 8.5, 9.9, "2026.22")
    assert p.at == datetime(2026, 10, 16, 9, 30, 12)
    # Review values that do not match the velocity trigger a warning
    s = repo.load("demo")
    sprint = s.sprint("2026.21")
    sprint.velocity, sprint.not_done, sprint.additional_done = 9.0, 2.0, 0.0
    messages = [i.message for i in check_team(s, TODAY)]
    assert any("ergibt 8" in m for m in messages)
    sprint.not_done = -1.0
    assert any(i.level.value == "Error" for i in check_team(s, TODAY))


def build_target(data):
    from foresprint.forecast import find_sprint

    return find_sprint(data, "2026.22")


def test_default_commitment_falls_back_to_previous_sprint(data_dir: Path):
    from foresprint.forecast import build_forecast
    from foresprint.web.logic import default_sprint_commitment

    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    current = fc.current.sprint
    assert default_sprint_commitment(fc, current) == current.commitment
    own = current.commitment
    current.commitment = None
    earlier = [e.sprint for e in fc.entries if e.sprint.start < current.start]
    expected = next(s.commitment for s in reversed(earlier) if s.commitment is not None)
    assert default_sprint_commitment(fc, current) == expected
    assert own is not None


def test_absence_sprints_can_include_past_sprints(data_dir: Path):
    from foresprint.forecast import build_forecast
    from foresprint.web.logic import absence_sprints

    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, TODAY)
    plain = absence_sprints(data, fc, 3)
    with_past = absence_sprints(data, fc, 3, past=2)
    assert [s.id for s in with_past[2:]] == [s.id for s in plain]
    assert all(s.end <= TODAY for s in with_past[:2])
    assert len(with_past) == len(plain) + 2


def test_saving_preplanning_does_not_change_capacity_source(data_dir: Path):
    from foresprint.engine import CapacitySource
    from foresprint.forecast import build_forecast
    from foresprint.model import ProductValues
    from foresprint.web.logic import with_sprints

    data = Repository(data_dir).load("demo")
    before = build_forecast(data, TODAY)
    target = next(e for e in before.upcoming() if not e.recorded)
    assert target.result.plan_capacity_source is CapacitySource.ESTIMATED

    sprint = target.sprint
    sprint.products["webshop"] = ProductValues(preplanned=3.0)  # pre-planning only, no absences
    after = build_forecast(with_sprints(data, [sprint]), TODAY).entry(sprint.id)
    assert after.result.plan_capacity_source is CapacitySource.ESTIMATED
    assert after.result.plan == target.result.plan

    sprint.absences = {"anna": 2.0}  # entered absences confirm the capacity
    confirmed = build_forecast(with_sprints(data, [sprint]), TODAY).entry(sprint.id)
    assert confirmed.result.plan_capacity_source is CapacitySource.PEOPLE


def test_unchanged_preview_keeps_forecast_of_unsaved_sprint(data_dir: Path):
    from foresprint.forecast import build_forecast
    from foresprint.web.ui import _preview_forecast

    data = Repository(data_dir).load("demo")
    fc = build_forecast(data, TODAY)
    target = next(e for e in fc.upcoming() if not e.recorded)
    base = target.sprint
    after = type(base)(id=base.id, start=base.start, end=base.end)
    assert _preview_forecast(data, fc, base, after) is fc


def test_empty_sprint_file_does_not_confirm_absences(data_dir: Path):
    from foresprint.engine import CapacitySource
    from foresprint.forecast import build_forecast
    from foresprint.model import Sprint
    from foresprint.web.logic import with_sprints

    data = Repository(data_dir).load("demo")
    base = build_forecast(data, TODAY)
    target = next(e for e in base.upcoming() if not e.recorded)
    sprint = Sprint(id=target.sprint.id, start=target.sprint.start, end=target.sprint.end)
    legacy = build_forecast(with_sprints(data, [sprint]), TODAY).entry(sprint.id)
    assert legacy.result.plan_capacity_source is CapacitySource.ESTIMATED  # empty file: unknown
    sprint.absences_confirmed = True
    confirmed = build_forecast(with_sprints(data, [sprint]), TODAY).entry(sprint.id)
    assert confirmed.result.plan_capacity_source is CapacitySource.PEOPLE

    from foresprint.storage import Repository as Repo

    repo = Repo(data_dir)
    repo.save_sprint("demo", sprint)
    assert repo.load("demo").sprint(sprint.id).absences_confirmed is True


def _sprint(**fields) -> Sprint:
    return Sprint(id="2026.30", start=date(2026, 12, 1), end=date(2026, 12, 14), **fields)


def test_board_steps_done_without_a_sprint_file_nothing_is_done():
    assert board_steps_done(None) == {
        "absences": False,
        "preplanning": False,
        "planning": False,
        "review": False,
    }
    # An empty file confirms nothing either (state unknown)
    assert not any(board_steps_done(_sprint()).values())


def test_board_steps_done_absences_only_when_confirmed():
    """Check mark for absences only for the state "confirmed" (state per sprint), not for
    "announced" or "unknown" and not because a file exists."""
    entered = _sprint(absences={"anna": 1.0})
    assert board_steps_done(entered)["absences"]
    nobody = _sprint(absence_state=AbsenceState.CONFIRMED)
    assert board_steps_done(nobody)["absences"]  # explicitly "nobody is absent"
    unknown = _sprint(absence_state=AbsenceState.UNKNOWN)
    assert not board_steps_done(unknown)["absences"]
    expected = _sprint(expected_absences={"anna": 2.0})
    assert not board_steps_done(expected)["absences"]  # announced confirms nothing
    only_preplanned = _sprint(products={"app": ProductValues(preplanned=3.0)})
    assert not board_steps_done(only_preplanned)["absences"]
    # Only the absences are recorded: the other steps stay open
    assert board_steps_done(entered) == {
        "absences": True,
        "preplanning": False,
        "planning": False,
        "review": False,
    }


def test_blank_product_cells_stay_none_and_zero_stays_zero():
    """The tables show empty cells as "-" (display only): NaN or None = not recorded still comes
    back, and 0 stays a recorded zero."""
    base = _sprint(products={"app": ProductValues(preplanned=2.0)})
    rows = [
        {"_id": "app", "PO pre-planning": float("nan"), "Planning": 0.0},
        {"_id": "web", "PO pre-planning": None, "Planning": float("nan")},
    ]
    after = apply_product_values(base, rows, ["preplanned", "planned"])
    assert after.products["app"].preplanned is None
    assert after.products["app"].planned == 0.0
    assert "web" not in after.products  # nothing recorded: no empty entry


def test_hidden_product_columns_keep_their_stored_values():
    """A column the editor does not show (missing in the row) is not overwritten."""
    base = _sprint(products={"app": ProductValues(planned=2.0, production_planned=1.0)})
    rows = [{"_id": "app", "Planning": 3.0}]
    after = apply_product_values(base, rows, ["planned", "production_planned"])
    assert after.products["app"].planned == 3.0
    assert after.products["app"].production_planned == 1.0


def test_board_steps_done_other_steps_follow_their_values():
    sprint = _sprint(
        products={"app": ProductValues(), "web": ProductValues(preplanned=0.0)},
        commitment=0.0,  # 0 is recorded (not "missing")
        velocity=7.5,
    )
    done = board_steps_done(sprint)
    assert done["preplanning"] and done["planning"] and done["review"]
    assert not board_steps_done(_sprint(products={"app": ProductValues(planned=2.0)}))[
        "preplanning"
    ]


def test_capacity_usage():
    from foresprint.web.logic import capacity_usage

    usage = capacity_usage(20.0, 15.0)
    assert usage is not None
    assert (usage.rest, usage.ratio, usage.over) == (5.0, 0.75, False)
    over = capacity_usage(20.0, 24.0)
    assert over is not None
    assert (over.rest, over.over) == (-4.0, True)
    assert capacity_usage(None, 3.0) is None
    assert capacity_usage(20.0, None) is None
    zero = capacity_usage(0.0, 2.0)
    assert zero is not None and zero.ratio == 0.0 and zero.over


def test_board_steps_done_preplanning_needs_every_active_product():
    from foresprint.model import Product, ProductValues

    shop, app, old = (
        Product("shop", "Shop"),
        Product("app", "App"),
        Product("old", "Old", end=date(2026, 11, 1)),  # no longer active in the sprint
    )
    products = [shop, app, old]

    def preplanned(**values) -> Sprint:
        return _sprint(products={k: ProductValues(preplanned=v) for k, v in values.items()})

    assert not board_steps_done(preplanned(shop=3.0), products)["preplanning"]
    assert not board_steps_done(_sprint(), products)["preplanning"]
    assert board_steps_done(preplanned(shop=3.0, app=2.0), products)["preplanning"]
    # A product without a value (only an entry without preplanned) does not count
    partial = _sprint(products={"shop": ProductValues(preplanned=1.0), "app": ProductValues()})
    assert not board_steps_done(partial, products)["preplanning"]
    # Without known products any value suffices (as before)
    assert board_steps_done(preplanned(shop=3.0))["preplanning"]
