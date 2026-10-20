# SPDX-License-Identifier: EUPL-1.2
"""Suggested commit message derived from the change view."""

from foresprint.commit_message import MAX_LENGTH, suggest_message
from foresprint.diff import FileChange, ValueChange
from foresprint.yamlmerge import MISSING


def test_no_changes_gives_none():
    assert suggest_message([]) is None


def test_single_value_names_old_and_new(english):
    fc = FileChange("kac/people.yaml", " M", (ValueChange(("people", "[ben]", "fte"), 0.5, 0.8),))
    assert suggest_message([fc]) == "Update people.[ben].fte in kac/people.yaml: 0.5 → 0.8"


def test_added_and_removed_value(english):
    added = FileChange("a.yaml", " M", (ValueChange(("x",), MISSING, 3),))
    removed = FileChange("a.yaml", " M", (ValueChange(("x",), 3, MISSING),))
    assert suggest_message([added]) == "Add x in a.yaml: 3"
    assert suggest_message([removed]) == "Remove x from a.yaml"


def test_several_values_in_one_file(english):
    values = tuple(ValueChange((f"k{i}",), i, i + 1) for i in range(3))
    assert suggest_message([FileChange("a.yaml", " M", values, omitted=2)]) == (
        "Update a.yaml: 5 values"
    )


def test_file_level_changes(english):
    assert suggest_message([FileChange("new.yaml", "??")]) == "Add new.yaml"
    assert suggest_message([FileChange("old.yaml", " D")]) == "Remove old.yaml"
    assert suggest_message([FileChange("b.yaml", "R ", orig="a.yaml")]) == (
        "Rename a.yaml to b.yaml"
    )
    assert suggest_message([FileChange("log.md", " M", readable=False)]) == "Update log.md"


def test_several_files_list_names_and_count(english):
    files = [FileChange(f"{d}/team.yaml", " M") for d in ("a", "b")]
    assert suggest_message(files) == "Update 2 files: a/team.yaml, b/team.yaml"
    many = [FileChange(f"f{i}.yaml", " M") for i in range(5)]
    assert suggest_message(many) == "Update 5 files: f0.yaml, f1.yaml, f2.yaml and 2 more"


def test_long_values_and_names_are_shortened(english):
    fc = FileChange("x.yaml", " M", (ValueChange(("note",), "a" * 200, "b\nc" * 50),))
    message = suggest_message([fc])
    assert message is not None and len(message) <= MAX_LENGTH and "\n" not in message


def test_german_is_the_source_language():
    fc = FileChange("a.yaml", " M", (ValueChange(("x",), 1, 2),))
    assert suggest_message([fc]) == "x in a.yaml geändert: 1 → 2"


def test_copy_is_not_called_a_rename(english):
    assert suggest_message([FileChange("b.yaml", "C ", orig="a.yaml")]) == "Copy a.yaml to b.yaml"
