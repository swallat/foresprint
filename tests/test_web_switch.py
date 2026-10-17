# SPDX-License-Identifier: EUPL-1.2
"""Aktiver Datenordner sichtbar, Liste zuletzt benutzter Ordner, Wechsel ohne Altlasten."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast import gitsync
from sprintforecast.storage import (
    DATA_ENV,
    MAX_RECENT,
    STICHTAG_ENV,
    forget_data_dir,
    recent_data_dirs,
    save_data_dir,
)

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_recent_folders_are_listed_newest_first_and_limited(tmp_path: Path):
    folders = [tmp_path / f"d{i}" for i in range(MAX_RECENT + 3)]
    for folder in folders:
        folder.mkdir()
        save_data_dir(folder)
    save_data_dir(folders[3])  # erneut benutzt: rückt nach vorn, kein Doppeltes
    recent = recent_data_dirs()
    assert recent[0] == folders[3].resolve() and len(recent) == MAX_RECENT
    assert len({str(p) for p in recent}) == MAX_RECENT
    forget_data_dir(folders[3])
    assert folders[3].resolve() not in recent_data_dirs() and folders[3].exists()


@pytest.fixture
def two_folders(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    git(data_dir, "init", "-q", "-b", "main")
    git(data_dir, "add", "-A")
    git(data_dir, "commit", "-qm", "init")
    second = tmp_path / "zweiter-ordner"
    shutil.copytree(data_dir / "demo", second / "zweit")
    save_data_dir(second)
    save_data_dir(data_dir)
    return data_dir, second


def start(path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(path))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_active_folder_and_branch_are_always_visible(two_folders, monkeypatch):
    first, _ = two_folders
    at = start(first, monkeypatch)
    text = " ".join(m.value for m in at.sidebar.markdown)
    assert first.name in text and "main" in text
    assert team_of(at) == "demo"  # aktives Team


def test_switch_discards_old_form_state_and_caches(two_folders, monkeypatch):
    first, _second = two_folders
    at = start(first, monkeypatch)
    at.switch_page("seiten/review.py").run()
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    at.session_state["probe"] = "Eingabe des alten Ordners"
    at.run()
    assert at.session_state["probe"]

    switch = next(e for e in at.sidebar.expander if e.label == "Datenordner wechseln")
    assert switch is not None
    target = at.sidebar.selectbox(key="switch-target")
    assert any("zweiter-ordner" in o for o in target.options)
    next(b for b in at.sidebar.button if b.label == "Wechseln").click().run()
    assert not at.exception, at.exception

    assert Path(monkeypatch_env(DATA_ENV)).name == "zweiter-ordner"
    assert "probe" not in at.session_state  # alter Formularzustand verworfen
    assert team_of(at) == "zweit"  # Team des neuen Ordners
    assert "zweiter-ordner" in " ".join(m.value for m in at.sidebar.markdown)
    # Der alte Ordner steht jetzt in der Liste der zuletzt benutzten
    assert any(first.name in o for o in at.sidebar.selectbox(key="switch-target").options)
    # kein Git-Repository im zweiten Ordner: Branch nicht angezeigt, kein Absturz
    assert not any("Branch `" in m.value for m in at.sidebar.markdown)


def monkeypatch_env(name: str) -> str:
    import os

    return os.environ[name]


def test_switch_keeps_changes_of_old_folder_and_git_state_is_not_mixed(two_folders, monkeypatch):
    first, _second = two_folders
    sprint = first / "demo" / "sprints" / "2026.20.yaml"
    sprint.write_text(sprint.read_text().replace("velocity: 9.75", "velocity: 1.0"))
    at = start(first, monkeypatch)
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    caption = " ".join(c.value for c in at.sidebar.caption)
    next(b for b in at.sidebar.button if b.label == "Wechseln").click().run()
    assert "velocity: 1.0" in sprint.read_text()  # nichts verloren
    assert not any("offene Änderung" in e.label for e in at.sidebar.expander)  # anderer Ordner
    assert caption and git(first, "status", "--porcelain").startswith("M")
    # Zurückwechseln zeigt die offene Änderung wieder
    next(b for b in at.sidebar.button if b.label == "Wechseln").click().run()
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    assert gitsync.state(first).branch == "main"


def test_data_dir_page_lists_and_forgets_recent_folders(two_folders, monkeypatch):
    first, second = two_folders
    at = start(first, monkeypatch)
    at.switch_page("seiten/datenordner.py").run()
    assert not at.exception
    assert any("zweiter-ordner" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Entfernen").click().run()
    assert second.resolve() not in recent_data_dirs() and second.exists()


def team_of(at: AppTest) -> str:
    return next(s for s in at.sidebar.selectbox if s.label == "Team").value
