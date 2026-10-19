# SPDX-License-Identifier: EUPL-1.2
"""Zusammenführen auf Schlüsselebene und stabiles Schreiben."""

from pathlib import Path

import pytest

from sprintforecast.storage import ConflictError, DataError, Repository, has_conflict_markers
from sprintforecast.yamlmerge import MISSING, merge3, same

BASE = {"velocity": 10, "absences": {"anna": 1}, "note": "x", "list": [1, 2]}


def test_different_keys_are_united():
    ours = {**BASE, "velocity": 11}
    theirs = {**BASE, "absences": {"anna": 1, "ben": 2}}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert conflicts == []
    assert merged["velocity"] == 11 and merged["absences"] == {"anna": 1, "ben": 2}


def test_nan_values_are_the_same_value():
    assert same(float("nan"), float("nan"))
    assert same([1, float("nan")], [1, float("nan")])
    assert not same(float("nan"), 1.0)
    merged, conflicts = merge3(
        {"v": float("nan")}, {"v": float("nan"), "a": 1}, {"v": float("nan"), "b": 2}
    )
    assert conflicts == [] and merged["a"] == 1 and merged["b"] == 2


def test_same_change_on_both_sides_is_no_conflict():
    merged, conflicts = merge3(BASE, {**BASE, "velocity": 9}, {**BASE, "velocity": 9})
    assert conflicts == [] and merged["velocity"] == 9


def test_nested_keys_merge_but_same_value_conflicts():
    ours = {**BASE, "absences": {"anna": 2}}
    theirs = {**BASE, "absences": {"anna": 3, "ben": 1}}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert [(c.path, c.ours, c.theirs) for c in conflicts] == [(("absences", "anna"), 2, 3)]
    assert merged["absences"] == {"anna": 2, "ben": 1}  # Standard: meine Seite


def test_choices_decide_conflicts():
    ours, theirs = {**BASE, "velocity": 11}, {**BASE, "velocity": 12}
    assert merge3(BASE, ours, theirs, {("velocity",): "theirs"})[0]["velocity"] == 12
    assert merge3(BASE, ours, theirs, {("velocity",): "ours"})[0]["velocity"] == 11
    assert merge3(BASE, ours, theirs, {("velocity",): "ours"})[1] == []


def test_deleted_on_one_side_changed_on_other_is_conflict():
    ours = {k: v for k, v in BASE.items() if k != "note"}
    theirs = {**BASE, "note": "geändert"}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert conflicts[0].path == ("note",) and conflicts[0].ours is MISSING
    assert "note" not in merged
    assert merge3(BASE, ours, theirs, {("note",): "theirs"})[0]["note"] == "geändert"


def test_delete_without_change_on_other_side_wins():
    ours = {k: v for k, v in BASE.items() if k != "note"}
    merged, conflicts = merge3(BASE, ours, dict(BASE))
    assert conflicts == [] and "note" not in merged


def test_lists_are_one_value_unless_entries_have_ids():
    merged, conflicts = merge3(BASE, {**BASE, "list": [1, 3]}, {**BASE, "list": [1, 2, 4]})
    assert [c.path for c in conflicts] == [("list",)]
    base = {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}]}
    ours = {"people": [{"id": "a", "fte": 0.5}, {"id": "b", "fte": 1}]}
    theirs = {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}, {"id": "c", "fte": 1}]}
    merged, conflicts = merge3(base, ours, theirs)
    assert conflicts == []
    assert merged["people"] == [
        {"id": "a", "fte": 0.5},
        {"id": "b", "fte": 1},
        {"id": "c", "fte": 1},
    ]
    theirs2 = {"people": [{"id": "a", "fte": 0.8}, {"id": "b", "fte": 1}]}
    _, conflicts = merge3(base, ours, theirs2)
    assert conflicts[0].path == ("people", "[a]", "fte")


def test_added_on_both_sides_without_base():
    merged, conflicts = merge3(MISSING, {"a": 1}, {"b": 2})
    assert conflicts == [] and merged == {"a": 1, "b": 2}


MARKED = "a: 1\n<<<<<<< HEAD\nb: 2\n=======\nb: 3\n>>>>>>> origin/main\n"


def test_conflict_markers_are_detected_before_loading(data_dir: Path):
    assert has_conflict_markers(MARKED) and not has_conflict_markers("a: 1\n")
    sprint = data_dir / "demo" / "sprints" / "2026.20.yaml"
    sprint.write_text(MARKED)
    repo = Repository(data_dir)
    with pytest.raises(ConflictError) as info:
        repo.load("demo")
    assert info.value.files == [sprint]
    assert isinstance(info.value, DataError)  # bestehende Fehlerbehandlung greift weiter
    with pytest.raises(ConflictError):
        repo.load_cached("demo")


def test_write_is_stable(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprints[-1]
    path = repo.save_sprint("demo", sprint)
    first = path.read_bytes()
    stamp = path.stat().st_mtime_ns
    repo.save_sprint("demo", repo.load("demo").sprints[-1])
    assert path.read_bytes() == first and path.stat().st_mtime_ns == stamp  # unverändert
    assert b"\r" not in first and first.endswith(b"\n")
    # Personen und Produkte erscheinen sortiert: Ergänzungen kollidieren seltener
    sprint.absences = {"zoe": 1.0, "anna": 2.0}
    text = repo.save_sprint("demo", sprint).read_text()
    assert text.index("anna:") < text.index("zoe:")
    assert not list(path.parent.glob("*.tmp"))
