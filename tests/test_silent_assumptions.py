# SPDX-License-Identifier: EUPL-1.2
"""The check reports silent assumptions on load (duplicate keys, empty number fields) as a note
with file, line and key path. Loading and calculating stay unchanged."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprintforecast.cli import app as cli_app
from sprintforecast.forecast import build_forecast
from sprintforecast.storage import AS_OF_ENV, DATA_ENV, Repository
from sprintforecast.validate import Level, check_all, check_team_files, check_yaml_text

TODAY = date(2026, 10, 15)
runner = CliRunner(env={"COLUMNS": "250"})
SPRINT = "sprints/2026.20.yaml"


def edit(data_dir: Path, name: str, old: str, new: str) -> Path:
    path = data_dir / "demo" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def issues(data_dir: Path):
    """Only the findings about silent assumptions (other plausibility notes are left out)."""
    return check_team_files(data_dir / "demo")


def test_bundled_sample_data_without_findings(data_dir: Path):
    assert issues(data_dir) == []
    assert check_all(Repository(data_dir), TODAY)["demo"] == []


def test_duplicate_key_is_reported(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    [issue] = issues(data_dir)
    assert issue.level is Level.WARNING
    assert issue.where == SPRINT
    assert "'velocity'" in issue.message
    assert "Zeilen 10, 11" in issue.message
    assert "letzten Eintrag (Zeile 11)" in issue.message


def test_nested_duplicate_key_names_the_path(data_dir: Path):
    edit(data_dir, SPRINT, "  anna: 5\n", "  anna: 5\n  anna: 3\n")
    [issue] = issues(data_dir)
    assert issue.where == SPRINT
    assert "absences.anna" in issue.message


def test_duplicate_key_in_list_names_the_list_path(data_dir: Path):
    edit(data_dir, "people.yaml", "    fte: 0.5\n", "    fte: 0.5\n    fte: 0.6\n")
    [issue] = issues(data_dir)
    assert issue.where == "people.yaml"
    assert "people[1].memberships[1].fte" in issue.message


def test_two_files_with_one_duplicate_each(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    edit(data_dir, "team.yaml", "name: ", "name: Eins\nname: ")
    found = issues(data_dir)
    assert sorted(i.where for i in found) == [SPRINT, "team.yaml"]
    assert all(i.level is Level.WARNING for i in found)


def test_empty_value_fte_is_reported(data_dir: Path):
    edit(data_dir, "people.yaml", "    fte: 0.5\n", "    fte:\n")
    [issue] = issues(data_dir)
    assert issue.level is Level.WARNING
    assert issue.where == "people.yaml"
    assert "people[1].memberships[1].fte" in issue.message
    assert "Zeile 18" in issue.message
    assert "mit 0" in issue.message


@pytest.mark.parametrize("raw", ["", "null", "~", '""'])
def test_empty_spellings(data_dir: Path, raw: str):
    edit(data_dir, SPRINT, "  anna: 5\n", f"  anna: {raw}\n")
    [issue] = issues(data_dir)
    assert "absences.anna" in issue.message


@pytest.mark.parametrize(
    ("old", "field"),
    [
        ("  carryover: 2.25\n", "planning.carryover"),
        ("  backlog: 9.75\n", "planning.backlog"),
        ("  - 0.75\n", "planning.corrections[0]"),
    ],
)
def test_empty_planning_values(data_dir: Path, old: str, field: str):
    new = old.split(":")[0] + ":\n" if ":" in old else "  -\n"
    edit(data_dir, SPRINT, old, new)
    [issue] = issues(data_dir)
    assert field in issue.message


def test_legitimate_empty_values_without_message(data_dir: Path):
    # to: null (membership without an end), unrecorded sprint values and region: meant to be empty
    edit(data_dir, SPRINT, "forecast_ist: 12\n", "forecast_ist:\n")
    edit(data_dir, SPRINT, "capacity: 29\n", "capacity: null\n")
    edit(data_dir, SPRINT, "    done: 3\n", "    done:\n")
    edit(data_dir, "products.yaml", "to: null", "to:")
    assert issues(data_dir) == []


def test_empty_files_without_message(data_dir: Path):
    (data_dir / "demo" / "products.yaml").write_text("", encoding="utf-8")
    (data_dir / "demo" / "people.yaml").write_text("# nur Kommentar\n", encoding="utf-8")
    assert issues(data_dir) == []


def test_invalid_yaml_stays_an_error(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: [\n")
    assert issues(data_dir) == []  # no follow-up messages from the broken file
    [issue] = check_all(Repository(data_dir), TODAY)["demo"]
    assert issue.level is Level.ERROR


def test_anchor_references_and_merge_keys_are_not_duplicates():
    text = "base: &b\n  x: 1\nother:\n  <<: *b\n  x: 2\nagain: *b\n"
    assert check_yaml_text(text, "x.yaml") == []


def test_calculation_with_duplicate_and_empty_value_stays_the_same(data_dir: Path, tmp_path: Path):
    clean = tmp_path / "clean"
    shutil.copytree(data_dir, clean)
    # Duplicate: the last value wins (as before); empty value: counts as 0
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 5\nvelocity: 9.75\n")
    edit(data_dir, SPRINT, "  anna: 5\n", "  anna:\n")
    edit(clean, SPRINT, "  anna: 5\n", "  anna: 0\n")

    loaded = Repository(data_dir).load("demo")
    reference = Repository(clean).load("demo")
    assert loaded == reference
    fc, fc_ref = build_forecast(loaded, TODAY), build_forecast(reference, TODAY)
    assert [(e.sprint.id, e.result) for e in fc.upcoming()] == [
        (e.sprint.id, e.result) for e in fc_ref.upcoming()
    ]
    assert len(issues(data_dir)) == 2  # both are reported, nothing aborts


def test_command_line_and_strict(data_dir: Path):
    edit(data_dir, SPRINT, "velocity: 9.75\n", "velocity: 9.75\nvelocity: 8\n")
    env = {DATA_ENV: str(data_dir), AS_OF_ENV: TODAY.isoformat()}
    result = runner.invoke(cli_app, ["check"], env=env)
    assert result.exit_code == 0
    assert "Hinweis sprints/2026.20.yaml" in result.output
    assert "'velocity' steht mehrfach" in result.output
    assert runner.invoke(cli_app, ["check", "--strict"], env=env).exit_code == 1


def messages(text: str) -> list[str]:
    return [i.message for i in check_yaml_text(text, "x.yaml")]


def test_empty_value_in_expected_absences_and_preplanned():
    assert any("expected_absences.anna" in m for m in messages("expected_absences:\n  anna:\n"))
    text = "prognoses:\n- at: 2026-10-01T10:00:00\n  preplanned:\n    app:\n"
    assert any("prognoses[0].preplanned.app" in m for m in messages(text))


def test_two_merge_keys_in_one_mapping_are_not_a_duplicate():
    text = "a: &a {x: 1}\nb: &b {y: 2}\nc:\n  <<: *a\n  <<: *b\n  z: 3\nd:\n  <<: [*a, *b]\n"
    assert messages(text) == []


def test_empty_value_via_anchor_and_merge_is_reported_under_every_path():
    text = (
        "people:\n- id: a\n  memberships:\n  - &m {from: 2025-01-01, fte: }\n  - *m\n"
        "- id: b\n  memberships:\n  - <<: *m\n    from: 2025-02-01\n"
    )
    found = " ".join(messages(text))
    for path in ("people[0].memberships[0].fte", "people[0].memberships[1].fte"):
        assert path in found
    assert "people[1].memberships[0].fte" in found


MEMBER = "people:\n- id: a\n  memberships:\n  - {from: 2025-01-01, fte: 1}\n"
BASE = "x: &x {fte: null}\ny: &y {fte: 0.5}\n"


def member(spec: str) -> list[str]:
    """Messages for a member that has ``spec`` (e.g. ``<<: *x``) in its membership."""
    return messages(BASE + f"people:\n- id: a\n  memberships:\n  - {{from: 2025-01-01, {spec}}}\n")


def test_inherited_empty_value_is_replaced_by_the_explicit_value():
    assert member("<<: *x, fte: 1") == []


def test_inherited_empty_value_is_reported_under_the_recipients_path():
    [found] = member("<<: *x")
    assert "people[0].memberships[0].fte" in found


def test_merge_list_the_first_source_wins():
    assert member("<<: [*y, *x]") == []  # fte comes from y (0.5), the empty value in x is dropped
    [found] = member("<<: [*x, *y]")  # fte comes from x: empty
    assert "memberships[0].fte" in found


def test_overridden_inherited_key_is_not_a_duplicate():
    assert member("<<: *x, fte: 1") == [] and member("<<: [*x, *y], fte: 2") == []


def test_inherited_over_two_levels():
    text = "a: &a {fte: }\nb: &b {<<: *a}\nc: &c {<<: *b, fte: 1}\n"
    assert messages(text) == []  # not under people: no number field, but no crash
    nested = "a: &a {fte: }\nb: &b {<<: *a}\n" + MEMBER.replace("fte: 1", "<<: *b")
    assert any("memberships[0].fte" in m for m in messages(nested))


def test_recursive_anchor_does_not_abort():
    assert messages("a: &x [*x, 1]\nb: &y {k: *y}\n") == []


def test_anchor_bomb_is_bounded_and_reported():
    lines = ["l0: &l0 [x, x, x, x, x, x, x, x, x]"]
    for n in range(1, 12):
        lines.append(f"l{n}: &l{n} [{', '.join([f'*l{n - 1}'] * 9)}]")
    [found] = messages("\n".join(lines) + "\n")
    assert "nicht vollständig geprüft" in found


def test_extreme_nesting_does_not_crash():
    depth = 5000
    text = "a: " + "[" * depth + "]" * depth + "\n"
    check_yaml_text(text, "x.yaml")  # must not raise an exception
    block = "".join("  " * i + "- \n" for i in range(depth))
    check_yaml_text("a:\n" + block, "x.yaml")


def test_key_type_distinguishes_except_for_abbreviations():
    # Short keys are read with str(): 1 and "1" are the same key there ...
    assert any("absences.1" in m for m in messages('absences:\n  1: 2\n  "1": 3\n'))
    assert any("products.1" in m for m in messages('products:\n  1: {}\n  "1": {}\n'))
    # ... otherwise the loader keeps both entries
    assert messages('1: a\n"1": b\n') == []
    assert messages("x: 1\ntrue: a\n'True': b\n") == []
    assert any("'True'" in m for m in messages("true: a\ntrue: b\n"))


@pytest.mark.parametrize(
    "text",
    ["{1: a, 1.0: b}\n", "{true: a, 1: b}\n", "{0: a, false: b}\n", "1: a\n1.0: b\n"],
)
def test_keys_equal_in_python_are_a_duplicate(text: str):
    """PyYAML maps 1, 1.0 and true to the same dict key: the later value wins."""
    import yaml

    from sprintforecast.storage import _YAML_LOADER

    assert len(yaml.load(text, Loader=_YAML_LOADER)) == 1  # the loader really discards one
    [found] = messages(text)
    assert "steht mehrfach" in found
    assert "Zeile" in found


def test_rows_with_same_key_of_different_type():
    [found] = messages("1: a\nx: 1\n1.0: b\n")
    assert "Zeilen 1, 3" in found


def test_unhashable_keys_do_not_crash():
    assert messages("? [a, b]\n: 1\n? {c: d}\n: 2\n") == []


def test_duplicate_in_a_row_names_the_columns():
    [found] = messages("absences: {anna: 1, anna: 2}\n")
    assert "alle in Zeile 1, Spalten 12, 21" in found
    assert "letzten Eintrag (Zeile 1, Spalte 21)" in found


def test_command_line_masks_markup_from_files(data_dir: Path):
    edit(data_dir, SPRINT, "  anna: 5\n", "  '[red]x[/red]': 1\n  '[red]x[/red]': 2\n  anna: 5\n")
    env = {DATA_ENV: str(data_dir), AS_OF_ENV: TODAY.isoformat()}
    result = runner.invoke(cli_app, ["check"], env=env)
    assert "[red]x[/red]" in result.output


def test_web_ui_never_shows_key_names_as_markdown(data_dir: Path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    evil = "[Klick](http://evil.example) www.evil.example **fett**"
    edit(data_dir, SPRINT, "  anna: 5\n", f"  '{evil}': 1\n  '{evil}': 2\n  anna: 5\n")
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, TODAY.isoformat())
    app_file = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
    at = AppTest.from_file(str(app_file), default_timeout=30)
    at.run()
    at.switch_page("seiten/pruefung.py").run()
    assert not at.exception, at.exception
    shown = [w.value for w in at.warning if "mehrfach" in w.value]
    assert shown
    text = "\n".join(shown)
    # Every punctuation character from the file carries a backslash: Markdown interprets none of it
    assert "\\[Klick\\]\\(http\\:\\/\\/evil\\.example\\)" in text
    assert "\\*\\*fett\\*\\*" in text
    assert "www.evil" not in text


def test_covered_empty_value_is_not_reported():
    # The loader reads a = 5; line 2 is never used, the duplicate itself is still reported
    found = messages("absences:\n  a:\n  a: 5\n")
    assert len(found) == 1 and "steht mehrfach" in found[0]
    found = messages("absences:\n  1:\n  '1': 5\n")
    assert len(found) == 1 and "steht mehrfach" in found[0]
    # If the empty value comes last, it applies and is reported
    found = messages("absences:\n  a: 5\n  a:\n")
    assert any("ist leer" in m for m in found)


def test_alias_duplicate_is_reported_only_once():
    text = "d: &d {k: 1, k: 2}\nx: *d\ny: *d\nz: [*d, *d]\n"
    found = messages(text)
    assert len(found) == 1 and "'d.k'" in found[0]


def test_alias_bomb_with_duplicate_in_sheet_stays_bounded():
    import time

    lines = ["l0: &l0 {k: 1, k: 2}"]
    for n in range(1, 9):
        lines.append(f"l{n}: &l{n} [{', '.join([f'*l{n - 1}'] * 9)}]")
    start = time.monotonic()
    found = messages("\n".join(lines) + "\n")
    assert time.monotonic() - start < 2.5
    assert len(found) <= 52


def test_many_duplicate_keys_are_truncated():
    text = "".join(f"k{i}: 1\nk{i}: 2\n" for i in range(5000))
    found = messages(text)
    assert len(found) == 51
    assert "… und 4950 weitere Hinweise" in found[-1]


def test_row_list_is_truncated():
    [found] = messages("{" + ", ".join(["k: 1"] * 200) + "}\n")
    assert "… und 190 weitere" in found
    assert len(found) < 600


def test_large_valid_file_names_no_anchors():
    text = "".join(f"k{i}: {{a: 1, b: 2}}\n" for i in range(30_000))
    [found] = messages(text)
    assert "zu groß oder zu verschachtelt" in found
    assert "Anker" not in found


def test_too_deep_for_the_loader(monkeypatch):
    from sprintforecast import validate

    def deep(_text):
        raise RecursionError

    monkeypatch.setattr(validate, "compose_yaml", deep)
    [found] = messages("a: 1\n")
    assert "zu tief verschachtelt" in found


def test_recursive_merge_source_does_not_abort():
    found = messages("a: &a\n  <<: *a\n  x: \n")
    assert isinstance(found, list)


def test_unhashable_key_is_skipped(monkeypatch):
    from yaml.constructor import SafeConstructor

    monkeypatch.setattr(SafeConstructor, "construct_object", lambda self, node, deep=False: [1])
    assert messages("{1: a, 2: b, 3: c}\n") == []


def test_displayed_key_is_the_last_entry():
    [found] = messages("{1: a, 1.0: b}\n")
    assert "'1.0'" in found


def test_control_characters_in_the_key_do_not_reach_the_output(data_dir: Path):
    key = '"a\\nb\\e[31mc"'
    edit(data_dir, SPRINT, "  anna: 5\n", f"  {key}: 1\n  {key}: 2\n  anna: 5\n")
    env = {DATA_ENV: str(data_dir), AS_OF_ENV: TODAY.isoformat()}
    result = runner.invoke(cli_app, ["check"], env=env)
    assert "\x1b" not in result.output
    assert "a b" in result.output.replace("\n  ", " ").replace("\n", " ")
    [found] = [m for m in messages(f"absences:\n  {key}: 1\n  {key}: 2\n")]
    assert "\n" not in found and "\x1b" not in found


def loaded_keys(text: str, field: str) -> set[str]:
    """Short keys of ``field`` as the program reads them (the loader's dict, then ``str()``)."""
    import yaml

    from sprintforecast.storage import _YAML_LOADER

    return {str(k) for k in yaml.load(text, Loader=_YAML_LOADER)[field]}


@pytest.mark.parametrize(
    "text",
    [
        "absences:\n  1: 2\n  1.0: 3\n",
        "absences: {1: a, 1.0: b, '1': c}\n",
        "absences: {true: a, 1: b}\n",
        "products: {1: {}, 1.0: {}}\n",
        "expected_absences: {1: 2, 1.0: 3}\n",
    ],
)
def test_abbreviations_equal_in_python_are_a_duplicate(text: str):
    """The loader builds the dict with Python equality (1 == 1.0 == True), only the program forms
    str(): the first key object stays, the last value wins."""
    assert len(loaded_keys(text, text.split(":")[0])) == 1  # the program reads one short key
    [found] = messages(text)
    assert "steht mehrfach" in found


def test_abbreviation_first_key_object_determines_the_text():
    # The loader keeps 1.0 as the key object: "1.0" and "1" remain separate short keys
    text = "absences: {1.0: a, 1: b, '1': c}\n"
    assert loaded_keys(text, "absences") == {"1", "1.0"}
    [found] = messages(text)
    assert "Spalten 12, 20" in found  # only 1.0 and 1, not '1'


def merged(spec: str) -> dict:
    import yaml

    from sprintforecast.storage import _YAML_LOADER

    return yaml.load(BASE + f"m: {{{spec}}}\n", Loader=_YAML_LOADER)["m"]


def test_with_several_merge_keys_the_last_wins():
    """PyYAML appends the sources of several ``<<`` in order; when building the dict, the later
    entry overwrites the earlier one."""
    assert merged("<<: *y, <<: *x") == {"fte": None}  # x (empty) is the last <<
    [found] = member("<<: *y, <<: *x")
    assert "memberships[0].fte" in found
    assert merged("<<: *x, <<: *y") == {"fte": 0.5}
    assert member("<<: *x, <<: *y") == []


def test_three_merge_keys_and_lists_mixed():
    assert merged("<<: *x, <<: *y, <<: *x") == {"fte": None}
    assert len(member("<<: *x, <<: *y, <<: *x")) == 1
    # in a list the first source still wins, across << the last one
    assert merged("<<: *y, <<: [*x, *y]") == {"fte": None}
    assert len(member("<<: *y, <<: [*x, *y]")) == 1
    assert merged("<<: [*x, *y], <<: *y") == {"fte": 0.5}
    assert member("<<: [*x, *y], <<: *y") == []
    # own keys beat every <<
    assert merged("<<: *y, fte: 1, <<: *x") == {"fte": 1}
    assert member("<<: *y, fte: 1, <<: *x") == []
