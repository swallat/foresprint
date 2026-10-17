# SPDX-License-Identifier: EUPL-1.2
"""Seitenleiste „Speichern und teilen“ mit zwei Personen (AppTest, echte Git-Repositories)."""

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


@pytest.fixture
def shared(data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch):
    """Alice (App auf data_dir) und Bob (zweiter Klon) teilen sich einen Server."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    work = tmp_path_factory.mktemp("zwei-personen")
    server = work / "server.git"
    git(work, "init", "-q", "--bare", "-b", "main", str(server))
    root = data_dir.parent
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", str(server))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Start")
    git(root, "push", "-q", "-u", "origin", "main")
    bob = work / "bob"
    git(work, "clone", "-q", str(server), str(bob))
    invalidate_status()
    return root, bob, server


def start(data_dir: Path, monkeypatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def press(at: AppTest, label: str) -> AppTest:
    next(b for b in at.sidebar.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def captions(at: AppTest) -> str:
    return "\n".join(c.value for c in at.sidebar.caption)


def test_status_and_incoming_changes_of_others(shared, data_dir: Path, monkeypatch):
    root, bob, _ = shared
    at = start(data_dir, monkeypatch)
    assert "Serverstand noch nicht geprüft" in captions(at)

    # Bob ändert einen Sprint und teilt
    file = bob / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 8"))
    git(bob, "commit", "-qam", "Korrektur durch Bob")
    git(bob, "push", "-q")

    press(at, "Stand prüfen")
    assert "1 neu von anderen" in captions(at)
    assert any("Korrektur durch Bob" in m.value for m in at.sidebar.markdown)

    press(at, "Speichern und teilen")
    assert any("von anderen übernommen" in s.value for s in at.sidebar.success)
    assert (root / SPRINT).read_text() == file.read_text()


def test_own_changes_are_saved_and_shared(shared, data_dir: Path, monkeypatch):
    root, _bob, server = shared
    file = root / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    at.sidebar.text_input(key="commit_message").set_value("Review korrigiert")
    press(at, "Speichern und teilen")
    assert any("Hochgeladen" in s.value for s in at.sidebar.success)
    assert git(server, "log", "-1", "--format=%s", "main") == "Review korrigiert"
    assert git(root, "status", "--porcelain") == ""


def test_offline_is_explained_and_nothing_is_lost(shared, data_dir: Path, monkeypatch):
    root, _, server = shared
    git(root, "remote", "set-url", "origin", str(server) + "-weg")
    file = root / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Server nicht erreichbar" in errors and "Internetverbindung" in errors
    assert git(root, "status", "--porcelain") == ""  # lokal gesichert
    assert "Server nicht erreichbar" in captions(at)


def make_value_conflict(root: Path, bob: Path) -> Path:
    theirs = bob / SPRINT
    theirs.write_text(theirs.read_text().replace("velocity: 9.75", "velocity: 8.5"))
    git(bob, "commit", "-qam", "Bob")
    git(bob, "push", "-q")
    mine = root / SPRINT
    mine.write_text(mine.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    return mine


def test_conflict_locks_editing_and_is_resolved_in_the_app(shared, data_dir: Path, monkeypatch):
    root, bob, server = shared
    mine = make_value_conflict(root, bob)
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    assert any("Konflikt beim Zusammenführen" in e.value for e in at.sidebar.error)
    # Die Seite ist gesperrt und zeigt statt des Forecasts die Konfliktlösung
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    assert not at.metric
    apply = next(b for b in at.button if b.label == "Entscheidungen übernehmen und teilen")
    assert apply.disabled  # erst nach einer Entscheidung je Eintrag
    radio = at.radio(key="conf-0-0")
    assert any("Meine Änderung: 7" in o for o in radio.options)
    radio.set_value("theirs").run()
    next(b for b in at.button if b.label == "Entscheidungen übernehmen und teilen").click().run()
    assert not at.exception
    assert any("Hochgeladen" in s.value for s in at.sidebar.success)
    assert "velocity: 8.5" in mine.read_text()  # "andere Änderung" gewählt
    assert "velocity: 8.5" in git(server, "show", f"main:{SPRINT.as_posix()}")
    assert git(root, "status", "--porcelain") == ""
    assert at.metric  # Bearbeitung wieder freigegeben


def test_conflict_choose_mine(shared, data_dir: Path, monkeypatch):
    root, bob, server = shared
    mine = make_value_conflict(root, bob)
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    at.radio(key="conf-0-0").set_value("ours").run()
    next(b for b in at.button if b.label == "Entscheidungen übernehmen und teilen").click().run()
    assert "velocity: 7" in mine.read_text()
    assert "velocity: 7" in git(server, "show", f"main:{SPRINT.as_posix()}")


def test_conflict_markers_without_merge_offer_restore(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    sprint = root / SPRINT
    original = sprint.read_text()
    sprint.write_text("<<<<<<< HEAD\nvelocity: 1\n=======\nvelocity: 2\n>>>>>>> origin/main\n")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    next(b for b in at.button if b.label == "Letzten Stand wiederherstellen").click().run()
    assert sprint.read_text() == original
    assert at.metric


def test_stale_form_is_discarded_before_saving(shared, data_dir: Path, monkeypatch):
    """Ändert sich eine Datei, während ein Formular offen ist, wird nicht blind gespeichert."""
    root, _, _ = shared
    at = start(data_dir, monkeypatch)
    at.switch_page("seiten/review.py").run()
    assert not at.exception
    at.selectbox(key="review-sprint").set_value("2026.21").run()
    other = root / "teams" / "demo" / "sprints" / "2026.20.yaml"
    other.write_text(other.read_text().replace("velocity: 9.75", "velocity: 5.0"))  # „von außen“
    at.number_input(key="velocity-2026.21").set_value(9.0)
    next(b for b in at.button if b.label == "Review speichern").click().run()
    assert not at.exception
    assert any("Daten haben sich geändert" in w.value for w in at.warning)
    assert (
        not (root / "teams" / "demo" / "sprints" / "2026.21.yaml").read_text().count("velocity: 9")
    )
    # nach dem Hinweis lässt sich normal speichern
    at.number_input(key="velocity-2026.21").set_value(9.0)
    next(b for b in at.button if b.label == "Review speichern").click().run()
    assert "velocity: 9" in (root / "teams" / "demo" / "sprints" / "2026.21.yaml").read_text()


def test_unfinished_merge_offers_abort(shared, data_dir: Path, monkeypatch):
    root, bob, _ = shared
    theirs = bob / SPRINT
    theirs.write_text(theirs.read_text().replace("velocity: 9.75", "velocity: 8"))
    git(bob, "commit", "-qam", "Bob")
    git(bob, "push", "-q")
    mine = root / SPRINT
    mine.write_text(mine.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    git(root, "commit", "-qam", "Alice")
    git(root, "fetch", "-q")
    subprocess.run(["git", "merge", "origin/main"], cwd=root, capture_output=True)
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert "Zusammenführen unvollständig" in captions(at)
    press(at, "Zusammenführen abbrechen")
    assert git(root, "status", "--porcelain") == ""
    assert "velocity: 7" in mine.read_text()


def test_git_missing_is_explained(data_dir: Path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    at = start(data_dir, monkeypatch)
    assert any("Git ist nicht installiert" in e.value for e in at.sidebar.error)
