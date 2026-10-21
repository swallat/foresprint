# SPDX-License-Identifier: EUPL-1.2
"""Change view: value changes between two YAML states."""

import contextlib
import os
import subprocess
from pathlib import Path

import pytest
from gitrepos import git, make_local

from foresprint import diff as diff_module
from foresprint.diff import (
    ADDED,
    CHANGED,
    REMOVED,
    TooComplex,
    cached_file_changes,
    diff_values,
    file_changes,
)
from foresprint.git import GitError, pending_changes
from foresprint.yamlmerge import MISSING


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
    (data / "neu.yaml").write_text("a: 2\n", encoding="utf-8")  # status AM
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
    monkeypatch.setattr("foresprint.diff._MAX_BYTES", 20)
    (change,) = file_changes(data)
    assert not change.readable


def test_oversized_committed_file_is_unreadable(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: " + "B" * 100 + "\n", encoding="utf-8")
    git(root, "commit", "-qam", "gross")
    (data / "team.yaml").write_text("name: C\n", encoding="utf-8")
    monkeypatch.setattr("foresprint.diff._MAX_BYTES", 20)
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

    monkeypatch.setattr("foresprint.git._git_bytes", broken("error"))
    (change,) = file_changes(data)
    assert not change.readable
    monkeypatch.setattr("foresprint.git._git_bytes", broken("git_missing"))
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


def test_renamed_file_knows_its_old_path(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    git(root, "mv", "teams/team.yaml", "teams/neu.yaml")
    (change,) = file_changes(data)
    assert (change.file, change.orig, change.values) == ("teams/neu.yaml", "teams/team.yaml", ())


def test_only_the_first_files_are_evaluated(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    (data / "zweit.yaml").write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "teams/zweit.yaml")
    git(root, "commit", "-qm", "zweit")
    (data / "zweit.yaml").write_text("a: 2\n", encoding="utf-8")
    monkeypatch.setattr("foresprint.diff._EVAL_LIMIT", 1)
    first, second = file_changes(data)
    assert first.values and not second.values and second.readable


def test_the_26th_file_is_readable_without_values(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    for i in range(26):
        (data / f"f{i:03}.yaml").write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "viele")
    for i in range(26):
        (data / f"f{i:03}.yaml").write_text("a: 2\n", encoding="utf-8")
    result = file_changes(data)
    assert len(result) == 26
    assert all(c.values for c in result[:25])
    assert result[25].file.endswith("f025.yaml") and result[25].readable
    assert result[25].values == ()


def test_old_path_for_text_files_new_deleted_and_beyond_the_limit(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "a.txt").write_text("x", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "txt")
    git(root, "mv", "teams/a.txt", "teams/b.txt")
    (data / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    (data / "team.yaml").unlink()
    result = {c.file: c for c in file_changes(data)}
    assert result["teams/b.txt"].orig == "teams/a.txt" and not result["teams/b.txt"].readable
    assert result["teams/neu.yaml"].orig == "" and result["teams/team.yaml"].orig == ""
    monkeypatch.setattr("foresprint.diff._EVAL_LIMIT", 0)
    beyond = {c.file: c for c in file_changes(data)}
    assert beyond["teams/b.txt"].orig == "teams/a.txt" and beyond["teams/b.txt"].readable


def alias_bomb(last: str) -> str:
    lines = ["l0: &l0 [x, x, x, x, x, x, x, x, x]"]
    lines += [f"l{i}: &l{i} [{', '.join([f'*l{i - 1}'] * 9)}]" for i in range(1, 7)]
    return "\n".join(lines) + f"\nz: {last}\n"


def test_alias_bomb_is_not_evaluated(tmp_path: Path):
    import time

    import yaml

    tree = yaml.safe_load(alias_bomb("1"))
    assert diff_values(tree, tree) == []  # same object: equal immediately
    with pytest.raises(TooComplex):
        diff_values(tree, yaml.safe_load(alias_bomb("2")))
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "bombe.yaml").write_text(alias_bomb("1"), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "bombe")
    (data / "bombe.yaml").write_text(alias_bomb("2"), encoding="utf-8")
    started = time.monotonic()
    (change,) = file_changes(data)
    assert not change.readable and time.monotonic() - started < 10


def pending_of(path: Path):
    return pending_changes(path)


def counting(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    real = diff_module.file_changes

    def wrapper(path: Path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(diff_module, "file_changes", wrapper)
    return calls


def test_cache_notices_a_new_head_from_outside(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    calls = counting(monkeypatch)
    cached_file_changes(data, pending_of(data))
    cached_file_changes(data, pending_of(data))
    assert len(calls) == 1
    git(root, "commit", "-q", "--allow-empty", "-m", "von außen")
    cached_file_changes(data, pending_of(data))
    assert len(calls) == 2


def test_cache_notices_a_changed_size_with_the_same_time(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    file = data / "team.yaml"
    file.write_text("name: B\n", encoding="utf-8")
    calls = counting(monkeypatch)
    cached_file_changes(data, pending_of(data))
    stamp = file.stat().st_mtime_ns
    file.write_text("name: CC\n", encoding="utf-8")
    os.utime(file, ns=(stamp, stamp))
    (change,) = cached_file_changes(data, pending_of(data))
    assert len(calls) == 2 and change.values[0].new == "CC"


def test_cache_notices_same_size_content_with_the_old_time_restored(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    file = data / "team.yaml"
    file.write_text("name: B\n", encoding="utf-8")
    calls = counting(monkeypatch)
    cached_file_changes(data, pending_of(data))
    stat = file.stat()
    file.write_text("name: C\n", encoding="utf-8")  # same size
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # timestamp as before
    (change,) = cached_file_changes(data, pending_of(data))
    assert len(calls) == 2 and change.values[0].new == "C"


def test_at_most_25_files_are_parsed_and_results_stay_small(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    for i in range(40):
        (data / f"f{i:02}.yaml").write_text("l: [0]\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "viele")
    big = list(range(5000))
    for i in range(40):
        (data / f"f{i:02}.yaml").write_text(
            f"l: {big}\n" + "".join(f"k{j}: {j}\n" for j in range(45)), encoding="utf-8"
        )
    parsed: list[str] = []
    real = diff_module._parse

    def counting_parse(text: str):
        parsed.append(text)
        return real(text)

    monkeypatch.setattr(diff_module, "_parse", counting_parse)
    result = file_changes(data)
    assert len(result) == 40 and len(parsed) == 2 * 25  # HEAD and working state per file
    assert all(c.readable and not c.values for c in result[25:])
    first = result[0]
    assert len(first.values) == diff_module.MAX_VALUES and first.omitted == 46 - 30
    assert len(first.values[0].new) <= diff_module._SLIM_ITEMS  # not a whole subtree


def test_big_files_are_rejected_cheaply_without_parsing(tmp_path: Path, monkeypatch):
    import time

    root = make_local(tmp_path)
    data = root / "teams"
    small = "".join(f"k{i}: 1\n" for i in range(5))
    for i in range(25):
        (data / f"g{i:02}.yaml").write_text(small, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "g")
    big = "".join(f"k{i}: 1\n" for i in range(100_001))  # about 1 MB, over 200,000 nodes
    assert len(big) < 1024 * 1024
    for i in range(25):
        (data / f"g{i:02}.yaml").write_text(big, encoding="utf-8")
    parsed: list[str] = []
    real = diff_module._parse
    monkeypatch.setattr(diff_module, "_parse", lambda text: parsed.append(text) or real(text))
    started = time.monotonic()
    result = file_changes(data)
    assert time.monotonic() - started < 2
    assert len(result) == 25 and all(not c.values for c in result)
    assert not result[0].readable  # too large; later: total budget used up (skipped)
    assert len(parsed) <= 25  # only the small HEAD versions, at most once per file


def test_files_over_one_mebibyte_have_no_value_view(tmp_path: Path):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("a: " + "x" * (1024 * 1024) + "\n", encoding="utf-8")
    (change,) = file_changes(data)
    assert not change.readable


def test_total_size_budget_marks_the_remaining_files_as_skipped(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    for name in ("a.yaml", "b.yaml", "c.yaml"):
        (data / name).write_text("a: 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "abc")
    for name in ("a.yaml", "b.yaml", "c.yaml"):
        (data / name).write_text("a: 2\n", encoding="utf-8")
    monkeypatch.setattr(diff_module, "_BYTES_BUDGET", 20)  # HEAD and working state: 10 per file
    a, b, c = file_changes(data)
    assert a.values and b.values and not b.skipped
    assert c.skipped and c.readable and not c.values


def test_null_and_bool_keys_use_the_notation_of_the_file():
    changes = diff_values({None: 1, True: 1, False: 1}, {None: 2, True: 2, False: 2})
    assert [c.label for c in changes] == ["null", "true", "false"]


def test_signature_stats_only_the_evaluated_files(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    for i in range(500):
        (data / f"n{i:03}.txt").write_text("x", encoding="utf-8")
    pending = pending_of(data)
    assert len(pending) == 500
    stats: list[Path] = []
    real = Path.lstat

    def counting_lstat(self: Path, *args, **kwargs):
        stats.append(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", counting_lstat)
    signature = diff_module._signature(root, pending)
    assert len(stats) <= 25 and len(signature) == 501  # HEAD plus all entries
    first = diff_module._signature(root, pending)
    assert first == signature
    # Even beyond the limit the entry (status, file) belongs to the signature
    assert diff_module._signature(root, [*pending, ("M", "teams/x.yaml")]) != signature


def test_signature_carries_size_mtime_inode_and_inode_time(tmp_path: Path):
    root = make_local(tmp_path)
    file = root / "teams" / "team.yaml"
    file.write_text("name: B\n", encoding="utf-8")
    stat = file.stat()
    entry = diff_module._signature(root, [("M", "teams/team.yaml")])[1]
    assert entry == (
        "M",
        "teams/team.yaml",
        stat.st_mtime_ns,
        stat.st_size,
        stat.st_ino,
        stat.st_ctime_ns,
    )


def test_many_equal_singletons_still_hit_the_node_limit(tmp_path: Path):
    lines = "".join(f"k{i}: null\n" for i in range(diff_module.MAX_NODES + 1))
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "viel.yaml").write_text(lines + "z: 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "viel")
    (data / "viel.yaml").write_text(lines + "z: 2\n", encoding="utf-8")
    (change,) = file_changes(data)
    assert not change.readable
    with pytest.raises(TooComplex):
        diff_values(
            {f"k{i}": None for i in range(diff_module.MAX_NODES + 1)} | {"z": 1},
            {f"k{i}": None for i in range(diff_module.MAX_NODES + 1)} | {"z": 2},
        )


def test_cache_key_is_the_resolved_path_and_the_result_is_a_copy(tmp_path: Path, monkeypatch):
    root = make_local(tmp_path)
    data = root / "teams"
    (data / "team.yaml").write_text("name: B\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(data)
    calls = counting(monkeypatch)
    first = cached_file_changes(data, pending_of(data))
    first.clear()  # does not change the cache
    again = cached_file_changes(link, pending_of(data))
    assert len(calls) == 1 and len(again) == 1
    again.clear()  # the result of a hit is a copy as well
    assert len(cached_file_changes(data, pending_of(data))) == 1
