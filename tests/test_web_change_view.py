# SPDX-License-Identifier: EUPL-1.2
"""The "What has changed?" view in the Git area (AppTest, real Git repositories)."""

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast import diff
from sprintforecast.git import GitError, invalidate_status
from sprintforecast.storage import AS_OF_ENV, DATA_ENV
from sprintforecast.yamlmerge import MISSING

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
SPRINT = Path("teams") / "demo" / "sprints" / "2026.20.yaml"
TITLE = "Was hat sich geändert?"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def start(data_dir: Path, monkeypatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(AS_OF_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def view(at: AppTest) -> str:
    """Everything the view outputs as Markdown or label."""
    return "\n".join([m.value for m in at.sidebar.markdown] + [c.value for c in at.sidebar.caption])


def commit_extra(root: Path, name: str, text: str) -> Path:
    file = root / "teams" / name
    file.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "extra")
    invalidate_status()
    return file


def test_changed_value_is_shown_with_before_and_after(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert TITLE in view(at)
    assert "`demo/sprints/2026.20.yaml` – geändert" in view(at)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert list(frame.columns) == ["Feld", "Vorher", "Nachher"]
    row = frame[frame["Feld"].str.endswith("velocity")].iloc[0]
    assert (row["Vorher"], row["Nachher"]) == ("9.75", "7.0")


def test_no_view_without_changes(repo, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    assert TITLE not in view(at)


def test_new_deleted_and_unreadable_files(repo, data_dir: Path, monkeypatch):
    (data_dir / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    (data_dir / "bericht.xlsx").write_bytes(b"PK\x03\x04")
    (repo / SPRINT).unlink()
    invalidate_status()
    at = start(data_dir, monkeypatch)
    text = view(at)
    assert "`neu.yaml` – neu" in text
    assert "`bericht.xlsx` – neu" in text
    assert "`demo/sprints/2026.20.yaml` – gelöscht" in text
    assert text.count("keine Wertansicht") == 1  # only the Excel file
    assert len(at.sidebar.dataframe) == 0  # new and deleted: only the kind


def test_foreign_text_is_never_rendered_as_markdown(repo, data_dir: Path, monkeypatch):
    evil = "[Klick](http://evil.example) **fett** www.evil.example"
    file = commit_extra(repo, "**fett**.yaml", "wert: alt\n")
    file.write_text(f"wert: '{evil}'\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    # The file name is shown as code, the value only in the table (no Markdown, no label).
    assert "`**fett**.yaml` – geändert" in view(at)
    assert evil not in view(at)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert frame.iloc[0]["Nachher"] == f"{chr(39)}{evil}{chr(39)}"


def test_values_are_shortened_and_missing_is_a_dash(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "x.yaml", "weg: 1\n")
    long = list(range(100))
    file.write_text(f"liste: {long}\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    rows = {r["Feld"]: r for _, r in frame.iterrows()}
    assert rows["weg"]["Nachher"] == "–" and rows["weg"]["Vorher"] == "1"
    assert rows["liste"]["Vorher"] == "–"
    assert len(rows["liste"]["Nachher"]) == 80 and rows["liste"]["Nachher"].endswith("…")


def test_rows_and_files_are_limited(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "viel.yaml", "".join(f"k{i}: 0\n" for i in range(40)))
    file.write_text("".join(f"k{i}: 1\n" for i in range(40)), encoding="utf-8")
    for i in range(30):
        (data_dir / f"neu{i:02}.txt").write_text("x", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert len(frame) == 31 and frame.iloc[-1]["Feld"] == "… und 10 weitere"
    # 31 files (viel.yaml and 30 new ones): 25 shown, 6 more
    assert "… und 6 weitere" in view(at)
    assert sum(1 for m in at.sidebar.markdown if " – " in m.value) == 25


def test_second_run_reads_nothing_again_until_invalidated(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    calls: list[Path] = []
    real = diff.file_changes

    def counting(path: Path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(diff, "file_changes", counting)
    at = start(data_dir, monkeypatch)
    assert len(calls) == 1
    at.run()
    assert len(calls) == 1  # unchanged: from the cache
    invalidate_status()
    at.run()
    assert len(calls) == 2
    file.write_text(file.read_text().replace("velocity: 7.0", "velocity: 6.5"))  # same size
    at.run()
    assert len(calls) == 3  # modification time of the working file changed
    assert any(d.value["Nachher"].eq("6.5").any() for d in at.sidebar.dataframe)


def test_git_error_hides_only_the_view(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()

    def broken(path: Path):
        raise GitError("kaputt", kind="unsafe_directory")

    monkeypatch.setattr(diff, "file_changes", broken)
    at = start(data_dir, monkeypatch)
    assert TITLE not in view(at)
    assert "nicht verfügbar" in view(at)
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    assert any(b.label == "Änderungen committen" for b in at.sidebar.button)
    assert any(i.key == "commit_message" for i in at.sidebar.text_input)


def test_git_buttons_stay_outside_the_expander(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    git_box = next(e for e in at.sidebar.expander if "offene Änderung" in e.label)
    assert not git_box.button and not git_box.text_input
    assert any(b.label == "Änderungen committen" for b in at.sidebar.button)


def cells(at: AppTest) -> dict[str, tuple[str, str]]:
    """Field -> (before, after) from all tables of the view."""
    out: dict[str, tuple[str, str]] = {}
    for d in at.sidebar.dataframe:
        for _, r in d.value.iterrows():
            out[r["Feld"]] = (r["Vorher"], r["Nachher"])
    return out


def test_date_as_key_does_not_crash(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "tage.yaml", "a:\n  2026-01-01: 1\nl:\n  - 2026-01-01: 1\n")
    file.write_text("a: 5\nl:\n  - 2026-01-01: 2\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)  # checks: no exception
    shown = cells(at)
    assert shown["a"] == ("{2026-01-01: 1}", "5")
    assert shown["l"] == ("[{2026-01-01: 1}]", "[{2026-01-01: 2}]")


def test_before_and_after_never_look_alike(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "typen.yaml", "a: 1\nb: null\nc: x y\nd: true\n")
    file.write_text("a: '1'\nb: 'None'\nc: 'x  y'\nd: 'true'\n", encoding="utf-8")
    invalidate_status()
    shown = cells(start(data_dir, monkeypatch))
    assert shown["a"] == ("1", "'1'")
    assert shown["b"] == ("null", "None")
    assert shown["c"][0] != shown["c"][1]  # whitespace is not collapsed
    assert shown["d"] == ("true", "'true'")


def test_change_at_the_end_of_a_long_value_is_visible(repo, data_dir: Path, monkeypatch):
    old = list(range(100))
    file = commit_extra(repo, "lang.yaml", f"l: {old}\n")
    file.write_text(f"l: {[*old[:-1], 1000]}\n", encoding="utf-8")
    invalidate_status()
    before, after = cells(start(data_dir, monkeypatch))["l"]
    assert before != after and before.startswith("…") and after.startswith("…")
    assert before.endswith("99]") and after.endswith("1000]")
    assert len(before) <= 80 and len(after) <= 80


def test_renamed_files_show_old_and_new_name(repo, data_dir: Path, monkeypatch):
    commit_extra(repo, "alt1.yaml", "a: 1\n")
    commit_extra(repo, "alt2.yaml", "a: 1\n")
    git(repo, "mv", "teams/alt1.yaml", "teams/neu1.yaml")
    git(repo, "mv", "teams/alt2.yaml", "teams/neu2.yaml")
    (data_dir / "neu2.yaml").write_text("a: 2\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    text = view(at)
    assert "umbenannt: `alt1.yaml` → `neu1.yaml`" in text
    assert "alt2.yaml` → `neu2.yaml`" in text
    assert cells(at)["a"] == ("1", "2")  # only the changed rename has values


def test_staged_then_deleted_files(repo, data_dir: Path, monkeypatch):
    changed = commit_extra(repo, "md.yaml", "a: 1\n")
    changed.write_text("a: 2\n", encoding="utf-8")
    git(repo, "add", "teams/md.yaml")
    changed.unlink()
    added = data_dir / "ad.yaml"
    added.write_text("a: 1\n", encoding="utf-8")
    git(repo, "add", "teams/ad.yaml")
    added.unlink()
    invalidate_status()
    text = view(start(data_dir, monkeypatch))
    assert "`md.yaml` – gelöscht" in text
    assert "`ad.yaml` – neu, danach gelöscht" in text


def test_table_export_cannot_become_a_formula(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "formel.yaml", "a: 1\nb: 1\nc: 1\n")
    file.write_text("a: -x\nb: -5\nc: '@SUM(1)'\n=cmd: 1\n", encoding="utf-8")
    invalidate_status()
    shown = cells(start(data_dir, monkeypatch))
    assert shown["a"][1] == "'-x"
    assert shown["b"][1] == "-5"  # numbers stay
    assert shown["c"][1].lstrip("'").startswith("@")
    assert "'=cmd" in shown  # the field name too


def test_limits_at_the_exact_boundary(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "viel.yaml", "".join(f"k{i}: 0\n" for i in range(31)))
    file.write_text("".join(f"k{i}: 1\n" for i in range(30)) + "k30: 0\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert len(frame) == 30 and "weitere" not in " ".join(frame["Feld"])
    file.write_text("".join(f"k{i}: 1\n" for i in range(31)), encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert len(frame) == 31 and frame.iloc[-1]["Feld"] == "… und 1 weitere"


@pytest.mark.parametrize(("count", "caption"), [(25, False), (26, True)])
def test_file_limit_at_the_exact_boundary(repo, data_dir, monkeypatch, count, caption):
    for i in range(count):
        (data_dir / f"n{i:02}.txt").write_text("x", encoding="utf-8")
    invalidate_status()
    text = view(start(data_dir, monkeypatch))
    assert ("… und 1 weitere" in text) is caption
    assert ("weitere" in text) is caption


def test_huge_hex_integer_does_not_crash(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "gross.yaml", "n: 0x" + "F" * 5000 + "\nm: 1\n")
    file.write_text("n: 0x" + "E" + "F" * 4999 + "\nm: 2\n", encoding="utf-8")
    invalidate_status()
    shown = cells(start(data_dir, monkeypatch))  # no exception
    before, after = shown["n"]
    assert "Bit" in before and before != after
    assert shown["m"] == ("1", "2")


def test_big_values_are_bounded_and_fast():
    import time

    from sprintforecast.web import ui

    started = time.monotonic()
    big = list(range(1_000_000))
    a, b = ui._view_pair(big, big[:-1])
    texts = {f"k{i}": "x" * 150_000 for i in range(30)}
    ui._view_pair(texts, {**texts, "k0": "y"})
    assert time.monotonic() - started < 2
    assert len(a) <= 80 and b.startswith(a) and "(" in b  # same excerpt: notice


def test_sets_binary_and_unknown_types_are_bounded():
    import base64
    import time

    import yaml

    from sprintforecast.web import ui

    members = ", ".join(f"m{i}" for i in range(100_000))
    data = base64.b64encode(bytes(3_000_000)).decode()
    loaded = yaml.safe_load(f"s: !!set {{{members}}}\nb: !!binary {data}\n")
    started = time.monotonic()
    for value in (loaded["s"], loaded["b"], object()):
        a, b = ui._view_pair(value, MISSING)
        assert len(a) <= 80 and b == "–"
    assert ui._view_text(loaded["b"]) == "bytes, 3000000 Byte"
    assert len(ui._view_text(loaded["s"])) < 20_000
    assert time.monotonic() - started < 2


def test_same_excerpt_but_different_values_gets_the_hint():
    from sprintforecast.web import ui

    a, b = ui._view_pair(list(range(2000)), [*range(1999), 5])
    assert a != b and "(" in b  # both excerpts equal: notice instead of identical cells


def test_rows_are_computed_once_until_invalidated(repo, data_dir: Path, monkeypatch):
    from sprintforecast.web import ui

    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    calls: list[object] = []
    real = ui._view_pair

    def counting(old, new):
        calls.append(old)
        return real(old, new)

    monkeypatch.setattr(ui, "_view_pair", counting)
    at = start(data_dir, monkeypatch)
    assert len(calls) == 1
    at.sidebar.text_input(key="commit_message").set_value("Tippen")
    at.run()
    assert len(calls) == 1  # keystroke: no recalculation
    invalidate_status()
    at.run()
    assert len(calls) == 2


def test_note_for_a_changed_file_without_value_changes(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "ordnung.yaml", "a: 1\nb: 2\n")
    file.write_text("b: 2\na: 1\n", encoding="utf-8")
    (data_dir / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    git(repo, "mv", "teams/ordnung.yaml", "teams/umbenannt.yaml")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    notes = [c.value for c in at.sidebar.caption if "keine Wertänderung" in c.value]
    assert len(notes) == 1  # only the changed (and renamed) file, not the new one


def test_pure_rename_and_new_file_get_no_note(repo, data_dir: Path, monkeypatch):
    commit_extra(repo, "ruhig.yaml", "a: 1\n")
    git(repo, "mv", "teams/ruhig.yaml", "teams/laut.yaml")
    (data_dir / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert not [c for c in at.sidebar.caption if "keine Wertänderung" in c.value]


def test_long_field_names_are_shortened(repo, data_dir: Path, monkeypatch):
    key = "k" * 300
    file = commit_extra(repo, "lang.yaml", f"{key}: 1\n")
    file.write_text(f"{key}: 2\n", encoding="utf-8")
    invalidate_status()
    (label,) = cells(start(data_dir, monkeypatch))
    assert label == "k" * 119 + "…"


def test_a_value_that_cannot_be_shown_does_not_stop_the_page():
    from sprintforecast.web import ui

    class Bad:
        def __repr__(self) -> str:
            raise ValueError("kaputt")

    assert ui._view_text(Bad()) == ui.t("(value cannot be shown)")


def test_every_formula_prefix_is_guarded_and_numbers_are_not():
    from sprintforecast.web import ui

    for ch in "=+-@":
        assert ui._formula_safe(f"{ch}x") == f"'{ch}x"
    assert ui._formula_safe("+1+2") == "'+1+2" and ui._formula_safe("+5", 5) == "'+5"
    assert ui._formula_safe("-5", -5) == "-5" and ui._formula_safe("-1.5", -1.5) == "-1.5"
    # The short form of large numbers and ``-.inf`` are not numbers in the number format
    assert ui._view_pair(1, -(10**60))[1].startswith("'-0x")
    assert ui._view_pair(1, float("-inf"))[1] == "'-.inf"


def test_rows_memory_is_bounded():
    from sprintforecast.diff import FileChange, ValueChange
    from sprintforecast.web import ui

    ui._ROWS.clear()
    for _ in range(ui._ROWS_MAX * 2 + 5):
        ui._file_rows(FileChange("f.yaml", "M", (ValueChange(("a",), 1, 2),)))
        assert len(ui._ROWS) <= ui._ROWS_MAX
    ui._ROWS.clear()


def test_files_beyond_the_size_budget_are_marked(repo, data_dir: Path, monkeypatch):
    from sprintforecast import diff as diff_module

    files = [commit_extra(repo, name, "a: 1\n") for name in ("eins.yaml", "zwei.yaml")]
    for file in files:
        file.write_text("a: 2\n", encoding="utf-8")
    invalidate_status()
    monkeypatch.setattr(diff_module, "_BYTES_BUDGET", 12)  # one file: HEAD and working state
    at = start(data_dir, monkeypatch)
    notes = [c.value for c in at.sidebar.caption if "nicht ausgewertet" in c.value]
    assert len(notes) == 1 and len(at.sidebar.dataframe) == 1


def test_clipping_offset_and_lengthening():
    from sprintforecast.web import ui

    a, b = ui._view_pair("x" * 30 + "A" * 100, "x" * 30 + "B" * 100)
    assert a == "…" + "x" * 10 + "A" * 68 + "…" and b == "…" + "x" * 10 + "B" * 68 + "…"
    a, b = ui._view_pair("x" * 100, "x" * 100 + "Z")
    assert (a, b) == ("…" + "x" * 10, "…" + "x" * 10 + "Z")
    # Exactly 80 characters: not shortened, not even at the start
    a, b = ui._view_pair("a" * 80, "a" * 79 + "b")
    assert (a, b) == ("a" * 80, "a" * 79 + "b")
    a, b = ui._view_pair("a" * 81, "a" * 80 + "b")
    assert a.startswith("…") and len(a) <= 80


def test_english_view(repo, data_dir: Path, monkeypatch):
    monkeypatch.setenv("FORESPRINT_LANG", "en")
    file = commit_extra(repo, "viel.yaml", "".join(f"k{i}: 0\n" for i in range(31)))
    file.write_text("".join(f"k{i}: 1\n" for i in range(31)), encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert "What has changed?" in view(at)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert list(frame.columns) == ["Field", "Before", "After"]
    assert frame.iloc[-1]["Field"] == "… and 1 more"


def test_view_helpers():
    from datetime import date

    from sprintforecast.web import ui
    from sprintforecast.yamlmerge import MISSING

    exact, longer = "a" * 80, "a" * 81
    assert ui._view_pair(exact, MISSING) == (exact, "–")
    assert ui._view_pair(longer, MISSING)[0] == "a" * 79 + "…"
    assert ui._view_text(["Büro", date(2026, 1, 1), True, None]) == "[Büro, 2026-01-01, true, null]"
    assert ui._view_clean("a\nb\tc\u202ed\x07") == "a⏎b⇥cd "
    # Equal right after cleaning: notice instead of seemingly identical cells
    a, b = ui._view_pair("ab", "a\u202eb")
    assert a == "ab" and b.startswith("ab (") and len(b) > 4
    assert ui._formula_safe("=1", "=1") == "'=1" and ui._formula_safe("-1", -1) == "-1"
    assert ui._formula_safe("x") == "x" and ui._formula_safe("") == ""
    assert ui._view_text(object()).startswith("<object")  # no crash on unknown input


def test_view_name_for_data_folder_equal_to_repository_root(tmp_path: Path):
    from sprintforecast.web import ui

    root = tmp_path.resolve()
    assert ui._view_name(root, "x.yaml", root) == "x.yaml"
    assert ui._view_name(root / "teams", "teams/a/x.yaml", root) == "a/x.yaml"
    assert ui._view_name(root / "teams", "anders/x.yaml", root) == "anders/x.yaml"
    assert ui._view_name(root, "x.yaml", None) == "x.yaml"


def test_commit_message_is_suggested_from_the_change(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    message = at.sidebar.text_input(key="commit_message").value
    assert "2026.20.yaml" in message and "9.75 → 7.0" in message
    # An own text is kept when the changes move on ...
    at.sidebar.text_input(key="commit_message").set_value("Mein Text")
    at.run()
    file.write_text(file.read_text().replace("velocity: 7.0", "velocity: 8.0"))
    invalidate_status()
    at.run()
    assert at.sidebar.text_input(key="commit_message").value == "Mein Text"


def test_suggested_message_follows_the_changes(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    file.write_text(file.read_text().replace("velocity: 7.0", "velocity: 8.25"))
    invalidate_status()
    at.run()
    assert "9.75 → 8.25" in at.sidebar.text_input(key="commit_message").value
