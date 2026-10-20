# SPDX-License-Identifier: EUPL-1.2
"""UI of the Git sync and the data folder switcher: review findings (AppTest)."""

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast.git import invalidate_status
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
SPRINT = Path("teams") / "demo" / "sprints" / "2026.20.yaml"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def start(path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(path))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"seiten/{page}.py").run()
    assert not at.exception, at.exception
    return at


def main_button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def tag_box(at: AppTest):
    return next(s for s in at.main.selectbox if s.label == "Tag löschen")


def sidebar_button(at: AppTest, label: str):
    return next(b for b in at.sidebar.button if b.label == label)


def diverge(root: Path) -> None:
    """Two branches change the same line; in the end ``andere`` or ``main`` remains."""
    git(root, "checkout", "-q", "-b", "andere")
    other = root / SPRINT
    other.write_text(other.read_text().replace("velocity: 9.75", "velocity: 8"))
    git(root, "commit", "-qam", "Andere")
    git(root, "checkout", "-q", "main")
    mine = root / SPRINT
    mine.write_text(mine.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    git(root, "commit", "-qam", "Meine")


def open_merge(root: Path) -> None:
    diverge(root)
    subprocess.run(["git", "merge", "andere"], cwd=root, capture_output=True)
    invalidate_status()


# --- W1: own saving never counts as a foreign change ------------------------------------


def test_own_save_with_rerun_is_not_reported_as_foreign_change(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = goto(start(data_dir, monkeypatch), "planning")
    at.selectbox(key="planning-sprint").set_value("2026.23").run()
    main_button(at, "Niemand fehlt – bestätigen und weiter").click().run()
    assert not at.exception, at.exception
    assert (data_dir / "demo" / "sprints" / "2026.23.yaml").exists()
    assert not any("Daten haben sich geändert" in w.value for w in at.warning)
    assert at.selectbox(key="planning-sprint").value == "2026.23"  # inputs not discarded
    assert at.radio(key="planning-step").value == 1


# --- W2: the data folder applies per session --------------------------------------------


def test_folder_switch_does_not_leak_into_other_sessions(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    tab1 = start(data_dir, monkeypatch)
    tab2 = goto(start(data_dir, monkeypatch), "review")
    tab2.selectbox(key="review-sprint").set_value("2026.21").run()
    tab2.number_input(key="velocity-2026.21").set_value(9.0)

    sidebar_button(tab1, "Wechseln").click().run()  # tab 1 switches to the second folder
    assert not tab1.exception, tab1.exception

    main_button(tab2, "Review speichern").click().run()  # tab 2 keeps saving in folder A
    assert not tab2.exception, tab2.exception
    assert "velocity: 9" in (data_dir / "demo" / "sprints" / "2026.21.yaml").read_text()
    assert "velocity: 9.0" not in (second_folder / "zweit" / "sprints" / "2026.21.yaml").read_text()
    assert "zweiter-ordner" in " ".join(m.value for m in tab1.sidebar.markdown)
    assert "zweiter-ordner" not in " ".join(m.value for m in tab2.sidebar.markdown)


def test_header_shows_parent_folder(repo: Path, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    text = " ".join(m.value for m in at.sidebar.markdown)
    assert f"`{repo.name}/teams`" in text


# --- W3: "Use without Git" is not a dead end --------------------------------------------


def test_without_git_in_empty_folder_leads_to_new_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    assert [h.value for h in at.header] == ["Datenordner"]
    at.session_state["offer-init"] = str(empty)
    at.run()
    main_button(at, "Ohne Git verwenden").click().run()
    assert not at.exception, at.exception
    assert [h.value for h in at.header] != ["Datenordner"]  # not the setup again
    goto(at, "neues_team")
    assert at.text_input  # "New team" is reachable


# --- W4: an open merge locks all writing pages ------------------------------------------


@pytest.mark.parametrize("page", ["neues_team", "review"])
def test_open_merge_locks_writing_pages(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, page: str
):
    open_merge(repo)
    at = goto(start(data_dir, monkeypatch), page)
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    assert not any(b.label == "Team anlegen" for b in at.button)


def test_history_buttons_are_disabled_with_open_merge(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    git(repo, "tag", "alt")
    open_merge(repo)
    at = goto(start(data_dir, monkeypatch), "verlauf")
    assert any("Zusammenführen ist noch offen" in w.value for w in at.warning)
    for label in ("Diesen Stand wiederherstellen", "Diese Änderung zurücknehmen"):
        assert main_button(at, label).disabled, label
    assert not at.error


def test_open_rebase_locks_pages(repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    diverge(repo)
    git(repo, "checkout", "-q", "andere")
    subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True)
    invalidate_status()
    at = goto(start(data_dir, monkeypatch), "review")
    assert [h.value for h in at.header] == ["Konflikte lösen"]


# --- W5: tags and commit message belong to the folder -----------------------------------


def test_pending_tags_and_message_survive_switching_back(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    at.session_state["pending_tags"] = ["demo/2026.20"]
    at.session_state["commit_message"] = "Review 20"
    at.run()
    sidebar_button(at, "Wechseln").click().run()
    # The second folder starts without the tags and the message of the first ...
    assert "pending_tags" not in at.session_state or not at.session_state["pending_tags"]
    assert at.session_state["commit_message"] != "Review 20"
    # ... and carries its own message.
    at.session_state["commit_message"] = "Zweiter Ordner"
    at.run()
    sidebar_button(at, "Wechseln").click().run()  # back
    assert at.session_state["pending_tags"] == ["demo/2026.20"]
    assert at.session_state["commit_message"] == "Review 20"
    sidebar_button(at, "Wechseln").click().run()  # into the second again
    assert at.session_state["commit_message"] == "Zweiter Ordner"


# --- W6: delete confirmation for tags applies once and only to the chosen tag ------------


def test_tag_delete_confirmation_is_per_tag_and_single_use(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    git(repo, "tag", "a")
    git(repo, "tag", "b")
    invalidate_status()
    at = goto(start(data_dir, monkeypatch), "verlauf")
    tag_box(at).set_value("a").run()
    at.checkbox[-1].check().run()
    tag_box(at).set_value("b").run()
    assert not at.checkbox[-1].value
    assert main_button(at, "Tag löschen").disabled
    # After deleting, the next selection is unconfirmed again
    at.checkbox[-1].check().run()
    main_button(at, "Tag löschen").click().run()
    assert git(repo, "tag").split() == ["a"]
    assert not at.checkbox[-1].value
    assert main_button(at, "Tag löschen").disabled


# --- K1: notices appear on every page ---------------------------------------------------


def test_flash_is_shown_on_any_page(repo: Path, data_dir: Path, monkeypatch):
    at = goto(start(data_dir, monkeypatch), "forecast")
    at.session_state["flash"] = [("success", "Meldung K1")]
    at.run()
    assert any("Meldung K1" in s.value for s in at.success)
    assert "flash" not in at.session_state or not at.session_state["flash"]


# --- K2: understandable Git errors -----------------------------------------------------


def test_git_error_in_sidebar_is_explained(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    (repo / ".git" / "index").write_bytes(b"kaputt")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    sidebar_warning = " ".join(w.value for w in at.sidebar.warning)
    assert "Datei-Manager" in sidebar_warning
    assert not any(c.value.startswith("Git: fatal") for c in at.sidebar.caption)
    assert not any("(0)" in e.label for e in at.sidebar.expander)


# --- K3: folder check of the switch list is briefly remembered ------------------------------


def test_recent_folder_check_is_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sprintforecast.web import ui

    calls: list[Path] = []
    real = Path.is_dir

    def counting(self: Path) -> bool:
        calls.append(self)
        return real(self)

    folder = tmp_path / "ordner"
    folder.mkdir()
    ui._DIR_CHECKED.clear()
    monkeypatch.setattr(Path, "is_dir", counting)
    assert ui._dir_exists(folder) and ui._dir_exists(folder) and ui._dir_exists(folder)
    assert calls.count(folder) == 1
