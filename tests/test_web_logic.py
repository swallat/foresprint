# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from sprintforecast.forecast import build_forecast
from sprintforecast.storage import Repository
from sprintforecast.web.logic import (
    absence_matrix,
    absence_sprints,
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
    assert [r["id"] for r in rows] == ["anna", "ben", "cem", "dana"]  # emil ausgetreten
    assert rows[2]["2026.22"] == 5  # cem
    edited = edit_absences(data.people, sprints, rows)
    assert [s.absences for s in edited] == [s.absences for s in sprints]
    # 2026.23 hat noch keine Datei → wird mit gespeichert
    assert [s.id for s in sprints_to_save(data, sprints, edited)] == ["2026.23"]

    rows[0]["2026.23"] = 2.5  # anna im Sprint ohne Datei
    rows[2]["2026.22"] = None  # cem: leer = keine Fehltage
    edited = edit_absences(data.people, sprints, rows)
    to_save = {s.id: s for s in sprints_to_save(data, sprints, edited)}
    assert set(to_save) == {"2026.22", "2026.23"}
    assert to_save["2026.23"].absences == {"anna": 2.5}
    assert "cem" not in to_save["2026.22"].absences


def test_people_table_roundtrip(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=True)
    assert hidden == []
    assert len(rows) == 6  # Ben hat zwei Zeiträume
    result = people_from_table(rows, people, hidden)
    assert (result.errors, result.deleted) == ([], [])
    assert result.people == people


def test_former_people_hidden_and_preserved(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    assert [p.name for p in hidden] == ["Emil"]  # bis 31.07.2026
    assert "Emil" not in {r["Name"] for r in rows}
    result = people_from_table(rows, people, hidden)
    assert result.deleted == []
    assert result.people == people


def test_new_rows_get_ids_and_join_existing_person(data_dir: Path):
    people = Repository(data_dir).load("demo").people
    rows, hidden = people_table(people, TODAY, show_former=False)
    anna = next(r for r in rows if r["Name"] == "Anna")
    anna["bis"] = date(2026, 10, 31)
    rows += [
        # FTE-Änderung: neue Zeile, gleicher Name, keine ID
        {"_id": None, "Name": "Anna", "Bundesland": "(Team)", "ab": "2026-11-01", "bis": None,
         "FTE": 0.5},
        {"_id": float("nan"), "Name": "Jörg Müller", "Bundesland": "BY",
         "ab": pd.Timestamp("2026-11-01"), "bis": pd.NaT, "FTE": float("nan")},
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
    ben[1]["Bundesland"] = "HE"  # zweiter Zeitraum mit anderem Bundesland
    rows.append({"_id": None, "Name": "", "Bundesland": None, "ab": None, "bis": None, "FTE": 1})
    rows.append({"_id": None, "Name": "Neu", "Bundesland": None, "ab": None, "bis": None})
    errors = people_from_table(rows, people, hidden).errors
    assert any("unterschiedliche Namen oder Bundesländer" in e for e in errors)
    assert any("Name fehlt" in e for e in errors)
    assert any("(Neu): 'ab' fehlt" in e for e in errors)


def test_parse_numbers():
    assert parse_numbers("4,25 4.5; 1") == [4.25, 4.5, 1.0]
    with pytest.raises(ValueError):
        parse_numbers("4,25 x")
