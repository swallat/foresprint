# SPDX-License-Identifier: EUPL-1.2
"""Änderungsansicht: Wertänderungen zwischen zwei YAML-Ständen."""

from pathlib import Path

from gitrepos import git, make_local

from sprintforecast.diff import ADDED, CHANGED, REMOVED, diff_values, file_changes
from sprintforecast.yamlmerge import MISSING


def test_equal_values_have_no_changes():
    assert diff_values({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == []


def test_changed_added_removed_with_path():
    changes = diff_values({"v": 10, "gone": 1, "n": {"x": 1}}, {"v": 11, "n": {"x": 2}, "new": 5})
    by_label = {c.label: c for c in changes}
    assert by_label["v"].kind == CHANGED and (by_label["v"].old, by_label["v"].new) == (10, 11)
    assert by_label["gone"].kind == REMOVED and by_label["gone"].new is MISSING
    assert by_label["n.x"].kind == CHANGED
    assert by_label["new"].kind == ADDED and by_label["new"].old is MISSING


def test_bool_and_int_differ():
    (change,) = diff_values({"a": True}, {"a": 1})
    assert change.kind == CHANGED


def test_people_are_compared_per_id():
    old = {"people": [{"id": "anna", "fte": 1.0}, {"id": "ben", "fte": 0.5}]}
    new = {"people": [{"id": "ben", "fte": 0.8}, {"id": "anna", "fte": 1.0}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people", "[ben]", "fte") and (change.old, change.new) == (0.5, 0.8)


def test_added_person_is_one_change():
    old = {"people": [{"id": "anna"}]}
    new = {"people": [{"id": "anna"}, {"id": "ben", "fte": 1}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people", "[ben]") and change.kind == ADDED


def test_plain_lists_are_one_value():
    (change,) = diff_values({"l": [1, 2]}, {"l": [1, 3]})
    assert change.path == ("l",) and change.old == [1, 2]


def test_file_changes_against_head(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    (data / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    (data / "notiz.txt").write_text("x", encoding="utf-8")
    result = {c.file: c for c in file_changes(data)}
    team = result["teams/team.yaml"]
    assert [(c.label, c.old, c.new) for c in team.values] == [("name", "A", "B")]
    assert result["teams/neu.yaml"].values == () and result["teams/neu.yaml"].readable
    assert not result["teams/notiz.txt"].readable


def test_deleted_and_broken_files(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").unlink()
    (data / "kaputt.yaml").write_text("a: [\n", encoding="utf-8")
    (data / "alt.yaml").write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "teams/alt.yaml")
    git(root, "commit", "-qm", "alt")
    (data / "alt.yaml").write_text("a: [\n", encoding="utf-8")
    result = {c.file: c for c in file_changes(data)}
    assert result["teams/team.yaml"].status == "D" and result["teams/team.yaml"].readable
    assert not result["teams/kaputt.yaml"].readable
    assert not result["teams/alt.yaml"].readable
