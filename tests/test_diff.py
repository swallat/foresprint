# SPDX-License-Identifier: EUPL-1.2
"""Änderungsansicht: Wertänderungen zwischen zwei YAML-Ständen."""

import contextlib
import subprocess
from pathlib import Path

import pytest
from gitrepos import git, make_local

from sprintforecast.diff import ADDED, CHANGED, REMOVED, diff_values, file_changes
from sprintforecast.git import GitError
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
    new = {"people": [{"id": "anna", "fte": 1.0}, {"id": "ben", "fte": 0.8}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people", "[ben]", "fte") and (change.old, change.new) == (0.5, 0.8)


def test_added_person_is_one_change():
    old = {"people": [{"id": "anna"}]}
    new = {"people": [{"id": "anna"}, {"id": "ben", "fte": 1}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people", "[ben]") and change.kind == ADDED


def test_first_person_added_to_empty_list_keeps_id_path():
    (change,) = diff_values({"people": []}, {"people": [{"id": "anna"}]})
    assert change.path == ("people", "[anna]") and change.kind == ADDED


def test_last_person_removed_keeps_id_path():
    (change,) = diff_values({"people": [{"id": "anna"}]}, {"people": []})
    assert change.path == ("people", "[anna]") and change.kind == REMOVED


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


def test_rename_from_non_yaml_is_not_compared(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "notiz.txt").write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "teams/notiz.txt")
    git(root, "commit", "-qm", "notiz")
    git(root, "mv", "teams/notiz.txt", "teams/notiz.yaml")
    result = {c.file: c for c in file_changes(data)}
    assert not result["teams/notiz.yaml"].readable


def test_type_changes_are_one_change():
    (a,) = diff_values({"a": {"x": 1}}, {"a": 5})
    assert a.path == ("a",) and a.kind == CHANGED
    (b,) = diff_values({"p": [{"id": "a"}]}, {"p": [1]})
    assert b.path == ("p",) and b.kind == CHANGED
    (c,) = diff_values({"p": None}, {"p": [{"id": "a"}]})
    assert c.path == ("p",) and c.kind == CHANGED


def test_root_label_is_a_dot():
    (change,) = diff_values(1, 2)
    assert change.label == "."


def test_reordered_people_are_reported():
    old = {"people": [{"id": "anna"}, {"id": "ben"}]}
    new = {"people": [{"id": "ben"}, {"id": "anna"}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people",) and (change.old, change.new) == (
        ["anna", "ben"],
        ["ben", "anna"],
    )


def test_order_of_unrelated_people_does_not_count_when_one_was_added():
    old = {"people": [{"id": "anna"}, {"id": "ben"}]}
    new = {"people": [{"id": "anna"}, {"id": "cleo"}, {"id": "ben"}]}
    (change,) = diff_values(old, new)
    assert change.path == ("people", "[cleo]") and change.kind == ADDED


def test_nan_is_not_a_change():
    assert diff_values({"a": float("nan")}, {"a": float("nan")}) == []
    assert diff_values({"l": [1, float("nan")]}, {"l": [1, float("nan")]}) == []
    assert diff_values({"o": {"x": [float("nan")]}}, {"o": {"x": [float("nan")]}}) == []
    (change,) = diff_values({"a": float("nan")}, {"a": 1.0})
    assert change.kind == CHANGED


def test_renamed_yaml_file_is_compared_with_its_old_content(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    git(root, "mv", "teams/team.yaml", "teams/neu.yaml")
    (data / "neu.yaml").write_text("name: B\n", encoding="utf-8")
    result = {c.file: c for c in file_changes(data)}
    renamed = result["teams/neu.yaml"]
    assert renamed.readable
    assert [(c.label, c.old, c.new) for c in renamed.values] == [("name", "A", "B")]


def test_staged_new_file_is_readable_without_values(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "teams/neu.yaml")
    (data / "neu.yaml").write_text("a: 2\n", encoding="utf-8")  # Status AM
    (change,) = [c for c in file_changes(data) if c.file == "teams/neu.yaml"]
    assert change.status == "AM" and change.readable and change.values == ()


def test_symlink_is_not_followed(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    outside = tmp_path / "geheim.yaml"
    outside.write_text("secret: 42\n", encoding="utf-8")
    (data / "team.yaml").unlink()
    (data / "team.yaml").symlink_to(outside)
    (change,) = [c for c in file_changes(data) if c.file == "teams/team.yaml"]
    assert not change.readable and change.values == ()


def test_oversized_working_file_is_unreadable(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: " + "B" * 100 + "\n", encoding="utf-8")
    monkeypatch.setattr("sprintforecast.diff._MAX_BYTES", 20)
    (change,) = file_changes(data)
    assert not change.readable


def test_oversized_committed_file_is_unreadable(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: " + "B" * 100 + "\n", encoding="utf-8")
    git(root, "commit", "-qam", "gross")
    (data / "team.yaml").write_text("name: C\n", encoding="utf-8")
    monkeypatch.setattr("sprintforecast.diff._MAX_BYTES", 20)
    (change,) = file_changes(data)
    assert not change.readable


def test_deeply_nested_file_does_not_break_the_others(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    depth = 1500
    (data / "tief.yaml").write_text("{a: " * depth + "1" + "}" * depth + "\n", encoding="utf-8")
    git(root, "add", "teams/tief.yaml")
    git(root, "commit", "-qm", "tief")
    (data / "tief.yaml").write_text("{a: " * depth + "2" + "}" * depth + "\n", encoding="utf-8")
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    result = {c.file: c for c in file_changes(data)}
    assert not result["teams/tief.yaml"].readable
    assert [c.label for c in result["teams/team.yaml"].values] == ["name"]


def test_git_problems_are_raised_other_git_errors_make_the_file_unreadable(
    tmp_path: Path, monkeypatch
):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")

    def broken(kind: str):
        def read(*args, **kwargs):
            raise GitError("x", kind)

        return read

    monkeypatch.setattr("sprintforecast.git._git_bytes", broken("error"))
    (change,) = file_changes(data)
    assert not change.readable
    monkeypatch.setattr("sprintforecast.git._git_bytes", broken("git_missing"))
    with pytest.raises(GitError):
        file_changes(data)


def test_unmerged_file_deleted_by_them_is_read_from_the_working_tree(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    git(root, "switch", "-qc", "andere")
    git(root, "rm", "-q", "teams/team.yaml")
    git(root, "commit", "-qm", "geloescht")
    git(root, "switch", "-q", "main")
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    git(root, "commit", "-qam", "geaendert")
    with contextlib.suppress(subprocess.CalledProcessError):
        git(root, "merge", "andere")
    (data / "team.yaml").write_text("name: C\n", encoding="utf-8")
    (change,) = file_changes(data)
    assert change.status == "UD" and change.readable
    assert [(c.label, c.old, c.new) for c in change.values] == [("name", "B", "C")]
