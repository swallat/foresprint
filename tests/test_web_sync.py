# SPDX-License-Identifier: EUPL-1.2
"""Seitenleiste „Speichern und teilen“ mit zwei Personen (AppTest, echte Git-Repositories)."""

import subprocess
from pathlib import Path

import pytest
from gitrepos import assume_foreign_owner

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
    root, _, _server = shared
    git(root, "remote", "set-url", "origin", "http://127.0.0.1:1/r.git")
    file = root / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Server nicht erreichbar" in errors and "Internetverbindung" in errors
    assert git(root, "status", "--porcelain") == ""  # lokal gesichert
    assert "Server nicht erreichbar" in captions(at)


def test_wrong_address_is_not_explained_as_offline(shared, data_dir: Path, monkeypatch):
    """Das Repository gibt es unter der Adresse nicht (z. B. umbenannt): Der nächste Schritt ist
    die Adresse, nicht Internet oder VPN."""
    root, _, server = shared
    git(root, "remote", "set-url", "origin", str(server) + "-weg")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Repository nicht gefunden" in errors and "Adresse" in errors
    assert "Server nicht erreichbar" not in errors and "VPN" not in errors
    assert "Server nicht erreichbar" not in captions(at)
    assert "Server meldet: Repository nicht gefunden" in captions(at)


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
    assert at.header[0].value == "Was möchtest du tun?"  # Bearbeitung wieder freigegeben


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
    assert at.header[0].value == "Was möchtest du tun?"


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


def detach_with_open_change(root: Path, orphan_commit: bool = False) -> None:
    """Lose auf dem Stand vor der letzten Änderung von ``main``, mit offener Änderung an derselben
    Datei (der Wechsel zurück würde sie überschreiben); optional mit einem Commit ohne Branch."""
    sprint = root / SPRINT
    original = sprint.read_text(encoding="utf-8")
    sprint.write_text(original.replace("velocity: 9.75", "velocity: 8"), encoding="utf-8")
    git(root, "commit", "-qam", "Neuer Stand")
    git(root, "checkout", "-q", "--detach", "HEAD~1")
    if orphan_commit:
        (root / "teams" / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "auf losem Stand")
    sprint.write_text(original.replace("velocity: 9.75", "velocity: 99"), encoding="utf-8")
    invalidate_status()


def test_reattach_with_open_changes_explains_the_way_out(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    detach_with_open_change(root)
    at = start(data_dir, monkeypatch)
    press(at, "Zurück auf den Branch")
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Kein Branch ausgewählt (detached HEAD)" in errors
    assert "Änderungen und Verlauf" in errors and "gehen dabei verloren" in errors
    assert "zuerst committen" not in errors and "außerhalb des Datenordners" not in errors
    assert "velocity: 99" in (root / SPRINT).read_text(encoding="utf-8")  # nichts überschrieben


def test_reattach_names_the_rescue_branch(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    detach_with_open_change(root, orphan_commit=True)
    git(root, "checkout", "--", ".")  # keine offene Änderung mehr
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Zurück auf den Branch")
    rescue = git(root, "branch", "--list", "rettung-*", "--format=%(refname:short)")
    assert rescue.startswith("rettung-")
    shown = " ".join(s.value for s in [*at.success, *at.sidebar.success])
    assert "Zurück auf den Branch main." in shown
    assert f"Rettungsbranch `{rescue}`" in shown


def test_reattach_without_orphan_commits_names_no_rescue_branch(
    shared, data_dir: Path, monkeypatch
):
    root, _, _ = shared
    git(root, "checkout", "-q", "--detach")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Zurück auf den Branch")
    shown = " ".join(s.value for s in [*at.success, *at.sidebar.success])
    assert "Zurück auf den Branch main." in shown and "Rettungsbranch" not in shown


def test_git_missing_is_explained(data_dir: Path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    at = start(data_dir, monkeypatch)
    assert any("Git ist nicht installiert" in e.value for e in at.sidebar.error)


def test_unsafe_directory_is_named_in_the_sidebar_and_on_the_history_page(
    shared, data_dir: Path, monkeypatch
):
    """Git lehnt den Ordner ab (anderer Besitzer): Die Oberfläche sagt das, statt „liegt in
    keinem Git-Repository“."""
    root, _, _ = shared
    assume_foreign_owner(monkeypatch, root)
    at = start(data_dir, monkeypatch)
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Git hält den Ordner für unsicher" in errors and "Betreuung des Rechners" in errors
    assert "keinem Git-Repository" not in captions(at)
    at.switch_page("seiten/verlauf.py").run()
    assert not at.exception, at.exception
    assert "Git hält den Ordner für unsicher" in " ".join(e.value for e in at.main.error)
    assert not [i for i in at.main.info if "keinem Git-Repository" in i.value]


def open_history(at: AppTest) -> AppTest:
    at.switch_page("seiten/verlauf.py").run()
    assert not at.exception, at.exception
    return at


def main_button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_discard_asks_and_shows_what_is_lost(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    sprint = root / SPRINT
    original = sprint.read_text()
    sprint.write_text(original.replace("velocity: 9.75", "velocity: 1.0"))
    (root / "teams" / "neu.yaml").write_text("x: 1\n")
    invalidate_status()
    at = open_history(start(data_dir, monkeypatch))
    assert len(at.checkbox) == 2  # je Datei eine Auswahl
    main_button(at, "Alles verwerfen …").click().run()
    warning = " ".join(w.value for w in at.warning)
    assert "geht verloren" in warning and "2026.20.yaml" in warning and "neu.yaml" in warning
    assert main_button(at, "Jetzt verwerfen").disabled  # erst nach Bestätigung
    assert sprint.read_text() != original  # noch nichts passiert
    at.checkbox(key="discard-confirm").check().run()
    main_button(at, "Jetzt verwerfen").click().run()
    assert not at.exception
    assert sprint.read_text() == original and not (root / "teams" / "neu.yaml").exists()
    assert any("Änderungen verworfen" in s.value for s in at.success)


def test_discard_single_file_only(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    sprint = root / SPRINT
    sprint.write_text(sprint.read_text().replace("velocity: 9.75", "velocity: 1.0"))
    (root / "teams" / "neu.yaml").write_text("x: 1\n")
    invalidate_status()
    at = open_history(start(data_dir, monkeypatch))
    labels = [c.label for c in at.checkbox]
    chosen = next(i for i, label in enumerate(labels) if "neu.yaml" in label)
    at.checkbox(key=f"disc-{chosen}").check()
    for i in range(len(labels)):
        if i != chosen:
            at.checkbox(key=f"disc-{i}").uncheck()
    main_button(at, "Ausgewählte verwerfen …").click().run()
    at.checkbox(key="discard-confirm").check().run()
    main_button(at, "Jetzt verwerfen").click().run()
    assert not (root / "teams" / "neu.yaml").exists()
    assert "velocity: 1.0" in sprint.read_text()  # andere Datei bleibt


def test_history_restore_and_undo_in_the_app(shared, data_dir: Path, monkeypatch):
    root, _, _ = shared
    sprint = root / SPRINT
    original = sprint.read_text()
    bad = original.replace("velocity: 9.75", "velocity: 1.0")
    sprint.write_text(bad)
    git(root, "commit", "-qam", "Fehlerhafte Eingabe")
    invalidate_status()
    at = open_history(start(data_dir, monkeypatch))
    entries = at.selectbox(key=f"history-entry-{root / 'teams' / 'demo'}")
    assert "Fehlerhafte Eingabe" in entries.options[0]
    entries.select_index(1).run()  # der Stand davor
    main_button(at, "Diesen Stand wiederherstellen").click().run()
    assert not at.exception
    assert sprint.read_text() == original
    assert any("Wiederhergestellt" in s.value for s in at.success)
    # Die Wiederherstellung steht jetzt oben im Verlauf und lässt sich zurücknehmen
    entries = at.selectbox(key=f"history-entry-{root / 'teams' / 'demo'}")
    assert "wiederhergestellt" in entries.options[0]
    entries.select_index(0).run()
    main_button(at, "Diese Änderung zurücknehmen").click().run()
    assert sprint.read_text() == bad
    assert git(root, "status", "--porcelain") == ""


def test_tags_set_later_and_delete_in_the_app(shared, data_dir: Path, monkeypatch):
    root, _, server = shared
    at = open_history(start(data_dir, monkeypatch))
    at.text_input[0].set_value("demo/2026.20")
    next(b for b in at.button if b.label == "Tag setzen").click().run()
    assert not at.exception
    assert "demo/2026.20" in git(root, "tag") and "demo/2026.20" in git(server, "tag")
    assert any("demo/2026.20" in str(r) for t in at.table for r in t.value.index)
    at.checkbox(key="tag-confirm-demo/2026.20").check().run()
    main_button(at, "Tag löschen").click().run()
    assert git(root, "tag") == "" and git(server, "tag") == ""
