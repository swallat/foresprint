# SPDX-License-Identifier: EUPL-1.2
"""„Speichern und teilen“ mit echten Git-Repositories: ein Server (bare) und zwei Klone."""

import http.server
import subprocess
import threading
from datetime import date
from pathlib import Path

import pytest
import yaml
from gitrepos import Denying, NotFound, Person, git, make_clone, serve

from sprintforecast import git as gitmod
from sprintforecast import gitsync
from sprintforecast.git import (
    GitError,
    classify,
    clone_repository,
    invalidate_status,
    title_for,
)


def test_state_without_remote(tmp_path: Path):
    git(tmp_path, "init", "-q", "-b", "main")
    state = gitsync.state(tmp_path)
    assert state.remote is None and state.upstream is None and not state.can_share
    assert state.branch == "main" and (state.ahead, state.behind) == (0, 0)


def test_first_sync_connects_branch_and_pushes(alice: Person, remote: Path):
    state = gitsync.state(alice.data)
    assert state.upstream == "origin/main" and (state.ahead, state.behind) == (0, 0)
    assert git(remote, "log", "-1", "--format=%s", "main") == "Start"


def test_ahead_and_behind(alice: Person, bob: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "lokal")
    assert gitsync.state(alice.data).ahead == 1
    assert alice.sync().ok
    # Bob weiß noch nichts davon, bis er den Stand holt
    assert gitsync.state(bob.data).behind == 0
    state = gitsync.fetch(bob.data)
    assert state.behind == 1 and state.fetch_error is None and state.fetched_at


def test_sync_shows_changes_by_others(alice: Person, bob: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Review 2026.2", ["a/2026.2"]).ok
    result = bob.sync()
    assert result.ok and not result.committed
    assert [c.subject for c in result.pulled] == ["Review 2026.2"]
    assert result.pulled[0].author == "Alice"
    assert ("A", "teams/a/2026.2.yaml") in result.pulled_files
    assert (bob.data / "a" / "2026.2.yaml").read_text() == "velocity: 5\n"
    assert "a/2026.2" in git(bob.root, "tag")  # Tag kam mit


def test_incoming_before_pull(alice: Person, bob: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    alice.sync("Korrektur")
    gitsync.fetch(bob.data)
    commits, files = gitsync.incoming(bob.data)
    assert [c.subject for c in commits] == ["Korrektur"]
    assert files == [("M", "teams/a/2026.1.yaml")]


def commit_without_subject(person: Person, rel: str, text: str) -> None:
    """Ein Commit mit leerem Betreff (Git verlangt dafür ``--allow-empty-message``)."""
    person.write(rel, text)
    git(person.root, "add", "-A")
    git(person.root, "commit", "-q", "--allow-empty-message", "-m", "")


def test_incoming_with_an_empty_subject_of_the_oldest_commit(alice: Person, bob: Person):
    """``_git`` schneidet das Trennzeichen am Ende der letzten Zeile ab (str.strip): Die Zeile
    des ältesten neuen Commits hat dann nur drei Felder, wenn dessen Betreff leer ist."""
    commit_without_subject(alice, "a/2026.2.yaml", "velocity: 5\n")
    alice.write("a/2026.3.yaml", "velocity: 6\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "Zweiter")
    git(alice.root, "push", "-q")
    gitsync.fetch(bob.data)
    commits, files = gitsync.incoming(bob.data)
    assert [(c.subject, c.author) for c in commits] == [("Zweiter", "Alice"), ("", "Alice")]
    assert {file for _, file in files} == {"teams/a/2026.2.yaml", "teams/a/2026.3.yaml"}


def test_sync_pulls_a_commit_without_subject(alice: Person, bob: Person):
    commit_without_subject(alice, "a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "push", "-q")
    result = bob.sync()
    assert result.ok and [c.subject for c in result.pulled] == [""]
    assert (bob.data / "a" / "2026.2.yaml").exists()


def test_parallel_changes_in_different_files_are_merged(alice: Person, bob: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    bob.write("a/2026.3.yaml", "velocity: 7\n")
    assert alice.sync("Alice").ok
    result = bob.sync("Bob")
    assert result.ok and result.pushed and result.committed
    again = alice.sync()
    assert again.ok and (alice.data / "a" / "2026.3.yaml").exists()
    assert (alice.data / "a" / "2026.2.yaml").exists()
    # Verlauf enthält beide Änderungen, nichts ging verloren
    log = git(alice.root, "log", "--format=%s", "--no-merges")
    assert "Alice" in log and "Bob" in log


def test_push_race_is_retried(alice: Person, bob: Person, tmp_path: Path, monkeypatch):
    """Zwischen Abgleich und Push lädt jemand anderes hoch: Der Push wird abgelehnt, die App
    holt den neuen Stand und versucht es erneut."""
    carol = make_clone(
        Path(git(alice.root, "remote", "get-url", "origin")), tmp_path / "c", "Carol"
    )
    carol.write("a/2026.9.yaml", "velocity: 1\n")
    real_push = gitsync._push
    calls = []

    def racing_push(root, current):
        if root != bob.root.resolve():
            return real_push(root, current)
        calls.append(1)
        if len(calls) == 1:
            assert carol.sync("Carol").ok  # kommt Bob zuvor
        real_push(root, current)

    monkeypatch.setattr(gitsync, "_push", racing_push)
    bob.write("a/2026.3.yaml", "velocity: 7\n")
    result = bob.sync("Bob")
    assert result.ok and len(calls) == 2
    assert (bob.data / "a" / "2026.9.yaml").exists()
    assert gitsync.state(bob.data).ahead == 0


def test_push_rejected_for_good_reports_next_step(alice: Person, bob: Person, monkeypatch):
    def always_rejected(root, current):
        raise classify("! [rejected] main -> main (fetch first)")

    monkeypatch.setattr(gitsync, "_push", always_rejected)
    bob.write("a/2026.3.yaml", "velocity: 7\n")
    result = bob.sync("Bob")
    assert result.error and result.error.kind == "rejected"
    assert "Speichern und teilen" in result.error.hint
    assert result.committed  # lokal gesichert
    assert git(bob.root, "status", "--porcelain") == ""


def test_server_denies_push(alice: Person, bob: Person, remote: Path):
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(0o755)
    bob.write("a/2026.3.yaml", "velocity: 7\n")
    result = bob.sync("Bob")
    assert result.error and result.error.kind == "denied"
    assert gitsync.state(bob.data).ahead == 1  # nichts verloren


def conflict_between_alice_and_bob(alice: Person, bob: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Alice").ok
    bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
    return bob.sync("Bob")


FILE = "teams/a/2026.1.yaml"


def test_value_conflict_stays_open_and_nothing_is_lost(alice: Person, bob: Person, remote: Path):
    result = conflict_between_alice_and_bob(alice, bob)
    assert result.error and result.error.kind == "conflict" and not result.pushed
    [conflict] = result.conflicts
    assert conflict.file == FILE and not conflict.whole
    [key] = conflict.keys
    assert (key.path, key.ours, key.theirs) == (("velocity",), 12, 11)
    state = gitsync.state(bob.data)
    assert state.unfinished == "merge" and state.conflicts == (FILE,)
    assert git(remote, "show", f"main:{FILE}").startswith("velocity: 11")  # Server unverändert
    assert "Bob" in git(bob.root, "log", "--format=%s")  # eigener Commit gesichert


@pytest.mark.parametrize(("choice", "value"), [("ours", "12"), ("theirs", "11")])
def test_resolve_mine_or_other_and_continue(
    alice: Person, bob: Person, remote: Path, choice: str, value: str
):
    conflict_between_alice_and_bob(alice, bob)
    remaining = gitsync.resolve_conflicts(bob.data, {FILE: {("velocity",): choice}})
    assert remaining == []
    result = bob.sync("egal")  # Wiederaufnahme: Merge abschließen, prüfen, hochladen
    assert result.ok and result.merged and result.pushed
    assert gitsync.state(bob.data).unfinished is None
    assert yaml.safe_load(git(remote, "show", f"main:{FILE}"))["velocity"] == int(value)
    assert yaml.safe_load(git(remote, "show", f"main:{FILE}"))["scope_creep"] == 1
    log = git(remote, "log", "--format=%s", "main")
    assert "Alice" in log and "Bob" in log  # beide Änderungen bleiben im Verlauf


def test_resume_after_restart_and_abort(alice: Person, bob: Person):
    conflict_between_alice_and_bob(alice, bob)
    invalidate_status()
    again = bob.sync("noch einmal")  # ohne Entscheidung: bleibt offen, nichts geht verloren
    assert again.error and again.error.kind == "conflict" and again.conflicts
    gitsync.abort_unfinished(bob.data)
    assert (bob.data / "a" / "2026.1.yaml").read_text() == "velocity: 12\nscope_creep: 1\n"


def test_different_keys_of_same_file_are_merged(alice: Person, bob: Person, remote: Path):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Alice").ok
    bob.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 2\nnote: Bob\n")
    result = bob.sync("Bob")
    assert result.ok and result.merged and result.pushed and not result.conflicts
    merged = yaml.safe_load(git(remote, "show", f"main:{FILE}"))
    assert merged == {"velocity": 11, "scope_creep": 2, "note": "Bob"}


def test_locked_file_during_automatic_merge_is_a_message_and_the_merge_can_resume(
    alice: Person, bob: Person, remote: Path, monkeypatch
):
    """Lässt sich die zusammengeführte Datei nicht schreiben (gesperrt, schreibgeschützt), meldet
    „Speichern und teilen“ das mit Hinweis statt mit Traceback; das Zusammenführen bleibt offen
    und wird beim nächsten Versuch zu Ende geführt."""
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Alice").ok
    bob.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 2\nnote: Bob\n")
    real = Path.write_text

    def locked(self, *args, **kwargs):
        if self.name == "2026.1.yaml":
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", locked)
    result = bob.sync("Bob")
    assert result.error is not None and result.error.kind == "locked"
    assert "2026.1.yaml" in str(result.error) and "Permission denied" in str(result.error)
    # Die Datei ist keine Sperrdatei von Git: Der Absatz zur verwaisten index.lock passt hier
    # nicht, wohl aber der Schreibschutz bzw. ein Programm, das die Datei hält.
    hint = result.error.hint
    assert "Sperrdatei" not in hint and "index.lock" not in hint
    assert "Programm" in hint and "schreibgeschützt" in hint and "Speichern und teilen" in hint
    assert hint != gitmod.hint_for("locked")
    assert not result.error.raw  # eigener Text, keine Ausgabe von Git
    monkeypatch.undo()
    again = bob.sync("Bob")
    assert again.ok and again.pushed
    merged = yaml.safe_load(git(remote, "show", f"main:{FILE}"))
    assert merged == {"velocity": 11, "scope_creep": 2, "note": "Bob"}


def test_unwritable_file_hint_does_not_talk_about_a_lock_file():
    """Die Datei, die beim Zusammenführen nicht geschrieben werden kann, ist keine Sperrdatei von
    Git: Der Hinweis nennt Programme, Schreibschutz und Rechte und wie es weitergeht."""
    hint = gitmod.unwritable_file_hint()
    assert "index.lock" not in hint and "Sperrdatei" not in hint
    assert "Programm" in hint and "schreibgeschützt" in hint and "Rechte" in hint
    assert "Speichern und teilen" in hint and "Betreuung des Rechners" in hint
    assert gitmod.hint_for("locked") != hint  # Gits eigene Sperrdatei hat weiter ihren Text
    assert "index.lock" in gitmod.hint_for("locked")


def test_people_are_merged_per_entry(alice: Person, bob: Person, remote: Path):
    people = "people:\n- id: anna\n  fte: 1\n- id: ben\n  fte: 1\n"
    alice.write("a/people.yaml", people)
    assert alice.sync("Personen").ok
    assert bob.sync("holen").ok
    alice.write("a/people.yaml", people.replace("id: ben\n  fte: 1", "id: ben\n  fte: 0.5"))
    assert alice.sync("Ben halbtags").ok
    bob.write("a/people.yaml", people + "- id: cem\n  fte: 1\n")
    result = bob.sync("Cem neu")
    assert result.ok and result.merged and not result.conflicts
    merged = yaml.safe_load(git(remote, "show", "main:teams/a/people.yaml"))["people"]
    assert [(p["id"], p["fte"]) for p in merged] == [("anna", 1), ("ben", 0.5), ("cem", 1)]


def prognosis_entry(minute: int, comment: str) -> str:
    return f"- at: 2026-10-18 09:{minute:02d}:00\n  comment: {comment}\n  forecast_ist: 20\n"


def test_two_people_append_a_prognosis_in_parallel_and_both_stay(
    alice: Person, bob: Person, remote: Path
):
    head = "velocity: 10\nprognoses:\n"
    alice.write("a/2026.1.yaml", head + prognosis_entry(0, "Start"))
    assert alice.sync("Start").ok
    assert bob.sync("holen").ok
    alice.write("a/2026.1.yaml", head + prognosis_entry(0, "Start") + prognosis_entry(10, "Alice"))
    assert alice.sync("Prognose Alice").ok
    bob.write("a/2026.1.yaml", head + prognosis_entry(0, "Start") + prognosis_entry(20, "Bob"))
    result = bob.sync("Prognose Bob")
    assert result.ok and result.merged and result.pushed and not result.conflicts
    merged = yaml.safe_load(git(remote, "show", f"main:{FILE}"))
    assert [p["comment"] for p in merged["prognoses"]] == ["Start", "Alice", "Bob"]


def test_prognosis_with_same_time_but_other_content_is_decided_per_entry(
    alice: Person, bob: Person, remote: Path
):
    head = "velocity: 10\nprognoses:\n"
    alice.write("a/2026.1.yaml", head + prognosis_entry(0, "Start"))
    assert alice.sync("Start").ok
    assert bob.sync("holen").ok
    alice.write("a/2026.1.yaml", head + prognosis_entry(0, "Start") + prognosis_entry(10, "Alice"))
    assert alice.sync("Prognose Alice").ok
    bob.write("a/2026.1.yaml", head + prognosis_entry(0, "Start") + prognosis_entry(10, "Bob"))
    result = bob.sync("Prognose Bob")
    assert result.error and result.error.kind == "conflict"
    [conflict] = result.conflicts
    [key] = conflict.keys
    assert key.path == ("prognoses", "[2026-10-18T09:10:00]")
    assert key.ours["comment"] == "Bob" and key.theirs["comment"] == "Alice"
    assert gitsync.resolve_conflicts(bob.data, {FILE: {key.path: "theirs"}}) == []
    assert bob.sync("egal").pushed
    merged = yaml.safe_load(git(remote, "show", f"main:{FILE}"))
    assert [p["comment"] for p in merged["prognoses"]] == ["Start", "Alice"]


def test_deleted_on_one_side_is_decided_as_whole_file(alice: Person, bob: Person, remote: Path):
    (alice.data / "a" / "2026.1.yaml").unlink()
    assert alice.sync("Löschen").ok
    bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
    result = bob.sync("Bob ändert")
    [conflict] = result.conflicts
    assert conflict.whole and conflict.theirs_deleted and not conflict.ours_deleted
    assert gitsync.resolve_conflicts(bob.data, {FILE: {(): "ours"}}) == []
    assert bob.sync("weiter").ok
    assert yaml.safe_load(git(remote, "show", f"main:{FILE}"))["velocity"] == 12


def test_invalid_merge_result_is_not_pushed(alice: Person, bob: Person, remote: Path, data_dir):
    """Zwei Personen ändern verschiedene Produktanteile: technisch ein sauberer Merge, fachlich
    zusammen 120 %. Die Gesamtvalidierung hält das Hochladen an."""
    import shutil

    from sprintforecast.storage import Repository

    shutil.copytree(data_dir / "demo", alice.data / "demo")
    assert alice.sync("Demo").ok
    assert bob.sync("holen").ok
    products = alice.data / "demo" / "products.yaml"
    text = products.read_text()
    assert "id: webshop\n  name: Webshop\n" in text
    alice.write("demo/products.yaml", text.replace("id: webshop\n", "id: webshop\n  share: 0.6\n"))
    assert alice.sync("Alice 60 %").ok
    bob.write(
        "demo/products.yaml",
        (bob.data / "demo" / "products.yaml")
        .read_text()
        .replace("id: app\n", "id: app\n  share: 0.6\n"),
    )
    result = bob.sync("Bob 60 %", today=date(2026, 10, 15))
    assert result.merged and not result.conflicts and not result.pushed
    assert result.error and result.error.kind == "invalid"
    assert any("120" in line for line in result.validation)
    assert gitsync.state(bob.data).ahead >= 1  # lokal gesichert, nicht geteilt
    assert (
        "share: 0.6" not in git(remote, "show", "main:teams/demo/products.yaml").split("id: app")[1]
    )
    # bewusst trotzdem teilen
    forced = bob.sync("egal", today=date(2026, 10, 15), allow_invalid=True)
    assert forced.ok and forced.pushed
    assert Repository(bob.data).load("demo").products


def test_offline_keeps_local_work(alice: Person, tmp_path: Path):
    """Der Server ist ein Ordner auf einem Laufwerk, das gerade fehlt (ohne Netzwerk)."""
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "getrennt" / "daten.git"))
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Offline")
    assert result.error and result.error.kind == "offline"
    assert result.committed and not result.pushed
    state = gitsync.state(alice.data)
    assert state.offline and state.ahead == 1


def test_missing_repository_is_not_offline(alice: Person, tmp_path: Path):
    """Der Server (hier ein Ordner) antwortet, das Repository gibt es dort nicht: Internet oder
    VPN zu prüfen hilft nicht, die Adresse stimmt nicht."""
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "gibt-es-nicht.git"))
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Falsche Adresse")
    assert result.error and result.error.kind == "not_found"
    assert "nicht gefunden" in result.error.hint and "VPN" not in result.error.hint
    assert result.committed and not result.pushed  # lokal gesichert
    state = gitsync.state(alice.data)
    assert not state.offline and state.fetch_error is not None
    assert state.fetch_error.kind == "not_found" and state.ahead == 1


def test_folder_server_on_a_missing_drive_is_offline_but_a_missing_repository_is_not(
    tmp_path: Path,
):
    """Ein Ordner-Server (Netzlaufwerk, Stick) ohne übergeordneten Ordner ist „nicht erreichbar“;
    liegt der Ordner vor und fehlt nur das Repository, stimmt die Adresse nicht."""
    gone = tmp_path / "laufwerk" / "daten.git"
    message = f"fatal: '{gone}' does not appear to be a git repository\n{TAIL}"
    assert classify(message, url=str(gone)).kind == "offline"
    assert classify(message, url=str(gone)).hint == gitmod.hint_for("offline")
    # Netzfreigabe (UNC), die nicht erreichbar ist: der übergeordnete Ordner fehlt auch hier.
    unc = "//fileserver-gibt-es-nicht/daten/repo.git"
    unc_message = f"fatal: '{unc}' does not appear to be a git repository\n{TAIL}"
    assert classify(unc_message, url=unc).kind == "offline"
    # Der Ordner ist da, das Repository nicht: nicht gefunden, wie bei jedem erreichbaren Server.
    there = tmp_path / "gibt-es-nicht.git"
    assert classify(message, url=str(there)).kind == "not_found"
    # Ohne Adresse und bei einer Webadresse bleibt es bei „nicht gefunden“.
    assert classify(message).kind == "not_found"
    assert classify(message, url="https://h.example/r.git").kind == "not_found"
    # Die Prüfung einer neu eingegebenen Adresse: ein fehlender Ordner ist ein Tippfehler.
    probe = gitmod._probe_error(message, gitmod.RemoteAddress(str(gone), "local"))
    assert probe.kind == "not_found"


def test_git_passes_the_address_on_to_the_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Nicht ``classify`` allein, sondern der ganze Weg ``_git`` → ``classify``: Die Adresse wählt
    die Anmelde-Hilfe (SSH oder https)."""
    refused = subprocess.CompletedProcess([], 128, "", "git@x: Permission denied (publickey).")
    monkeypatch.setattr(gitmod, "_git_result", lambda *args, **kwargs: refused)
    with pytest.raises(GitError) as ssh:
        gitmod._git(tmp_path, "fetch", network=True, url="git@x:r.git")
    with pytest.raises(GitError) as https:
        gitmod._git(tmp_path, "fetch", network=True, url="https://x/r.git")
    assert "ssh-keygen" in ssh.value.hint and "Zugangstoken" not in ssh.value.hint
    assert "Zugangstoken" in https.value.hint and "ssh-keygen" not in https.value.hint


@pytest.mark.usefixtures("no_login_prompt")
def test_http_404_is_not_found_and_not_offline(alice: Person):
    with serve(NotFound) as port:
        git(alice.root, "remote", "set-url", "origin", f"http://127.0.0.1:{port}/r.git")
        error = gitsync.fetch(alice.data).fetch_error
    assert error is not None and error.kind == "not_found"
    assert "not found" in str(error) or "error: 404" in str(error)  # je nach Git-Version
    assert "VPN" not in error.hint


def test_timeout_counts_as_offline():
    assert classify("", timeout=True).kind == "offline"


def test_first_push_to_a_missing_drive_is_offline(tmp_path: Path):
    """Der erste Hochlade-Versuch (``push -u``) reicht die Adresse an die Zuordnung weiter: Ein
    Ordner-Server auf einem fehlenden Laufwerk ist „nicht erreichbar“."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "X")
    git(tmp_path, "config", "user.email", "x@example.org")
    person = Person("X", tmp_path)
    person.write("a/team.yaml", "name: A\n")
    assert person.sync("Lokal").committed
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "getrennt" / "daten.git"))
    current = gitsync.state(tmp_path)
    assert current.upstream is None and current.remote == "origin"
    with pytest.raises(GitError) as info:
        gitsync._push(tmp_path, current)
    assert info.value.kind == "offline"


def test_no_remote_still_saves(tmp_path: Path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "X")
    git(tmp_path, "config", "user.email", "x@example.org")
    person = Person("X", tmp_path)
    person.write("a/team.yaml", "name: A\n")
    result = person.sync("Lokal")
    assert result.committed and result.error and result.error.kind == "no_remote"


def test_missing_login_is_explained(alice: Person):
    server = http.server.HTTPServer(("127.0.0.1", 0), Denying)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        git(
            alice.root,
            "remote",
            "set-url",
            "origin",
            f"http://127.0.0.1:{server.server_port}/r.git",
        )
        alice.write("a/2026.2.yaml", "velocity: 5\n")
        result = alice.sync("Login")
    finally:
        server.shutdown()
    assert result.error and result.error.kind == "auth"
    assert "Zugangstoken" in result.error.hint
    assert result.committed


def test_auth_help_for_ssh_differs():
    from sprintforecast.git import auth_help

    assert "SSH" in auth_help("git@example.org:team/daten.git")
    assert "Zugangstoken" in auth_help("https://example.org/team/daten.git")


@pytest.mark.parametrize(
    "url", ["https://example.org/team/daten.git", "git@example.org:team/daten.git", ""]
)
def test_auth_help_does_not_repeat_the_heading(url: str):
    """Die Überschrift („Anmeldung fehlt oder wurde abgelehnt“) steht schon über dem Hinweis."""
    from sprintforecast.git import auth_help, hint_for, title_for

    hint = auth_help(url)
    assert "fehlt oder wurde abgelehnt" not in hint
    assert "fehlt oder wurde abgelehnt" in title_for("auth")
    assert hint_for("auth", url) == hint
    assert hint.endswith("Danach noch einmal versuchen.")


def test_auth_help_is_cut_to_the_address():
    from sprintforecast.git import auth_help

    https = auth_help("https://example.org/team/daten.git")
    assert "Zugangstoken" in https and "`gh auth setup-git`" in https
    assert "Anmeldedienst des Rechners" in https
    # nicht mehr alle Betriebssysteme in einem Satz, keine SSH-Schritte
    for other in ("Windows", "macOS", "Linux", "credential.helper", "ssh-keygen", "SSH"):
        assert other not in https, other

    ssh = auth_help("git@example.org:team/daten.git")
    assert auth_help("ssh://git@example.org/team/daten.git") == ssh
    assert ssh.startswith("Diese Adresse nutzt die Anmeldung per SSH-Schlüssel. Dafür ")
    assert "ssh-keygen -t ed25519" in ssh and ".pub" in ssh and "ssh-agent" in ssh
    for other in ("Zugangstoken", "gh auth", "Anmeldedienst", "Windows", "https"):
        assert other not in ssh, other


LOGIN_FAILURES = [
    pytest.param(
        "git@example.org:team/daten.git",
        "git@example.org: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository.",
        "ssh-keygen",
        "Zugangstoken",
        id="ssh",
    ),
    pytest.param(
        "ssh://git@example.org/team/daten.git",
        "git@example.org: Permission denied (publickey).",
        "ssh-keygen",
        "Zugangstoken",
        id="ssh-url",
    ),
    pytest.param(
        "https://example.org/team/daten.git",
        "fatal: Authentication failed for 'https://example.org/team/daten.git/'",
        "Zugangstoken",
        "ssh-keygen",
        id="https",
    ),
    pytest.param(
        "git@example.org:team/daten.git",
        "Host key verification failed.\nfatal: Could not read from remote repository.",
        "Fingerabdruck",
        "ssh-keygen",
        id="ssh-host-key",
    ),
]


@pytest.mark.parametrize(("url", "message", "expected", "absent"), LOGIN_FAILURES)
def test_fetch_login_failure_names_the_steps_for_the_address(
    alice: Person, monkeypatch: pytest.MonkeyPatch, url: str, message: str, expected: str,
    absent: str,
):  # fmt: skip
    """Scheitert der Abgleich an der Anmeldung, passt der Hinweis zur Adresse des Servers: bei
    SSH die SSH-Schritte, bei https der Zugangstoken – nicht der Text für https überall."""
    git(alice.root, "remote", "set-url", "origin", url)
    real_git = gitsync._git

    def failing(root, *args, **kwargs):
        if args[:1] == ("fetch",):
            raise classify(message, url=kwargs.get("url", ""))
        return real_git(root, *args, **kwargs)

    monkeypatch.setattr(gitsync, "_git", failing)
    error = gitsync.fetch(alice.data).fetch_error
    assert error is not None and error.kind == "auth"
    assert expected in error.hint and absent not in error.hint
    # „Speichern und teilen“ meldet denselben Hinweis
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    shared = alice.sync("Login")
    assert shared.error is not None and shared.error.kind == "auth"
    assert shared.error.hint == error.hint
    assert shared.committed  # lokal gesichert


@pytest.mark.parametrize(("url", "message", "expected", "absent"), LOGIN_FAILURES)
def test_clone_login_failure_names_the_steps_for_the_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, message: str, expected: str,
    absent: str,
):  # fmt: skip
    def failing(*args, **kwargs):
        raise classify(message, url=kwargs.get("url", ""))

    monkeypatch.setattr(gitmod, "_git", failing)
    with pytest.raises(GitError) as info:
        clone_repository(url, tmp_path / "ziel")
    assert info.value.kind == "auth"
    assert expected in info.value.hint and absent not in info.value.hint


@pytest.mark.parametrize(("url", "message", "expected", "absent"), LOGIN_FAILURES)
def test_push_login_failure_names_the_steps_for_the_address(
    alice: Person, monkeypatch: pytest.MonkeyPatch, url: str, message: str, expected: str,
    absent: str,
):  # fmt: skip
    """Gelingt der Abgleich und scheitert erst das Hochladen an der Anmeldung (z. B. ein anderer
    Schlüssel), gilt für den Hinweis dasselbe wie beim Abgleich."""
    git(alice.root, "remote", "set-url", "origin", url)
    real_git = gitsync._git

    def failing(root, *args, **kwargs):
        if args[:1] == ("fetch",):
            return ""
        if args[:1] == ("push",):
            raise classify(message, url=kwargs.get("url", ""))
        return real_git(root, *args, **kwargs)

    monkeypatch.setattr(gitsync, "_git", failing)
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Login")
    assert result.error is not None and result.error.kind == "auth"
    assert expected in result.error.hint and absent not in result.error.hint


def test_login_failure_without_a_heading_names_the_cause():
    """„Nur lokal erledigt“ (z. B. ein Tag, der nicht hochgeladen werden konnte) zeigt
    ``GitError.full()`` ohne Überschrift: Die Ursache steht deshalb dort voran, der Hinweis
    selbst wiederholt sie nicht."""
    error = classify("fatal: Authentication failed for 'https://example.org/team/daten.git/'")
    assert error.kind == "auth"
    text = error.full()
    assert text.startswith(title_for("auth") + ". ")
    assert text.count("fehlt oder wurde abgelehnt") == 1
    assert "Authentication failed" in text  # die Meldung von Git bleibt erhalten
    assert text.endswith(error.hint)
    # andere Fehlerarten bleiben unverändert: Meldung, dann Hinweis
    offline = classify("fatal: unable to access 'https://x/': Could not resolve host: x")
    assert offline.full() == f"{offline} {offline.hint}"
    assert classify("fatal: etwas Unbekanntes").full() == "fatal: etwas Unbekanntes"


def test_clone_with_missing_login_is_explained(tmp_path: Path):
    server = http.server.HTTPServer(("127.0.0.1", 0), Denying)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(GitError) as info:
            clone_repository(f"http://127.0.0.1:{server.server_port}/r.git", tmp_path / "ziel")
    finally:
        server.shutdown()
    assert info.value.kind == "auth" and info.value.hint


def test_locked_file(alice: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    (alice.root / ".git" / "index.lock").write_text("")
    result = alice.sync("Gesperrt")
    assert result.error and result.error.kind == "locked"
    assert "Programm" in result.error.hint
    # Nach einem Absturz kann die Sperrdatei übrig sein: nachfragen, nicht selbst löschen
    assert "Sperrdatei" in result.error.hint and "Betreuung" in result.error.hint


@pytest.mark.parametrize(
    "message",
    [
        "error: unable to create file teams/a/2026.2.yaml: Permission denied",
        "fatal: Unable to create '/r/.git/index.lock': Permission denied",
    ],
)
def test_unwritable_repository_is_not_a_locked_file(
    alice: Person, monkeypatch: pytest.MonkeyPatch, message: str
):
    """Rechtefehler lassen sich nicht unter Windows und Linux gleich herstellen: Git antwortet
    hier nachgestellt."""
    real = gitmod._git_result

    def refusing(cwd, *args, **kwargs):
        if args[:1] == ("add",):
            return subprocess.CompletedProcess(args, 128, "", message)
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git_result", refusing)
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Schreibgeschützt")
    assert result.error and result.error.kind == "not_writable"
    assert "Schreibrechte" in result.error.hint and "Sperrdatei" not in result.error.hint
    assert not result.committed and not result.pushed
    assert title_for(result.error.kind) == "Datei oder Ordner nicht beschreibbar"


def test_git_missing(alice: Person, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PATH", "")
    result = alice.sync("ohne Git")
    assert result.error and result.error.kind == "git_missing"
    assert "installieren" in result.error.hint
    assert not gitsync.git_available()


def test_unfinished_merge_from_outside_can_be_aborted(alice: Person, bob: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Alice").ok
    bob.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
    git(bob.root, "add", "-A")
    git(bob.root, "commit", "-qm", "Bob")
    git(bob.root, "fetch", "-q")
    subprocess.run(["git", "merge", "origin/main"], cwd=bob.root, capture_output=True)  # Konflikt
    invalidate_status()
    state = gitsync.state(bob.data)
    assert state.unfinished == "merge" and state.conflicts == (FILE,)
    assert [c.file for c in gitsync.pending_conflicts(bob.data)] == [FILE]
    gitsync.abort_unfinished(bob.data)
    state = gitsync.state(bob.data)
    assert state.unfinished is None and not state.conflicts
    assert (bob.data / "a" / "2026.1.yaml").read_text() == "velocity: 12\nscope_creep: 1\n"


def test_detached_head_blocks_and_reattach(alice: Person):
    git(alice.root, "checkout", "-q", "--detach")
    invalidate_status()
    assert gitsync.state(alice.data).detached
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Detached")
    assert result.error and result.error.kind == "detached"
    assert not result.committed  # nichts auf einen namenlosen Stand schreiben
    git(alice.root, "stash", "-u", "-q")  # nur damit der Wechsel ohne offene Änderungen läuft
    assert gitsync.reattach(alice.data).branch == "main"
    assert gitsync.state(alice.data).branch == "main"


def test_reattach_rescues_orphan_commits(alice: Person):
    git(alice.root, "checkout", "-q", "--detach")
    (alice.root / "teams" / "a" / "neu.yaml").write_text("x: 1\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "auf losem Stand")
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.branch == "main"
    assert "rettung-" in git(alice.root, "branch", "--list")
    assert done.rescue is not None and done.rescue.startswith("rettung-")


def detach_with_open_change(alice: Person, orphan_commit: bool = False) -> None:
    """Lose auf dem Stand vor der letzten Änderung von ``main``, mit offener Änderung an derselben
    Datei: Der Wechsel zurück würde sie überschreiben. Mit ``orphan_commit`` hängt vorher noch ein
    Commit an keinem Branch."""
    file = alice.data / "a" / "2026.1.yaml"
    file.write_text("velocity: 11\nscope_creep: 1\n", encoding="utf-8")
    git(alice.root, "commit", "-qam", "Neuer Stand")
    git(alice.root, "checkout", "-q", "--detach", "HEAD~1")
    if orphan_commit:
        (alice.data / "a" / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
        git(alice.root, "add", "-A")
        git(alice.root, "commit", "-qm", "auf losem Stand")
    file.write_text("velocity: 99\nscope_creep: 1\n", encoding="utf-8")
    invalidate_status()


def test_reattach_with_open_changes_saves_them_on_a_rescue_branch(alice: Person):
    """Offene Änderungen im Datenordner gehen nicht verloren und werden nicht mitgenommen: Sie
    liegen als eigener Commit auf einem Rettungsbranch, danach steht der Hauptbranch sauber da."""
    detach_with_open_change(alice)
    done = gitsync.reattach(alice.data)
    assert done.branch == "main" and done.changes and not done.commits
    assert done.rescue is not None and done.rescue.startswith("rettung-")
    assert gitsync.state(alice.data).branch == "main"
    assert git(alice.root, "status", "--porcelain") == ""
    assert (alice.data / "a" / "2026.1.yaml").read_text() == "velocity: 11\nscope_creep: 1\n"
    saved = f"{done.rescue}:teams/a/2026.1.yaml"
    assert git(alice.root, "show", saved) == "velocity: 99\nscope_creep: 1"
    assert git(alice.root, "log", "-1", "--format=%s", done.rescue) == (
        "Offene Änderungen vor dem Wechsel gesichert"
    )


def test_reattach_saves_new_files_and_commits_together_on_one_rescue_branch(alice: Person):
    detach_with_open_change(alice, orphan_commit=True)
    (alice.data / "a" / "frisch.yaml").write_text("y: 2\n", encoding="utf-8")
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.commits and done.changes and done.rescue is not None
    rescue = git(alice.root, "branch", "--list", "rettung-*", "--format=%(refname:short)")
    assert rescue == done.rescue  # ein einziger Rettungsbranch
    files = git(alice.root, "ls-tree", "-r", "--name-only", done.rescue)
    assert "teams/a/neu.yaml" in files and "teams/a/frisch.yaml" in files
    assert "frisch.yaml" not in (git(alice.root, "ls-files"))  # auf main nicht mitgenommen


def test_reattach_with_open_changes_and_a_commit_on_a_branch_makes_a_new_rescue_branch(
    alice: Person,
):
    """Hängt der Stand an einem Branch, wird für die offenen Änderungen ein Rettungsbranch neu
    angelegt; der Branch selbst bleibt unverändert."""
    git(alice.root, "checkout", "-q", "--detach")
    (alice.data / "a" / "2026.1.yaml").write_text("velocity: 50\n", encoding="utf-8")
    invalidate_status()
    before = git(alice.root, "rev-parse", "main")
    done = gitsync.reattach(alice.data)
    assert done.changes and not done.commits and done.rescue is not None
    assert git(alice.root, "rev-parse", "main") == before
    assert git(alice.root, "rev-parse", f"{done.rescue}~1") == before


def test_reattach_without_open_changes_makes_no_extra_commit(alice: Person):
    detach_with_open_change(alice, orphan_commit=True)
    git(alice.root, "checkout", "--", ".")
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.commits and not done.changes
    assert git(alice.root, "log", "-1", "--format=%s", done.rescue) == "auf losem Stand"


def test_reattach_keeps_the_state_when_saving_fails(alice: Person):
    """Eine Tabellenkalkulation im Datenordner lässt sich nicht committen: Der Wechsel bricht ab,
    das Repository steht wie vorher auf dem losen Stand, ein neu angelegter Rettungsbranch ist
    wieder weg."""
    git(alice.root, "checkout", "-q", "--detach")
    (alice.data / "a" / "plan.xlsx").write_text("x", encoding="utf-8")
    invalidate_status()
    head = git(alice.root, "rev-parse", "HEAD")
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    assert gitsync.state(alice.data).detached
    assert git(alice.root, "rev-parse", "HEAD") == head
    assert "rettung-" not in git(alice.root, "branch", "--list")
    assert (alice.data / "a" / "plan.xlsx").exists()


def test_reattach_blocked_outside_the_data_folder_does_not_point_to_discarding(alice: Person):
    """Das Verwerfen auf der Seite „Änderungen und Verlauf“ wirkt nur im Datenordner: Liegt die
    blockierende Datei außerhalb (hier ``README.md`` im Wurzelordner), wäre der Hinweis
    „verwerfen“ eine Sackgasse."""
    readme = alice.root / "README.md"
    readme.write_text("eins\n", encoding="utf-8")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "README")
    git(alice.root, "checkout", "-q", "--detach", "HEAD~1")
    readme.write_text("zwei\n", encoding="utf-8")
    invalidate_status()
    from sprintforecast.githistory import discard_preview

    assert discard_preview(alice.data) == []  # im Datenordner gibt es nichts zu verwerfen
    with pytest.raises(GitError) as info:
        gitsync.reattach(alice.data)
    hint = " ".join(info.value.hint.split())
    assert info.value.kind == "detached" and "README.md" in str(info.value)
    assert "außerhalb des Datenordners" in hint and "in Git" in hint
    assert "die offenen Änderungen verwerfen – sie gehen" not in hint
    assert "git config" not in hint and "safe.directory" not in hint


def test_reattach_names_no_rescue_branch_when_the_commit_is_on_a_branch(alice: Person):
    git(alice.root, "checkout", "-q", "--detach")
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.branch == "main" and done.rescue is None
    assert "rettung-" not in git(alice.root, "branch", "--list")


def test_reattach_names_the_rescue_branch_again_after_a_failed_attempt(alice: Person):
    """Erst scheitert der Wechsel an offenen Änderungen (die Commits sind schon gesichert), nach
    dem Aufräumen außerhalb des Datenordners gelingt er: Die Meldung nennt den Rettungsbranch
    trotzdem, und die Sicherung der Änderungen im Datenordner bleibt, ohne ein zweites Mal
    zu committen."""
    readme = alice.root / "README.md"
    readme.write_text("eins\n", encoding="utf-8")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "README")
    git(alice.root, "checkout", "-q", "--detach", "HEAD~1")
    (alice.data / "a" / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "auf losem Stand")
    (alice.data / "a" / "2026.1.yaml").write_text("velocity: 99\n", encoding="utf-8")
    readme.write_text("zwei\n", encoding="utf-8")
    invalidate_status()
    with pytest.raises(GitError) as info:
        gitsync.reattach(alice.data)
    rescue = git(alice.root, "branch", "--list", "rettung-*", "--format=%(refname:short)")
    assert rescue.startswith("rettung-") and "\n" not in rescue
    assert rescue in info.value.hint  # die Änderungen im Datenordner liegen schon dort
    assert gitsync.state(alice.data).detached
    readme.unlink()  # außerhalb des Datenordners aufgeräumt
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.branch == "main" and done.rescue == rescue and done.commits
    assert done.changes  # die frühere Sicherung wird erkannt: Meldung nennt auch die Änderungen
    assert git(alice.root, "log", "--format=%s", "-2", rescue).splitlines() == [
        "Offene Änderungen vor dem Wechsel gesichert",
        "auf losem Stand",
    ]


def detach_blocked_outside(alice: Person) -> Path:
    """Lose, mit einer offenen Änderung im Datenordner und einer blockierenden Datei außerhalb
    (``README.md`` im Wurzelordner, auf ``main`` vorhanden)."""
    readme = alice.root / "README.md"
    readme.write_text("eins\n", encoding="utf-8")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "README")
    git(alice.root, "checkout", "-q", "--detach", "HEAD~1")
    (alice.data / "a" / "eins.yaml").write_text("x: 1\n", encoding="utf-8")
    readme.write_text("zwei\n", encoding="utf-8")
    invalidate_status()
    return readme


def test_second_attempt_names_the_earlier_save_in_the_hint(alice: Person):
    readme = detach_blocked_outside(alice)
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    rescue = git(alice.root, "branch", "--list", "rettung-*", "--format=%(refname:short)")
    with pytest.raises(GitError) as info:
        gitsync.reattach(alice.data)  # nichts Neues im Datenordner, die Sicherung steht schon
    assert rescue in info.value.hint
    readme.unlink()
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.changes and not done.commits and done.rescue == rescue


@pytest.mark.parametrize("orphan", [False, True])
def test_commits_are_told_apart_over_a_chain_of_saves(alice: Person, orphan: bool):
    """Zwei Sicherungen hintereinander (zwei gescheiterte Versuche): Ob der lose Stand eigene
    Commits hatte, zeigt erst der Commit vor der ganzen Kette."""
    readme = detach_blocked_outside(alice)
    if orphan:
        git(alice.root, "add", "teams/a/eins.yaml")
        git(alice.root, "commit", "-qm", "auf losem Stand", "--", "teams/a/eins.yaml")
        (alice.data / "a" / "drei.yaml").write_text("w: 0\n", encoding="utf-8")
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    (alice.data / "a" / "zwei.yaml").write_text("y: 2\n", encoding="utf-8")
    invalidate_status()
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    subjects = git(alice.root, "log", "--format=%s", "-3", "HEAD").splitlines()
    assert subjects[:2] == ["Offene Änderungen vor dem Wechsel gesichert"] * 2
    readme.unlink()
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.changes and done.commits is orphan


def test_new_changes_after_a_failed_attempt_go_to_the_same_rescue_branch(alice: Person):
    readme = detach_blocked_outside(alice)
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    rescue = git(alice.root, "branch", "--list", "rettung-*", "--format=%(refname:short)")
    (alice.data / "a" / "zwei.yaml").write_text("y: 2\n", encoding="utf-8")
    invalidate_status()
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    assert git(alice.root, "branch", "--list", "rettung-*", "--format=%(refname:short)") == rescue
    readme.unlink()
    invalidate_status()
    done = gitsync.reattach(alice.data)
    assert done.rescue == rescue
    files = git(alice.root, "ls-tree", "-r", "--name-only", rescue)
    assert "teams/a/eins.yaml" in files and "teams/a/zwei.yaml" in files


def test_failed_save_restores_the_index(alice: Person, monkeypatch: pytest.MonkeyPatch):
    """Nach einem gescheiterten Commit (hier: fehlende Identität) ist der Index wie vorher: neue
    Dateien nicht vorgemerkt, geänderte nicht vorgemerkt; HEAD lose auf dem alten Stand."""
    git(alice.root, "checkout", "-q", "--detach")
    (alice.data / "a" / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    (alice.data / "a" / "2026.1.yaml").write_text("velocity: 50\n", encoding="utf-8")
    invalidate_status()
    head = git(alice.root, "rev-parse", "HEAD")
    real = gitmod._git

    def failing(root, *args, **kwargs):
        if args and args[0] == "commit":
            raise GitError("kein Commit")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git", failing)
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    monkeypatch.undo()
    assert git(alice.root, "diff", "--cached", "--name-only") == ""  # nichts vorgemerkt
    assert git(alice.root, "ls-files", "--others", "--exclude-standard") == "teams/a/neu.yaml"
    assert git(alice.root, "diff", "--name-only") == "teams/a/2026.1.yaml"
    assert gitsync.state(alice.data).detached and git(alice.root, "rev-parse", "HEAD") == head
    assert "rettung-" not in git(alice.root, "branch", "--list")


def test_failed_save_keeps_the_staging_of_the_user(alice: Person, monkeypatch: pytest.MonkeyPatch):
    """Eine vorhandene (auch teilweise) Vormerkung bleibt nach dem Rückbau exakt erhalten."""
    git(alice.root, "checkout", "-q", "--detach")
    full = alice.data / "a" / "voll.yaml"
    full.write_text("x: 1\n", encoding="utf-8")
    git(alice.root, "add", str(full))  # vollständig vorgemerkt
    part = alice.data / "a" / "2026.1.yaml"
    part.write_text("velocity: 50\n", encoding="utf-8")
    git(alice.root, "add", str(part))
    part.write_text("velocity: 51\n", encoding="utf-8")  # danach erneut geändert: teilweise
    (alice.data / "a" / "lose.yaml").write_text("z: 3\n", encoding="utf-8")  # nicht vorgemerkt
    invalidate_status()
    before = [
        git(alice.root, *args)
        for args in (("diff", "--cached"), ("diff",), ("status", "--porcelain"))
    ]
    real = gitmod._git

    def failing(root, *args, **kwargs):
        if args and args[0] == "commit":
            raise GitError("kein Commit")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git", failing)
    with pytest.raises(GitError):
        gitsync.reattach(alice.data)
    monkeypatch.undo()
    after = [
        git(alice.root, *args)
        for args in (("diff", "--cached"), ("diff",), ("status", "--porcelain"))
    ]
    assert after == before and before[0]  # es gab eine Vormerkung
    assert gitsync.state(alice.data).detached


def test_failed_save_with_a_file_error_never_stays_on_the_rescue_branch(
    alice: Person, monkeypatch: pytest.MonkeyPatch
):
    git(alice.root, "checkout", "-q", "--detach")
    (alice.data / "a" / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    invalidate_status()

    def broken(path, message, tags=None):
        raise OSError("Datei gesperrt")

    monkeypatch.setattr(gitmod, "commit_directory", broken)
    with pytest.raises(OSError):
        gitsync.reattach(alice.data)
    monkeypatch.undo()
    assert gitsync.state(alice.data).detached
    assert "rettung-" not in git(alice.root, "branch", "--list")


def test_identity_missing_is_explained(
    alice: Person, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    git(alice.root, "config", "--unset", "user.name")
    git(alice.root, "config", "--unset", "user.email")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Ohne Namen")
    assert result.error and result.error.kind == "identity"
    gitsync.set_identity("Alice", "alice@example.org")
    assert alice.sync("Mit Namen").ok
    with pytest.raises(GitError):
        gitsync.set_identity("", "keine-adresse")


def test_spreadsheet_is_still_refused(alice: Person):
    (alice.data / "blatt.xlsx").write_bytes(b"x")
    invalidate_status()
    result = alice.sync("Tabelle")
    assert result.error and "Tabellenkalkulationen" in str(result.error)


TAIL = (
    "fatal: Could not read from remote repository.\n\nPlease make sure you have the correct "
    "access rights\nand the repository exists."
)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("fatal: Authentication failed for 'https://x/'", "auth"),
        ("fatal: could not read Username for 'https://x': terminal prompts disabled", "auth"),
        ("git@x: Permission denied (publickey).\nfatal: Could not read from remote", "auth"),
        ("fatal: unable to access 'https://x/': Could not resolve host: x", "offline"),
        ("fatal: unable to access 'https://x/': The requested URL returned error: 403", "auth"),
        ("fatal: Unable to create '/r/.git/index.lock': File exists.", "locked"),
        ("error: Your local changes to the following files would be overwritten by merge", "dirty"),
        ("fatal: You have not concluded your merge (MERGE_HEAD exists).", "merge_in_progress"),
        ("CONFLICT (content): Merge conflict in a.yaml", "conflict"),
        ("fatal: Repository not found.", "not_found"),
        ("etwas ganz anderes", "error"),
        # Der Server antwortet, es gibt das Repository dort nicht: nie „offline“.
        (
            "fatal: unable to access 'https://x/r.git/': The requested URL returned error: 404",
            "not_found",
        ),
        (f"ERROR: Repository not found.\n{TAIL}", "not_found"),
        ("fatal: repository 'https://x/r.git/' not found", "not_found"),
        (
            "remote: TF401019: The Git repository with name or identifier x does not exist",
            "not_found",
        ),
        (f"fatal: '/x/y' does not appear to be a git repository\n{TAIL}", "not_found"),
        ("fatal: repository '/x/y' does not exist", "not_found"),  # Klonen von einem Pfad
        ("remote: Project not found.\nfatal: Could not read from remote repository.", "not_found"),
        (
            "remote: ERROR: The project does not exist or you do not have permission to access it.",
            "not_found",
        ),
        ("error: unable to create file x.yaml: Device or resource busy", "locked"),
        # Das Zertifikat wird nicht anerkannt: VPN oder Internet zu prüfen nützt nichts.
        (
            "fatal: unable to access 'https://x/': server certificate verification failed. "
            "CAfile: none CRLfile: none",
            "certificate",
        ),
        ("fatal: unable to access 'https://x/': schannel: SEC_E_CERT_EXPIRED", "certificate"),
        (
            "fatal: unable to access 'https://x/': schannel: next InitializeSecurityContext "
            "failed: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)",
            "certificate",
        ),
        (
            "fatal: unable to access 'https://x/': no alternative certificate subject name "
            "matches target host name 'x'",
            "certificate",
        ),
        (
            "fatal: unable to access 'https://x/r.git/': SSL certificate problem: unable to get "
            "local issuer certificate",
            "certificate",
        ),
        (
            "fatal: unable to access 'https://x/': schannel: SEC_E_UNTRUSTED_ROOT (0x80090325)",
            "certificate",
        ),
        # Kein Schreibrecht, auch beim Anlegen der Sperrdatei; die SSH-Anmeldung bleibt „auth“.
        ("error: unable to create file teams/a/2026.2.yaml: Permission denied", "not_writable"),
        ("fatal: Unable to create '/r/.git/index.lock': Permission denied", "not_writable"),
        ("error: could not lock config file .git/config: Permission denied", "not_writable"),
        ("fatal: could not create work tree dir 'ziel': Permission denied", "not_writable"),
        ("error: unable to create file teams/a/x.yaml: Read-only file system", "not_writable"),
        ("git@x: Permission denied (publickey,gssapi-keyex,gssapi-with-mic).", "auth"),
        ('error: open("teams/a/x.yaml"): Permission denied', "not_writable"),
        ("error: unable to open x.yaml: Permission denied", "not_writable"),
        ("error: unable to write file x.yaml: Permission denied", "not_writable"),
        ("error: could not write config file .git/config: Permission denied", "not_writable"),
        ("fatal: could not open '.git/FETCH_HEAD' for writing: Permission denied", "not_writable"),
        (
            "error: cannot lock ref 'refs/heads/main': Unable to create "
            "'/r/.git/refs/heads/main.lock': Permission denied",
            "not_writable",
        ),
        ("fatal: cannot mkdir ziel: Permission denied", "not_writable"),
        ("error: cannot create directory at 'teams/a': Permission denied", "not_writable"),
        ("error: cannot open .git/FETCH_HEAD: Permission denied", "not_writable"),
        # Windows beendet die Zeile mit CRLF.
        ("error: unable to create file x.yaml: Permission denied\r\n", "not_writable"),
        # „Permission denied“ allein macht es nicht zu „nicht beschreibbar“: Verbindung gesperrt
        # (Firewall, Sicherheitssoftware) bleibt offline, Schlüsseldatei und Host-Key bleiben
        # Anmeldung, die Ablehnung des Servers bleibt „denied“, wie vor dieser Änderung.
        (
            "git@x: Permission denied, please try again.\ngit@x: Permission denied (publickey).",
            "auth",
        ),
        ("git@x: Permission denied, please try again.", "error"),
        ("ssh: connect to host github.com port 22: Permission denied", "offline"),
        (
            "ssh: connect to host github.com port 22: Permission denied\n"
            "fatal: Could not read from remote repository.",
            "offline",
        ),
        (
            "fatal: unable to access 'https://h/r.git/': Failed to connect to h port 443: "
            "Permission denied",
            "offline",
        ),
        (
            "Could not create directory '/home/svc/.ssh' (Permission denied).\n"
            "Failed to add the host to the list of known hosts (/home/svc/.ssh/known_hosts).\n"
            "Host key verification failed.\n" + TAIL,
            "auth",
        ),
        (
            'Load key "/home/u/.ssh/id_ed25519": Permission denied\n'
            "git@github.com: Permission denied (publickey).\n" + TAIL,
            "auth",
        ),
        (
            "Warning: Identity file /home/u/.ssh/id not accessible: Permission denied.\n"
            "git@github.com: Permission denied (publickey).",
            "auth",
        ),
        (
            "warning: unable to access '/home/u/.config/git/attributes': Permission denied\n"
            "fatal: unable to access 'https://x/r.git/': Could not resolve host: x",
            "offline",
        ),
        (
            "remote: Gitea: User permission denied for writing.\nTo h:r.git\n"
            " ! [remote rejected] main -> main (pre-receive hook declined)",
            "denied",
        ),
        (
            "remote: Permission denied\n ! [remote rejected] main -> main (pre-receive hook "
            "declined)",
            "denied",
        ),
        # Ein Schreibfehler auf dem Server ist nicht der eigene Datenordner.
        ("remote: error: unable to create file x: Permission denied", "error"),
        # Ein anderes Programm benutzt die Datei: gesperrt (Windows meldet oft Permission denied).
        ("error: unable to unlink old 'teams/a/x.yaml': Permission denied", "locked"),
        (
            "error: unable to create file x.yaml: The process cannot access the file because it "
            "is being used by another process",
            "locked",
        ),
        # Git verweigert einen fremden Ordner.
        (
            "fatal: detected dubious ownership in repository at '/r'\nTo add an exception for "
            "this directory, call:\n\n\tgit config --global --add safe.directory /r",
            "unsafe_directory",
        ),
        # Der Fingerabdruck des SSH-Servers ist unbekannt oder hat sich geändert.
        (f"Host key verification failed.\n{TAIL}", "auth"),
        ("@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @", "auth"),
    ],
)
def test_classify(text: str, kind: str):
    assert classify(text).kind == kind


@pytest.mark.parametrize(
    ("text", "url", "hint_part", "absent"),
    [
        (
            "fatal: unable to access 'https://x/': The requested URL returned error: 404",
            "",
            "nicht gefunden",
            "VPN",
        ),
        (f"ERROR: Repository not found.\n{TAIL}", "git@x:r.git", "nicht gefunden", "VPN"),
        ("fatal: repository 'https://x/r.git/' not found", "", "Adresse", "VPN"),
        (
            "fatal: unable to access 'https://x/': SSL certificate problem: x",
            "",
            "Zertifikat",
            "VPN",
        ),
        (
            "fatal: unable to access 'https://x/': SSL certificate problem: x",
            "",
            "IT",
            "gespeichert",
        ),
        (
            "error: unable to create file x.yaml: Permission denied",
            "",
            "schreibgeschützt",
            "anderes Programm",
        ),
        ("error: unable to create file x.yaml: Permission denied", "", "Cloud", "anderes Programm"),
        (
            "fatal: Unable to create '/r/.git/index.lock': Permission denied",
            "",
            "Schreibrechte",
            "Sperrdatei",
        ),
        # Eine Sperrdatei nach einem Absturz: nachfragen, bevor sie entfernt wird.
        (
            "fatal: Unable to create '/r/.git/index.lock': File exists.",
            "",
            "Betreuung",
            "schreibgeschützt",
        ),
        (
            "fatal: Unable to create '/r/.git/index.lock': File exists.",
            "",
            "index.lock",
            "schreibgeschützt",
        ),
        ("fatal: detected dubious ownership in repository at '/r'", "", "andere", "safe.directory"),
        (
            "fatal: detected dubious ownership in repository at '/r'",
            "",
            "ändert keine Git-Einstellungen",
            "VPN",
        ),
        # Fingerabdruck: unabhängig von der Adresse, die Meldung belegt SSH
        ("Host key verification failed.", "git@x:r.git", "Fingerabdruck", "ssh-keygen"),
        ("Host key verification failed.", "", "Fingerabdruck", "Zugangstoken"),
        ("git@x: Permission denied (publickey).", "git@x:r.git", "ssh-keygen", "Fingerabdruck"),
        (
            "fatal: Authentication failed for 'https://x/'",
            "https://x/r.git",
            "Zugangstoken",
            "Fingerabdruck",
        ),
    ],
)
def test_classify_hints(text: str, url: str, hint_part: str, absent: str):
    hint = classify(text, url=url).hint
    assert hint_part in hint and absent not in hint


@pytest.mark.parametrize(
    "kind", ["not_writable", "unsafe_directory", "certificate", "not_found", "locked"]
)
def test_kinds_have_their_own_title_and_hint(kind: str):
    assert title_for(kind) != title_for("unbekannt")
    assert gitmod.hint_for(kind)


MARKED = "<<<<<<< HEAD\nvelocity: 5\n=======\nvelocity: 7\n>>>>>>> origin/main\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_files_with_conflict_markers_are_not_committed_or_shared(
    alice: Person, remote: Path, newline: str
):
    """Markierungen ohne offenes Zusammenführen (z. B. nach einem Git-Client) würden sonst
    geteilt und sperrten die Bearbeitung bei allen anderen."""
    before = git(remote, "rev-parse", "main")
    alice.write("a/2026.2.yaml", MARKED.replace("\n", newline))
    result = alice.sync("Mit Markierungen")
    assert result.error is not None and result.error.kind == "conflict"
    assert "teams/a/2026.2.yaml" in str(result.error)  # Pfad statt nur des Dateinamens
    assert "Konflikte lösen" in result.error.hint
    assert not result.committed and not result.pushed
    assert git(remote, "rev-parse", "main") == before  # nichts hochgeladen
    assert git(alice.root, "log", "-1", "--format=%s") == "Start"  # nichts committet
    with pytest.raises(GitError) as caught:
        gitmod.commit_directory(alice.data, "Noch einmal")
    assert caught.value.kind == "conflict"


def test_message_names_the_team_when_several_teams_have_the_same_file(alice: Person):
    alice.write("a/2026.2.yaml", MARKED)
    alice.write("b/2026.2.yaml", MARKED)
    with pytest.raises(GitError) as caught:
        gitmod.commit_directory(alice.data, "Beide")
    text = str(caught.value) + caught.value.hint
    assert "teams/a/2026.2.yaml" in text and "teams/b/2026.2.yaml" in text


def test_other_changes_are_shared_once_the_marked_file_is_gone(alice: Person, remote: Path):
    alice.write("a/2026.2.yaml", MARKED)
    alice.write("a/2026.3.yaml", "velocity: 7\n")
    assert alice.sync("Mit Markierungen").error is not None
    (alice.data / "a" / "2026.2.yaml").unlink()  # die Datei ist weg: der Rest lässt sich teilen
    invalidate_status()
    result = alice.sync("Ohne Markierungen")
    assert result.ok and result.committed and result.pushed
    assert git(remote, "show", "main:teams/a/2026.3.yaml") == "velocity: 7"
    assert git(remote, "ls-tree", "--name-only", "main", "teams/a/").count("2026.2.yaml") == 0


@pytest.mark.parametrize(
    "how", ["yml", "tracked-modified", "renamed"], ids=["yml", "tracked", "renamed"]
)
def test_conflict_markers_are_refused_for_other_kinds_of_change(alice: Person, how: str):
    if how == "yml":
        alice.write("a/notizen.yml", MARKED)
    elif how == "tracked-modified":
        alice.write("a/2026.1.yaml", MARKED)  # eine bereits verfolgte Datei, Status „M“
    else:
        alice.write("a/2026.1.yaml", MARKED)
        git(alice.root, "mv", "teams/a/2026.1.yaml", "teams/a/2026.5.yaml")  # Status „R“
    invalidate_status()
    with pytest.raises(GitError) as caught:
        gitmod.commit_directory(alice.data, "Mit Markierungen")
    assert caught.value.kind == "conflict"
    assert git(alice.root, "log", "-1", "--format=%s") == "Start"


def test_deleted_tracked_file_is_not_checked(alice: Person):
    (alice.data / "a" / "2026.1.yaml").unlink()
    invalidate_status()
    assert gitmod.commit_directory(alice.data, "Datei entfernt")


def test_markdown_with_a_line_of_equal_signs_is_not_mistaken_for_a_conflict(alice: Person):
    alice.write("a/NOTIZ.md", "<<<<<<< x\n=======\n>>>>>>> y\n")  # nur Datendateien werden geprüft
    assert alice.sync("Notiz").ok


def test_commit_of_given_files_refuses_conflict_markers(alice: Person):
    file = alice.write("a/2026.2.yaml", MARKED)
    with pytest.raises(GitError, match="Konfliktmarkierungen") as caught:
        gitmod.commit([file], "Mit Markierungen")
    assert caught.value.kind == "conflict"
    assert git(alice.root, "log", "-1", "--format=%s") == "Start"


def test_finishing_an_open_merge_does_not_commit_leftover_markers(
    alice: Person, bob: Person, remote: Path
):
    """Wer die Datei im Git-Client als gelöst vormerkt, ohne die Markierungen zu entfernen, kann
    das Zusammenführen nicht über „Speichern und teilen“ abschließen und hochladen."""
    conflict_between_alice_and_bob(alice, bob)
    git(bob.root, "add", "--", FILE)  # „gelöst“, aber die Markierungen stehen noch darin
    assert "<<<<<<<" in (bob.root / FILE).read_text()
    result = bob.sync("Abschließen")
    assert result.error is not None and result.error.kind == "conflict"
    assert not result.pushed
    assert (bob.root / ".git" / "MERGE_HEAD").exists()  # das Zusammenführen bleibt offen
    assert git(remote, "show", f"main:{FILE}").startswith("velocity: 11")  # Server unverändert


def test_protocols_travel_through_the_server(alice: Person, bob: Person):
    """Planning and review minutes are plain Markdown files below ``<team>/protokolle`` and must
    be shared like the sprint files."""
    name = "a/protokolle/2026.1-planning-20260101-100000-ab12.md"
    alice.write(name, "# Planning\n\nBody\n")
    assert alice.sync("Protokoll").ok
    assert git(alice.root, "ls-files", f"teams/{name}")
    result = bob.sync("nichts")
    assert result.error is None
    assert (bob.data / name).read_text(encoding="utf-8") == "# Planning\n\nBody\n"


def test_pull_takes_over_server_state_without_pushing(alice: Person, bob: Person, remote: Path):
    alice.write("a/protokolle/2026.1-review-20260102-100000-cd34.md", "# Review\n")
    assert alice.sync("Protokoll").ok
    bob.write("a/2026.2.yaml", "velocity: 7\n")  # open change of Bob: saved, never uploaded
    before = git(remote, "rev-parse", "main")
    result = bob.sync("lokal", push=False)
    assert result.error is None and not result.pushed and result.committed
    assert (bob.data / "a/protokolle/2026.1-review-20260102-100000-cd34.md").exists()
    assert git(remote, "rev-parse", "main") == before
    assert gitsync.state(bob.data).ahead >= 1


def test_protocols_travel_with_teams_in_repository_root(alice: Person, bob: Person):
    """Teams directly in the repository root (no ``teams`` folder): the data folder is the root."""
    name = "a/protokolle/2026.1-review-20260103-100000-ef56.md"
    (alice.root / "a").mkdir(exist_ok=True)
    (alice.root / name).parent.mkdir(parents=True, exist_ok=True)
    (alice.root / name).write_text("# Review\n", encoding="utf-8")
    invalidate_status()
    result = gitsync.sync(alice.root, "Protokoll im Root")
    assert result.error is None and result.pushed
    assert gitmod_ls(alice.root, name)
    result = gitsync.sync(bob.root, "nichts")
    assert result.error is None
    assert (bob.root / name).read_text(encoding="utf-8") == "# Review\n"


def gitmod_ls(root: Path, name: str) -> str:
    return git(root, "ls-files", name)


def _gitlab_like(remote: Path) -> Path:
    """A server that accepts push options and answers like GitLab; records the options."""
    git(remote, "config", "receive.advertisePushOptions", "true")
    log = remote / "push-options.log"
    hook = remote / "hooks" / "post-receive"
    hook.write_text(
        "#!/bin/sh\n"
        'i=0; line="$GIT_PUSH_OPTION_COUNT"\n'
        'while [ "$i" -lt "$GIT_PUSH_OPTION_COUNT" ]; do\n'
        '  eval "line=\\"\\$line:\\$GIT_PUSH_OPTION_$i\\""; i=$((i+1))\n'
        "done\n"
        f'echo "$line" >> "{log}"\n'
        'echo "remote: View merge request for x:" >&2\n'
        'echo "remote:   https://gitlab.example.org/team/data/-/merge_requests/7" >&2\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return log


def test_share_via_merge_request_pushes_own_branch(alice: Person, bob: Person, remote: Path):
    log = _gitlab_like(remote)
    gitsync.set_share_mode(bob.data, gitsync.SHARE_MERGE_REQUEST)
    assert gitsync.share_mode(bob.data) == gitsync.SHARE_MERGE_REQUEST
    main_before = git(remote, "rev-parse", "main")
    bob.write("a/2026.2.yaml", "velocity: 7\n")
    result = bob.sync("Sprint 2 geplant")
    assert result.error is None and result.pushed
    branch = result.merge_request_branch
    assert branch and branch.startswith("sprintforecast/bob-")
    assert result.merge_request_url == "https://gitlab.example.org/team/data/-/merge_requests/7"
    assert git(remote, "rev-parse", "main") == main_before  # main stays untouched
    assert git(remote, "log", "-1", "--format=%s", branch) == "Sprint 2 geplant"
    options = log.read_text(encoding="utf-8")
    assert "merge_request.create" in options and "merge_request.target=main" in options
    again = bob.sync("nochmal")  # still ahead of main (not merged yet): nothing new, no error
    assert again.error is None and git(remote, "rev-parse", "main") == main_before


def test_share_mode_defaults_to_direct(alice: Person):
    assert gitsync.share_mode(alice.data) == gitsync.SHARE_DIRECT
    gitsync.set_share_mode(alice.data, gitsync.SHARE_MERGE_REQUEST)
    gitsync.set_share_mode(alice.data, gitsync.SHARE_DIRECT)
    assert gitsync.share_mode(alice.data) == gitsync.SHARE_DIRECT


def test_merge_request_squash_merge_does_not_stay_ahead(alice: Person, bob: Person, remote: Path):
    """After the server squashes Bob's merge request (new commit, same content) his main is reset
    to the server state instead of sharing an empty merge request again and again."""
    _gitlab_like(remote)
    gitsync.set_share_mode(bob.data, gitsync.SHARE_MERGE_REQUEST)
    bob.write("a/2026.2.yaml", "velocity: 7\n")
    first = bob.sync("Sprint 2")
    assert first.error is None
    # The server squashes: main gets the same content as one new commit.
    squash = alice.root.parent / "squasher"
    git(alice.root.parent, "clone", "-q", str(remote), str(squash))
    git(squash, "config", "user.name", "S")
    git(squash, "config", "user.email", "s@example.org")
    (squash / "teams/a/2026.2.yaml").write_text("velocity: 7\n", encoding="utf-8")
    git(squash, "add", "-A")
    git(squash, "commit", "-qm", "Squash")
    git(squash, "push", "-q", "origin", "main")
    again = bob.sync("nochmal")
    assert again.error is None and again.merge_request_url is None
    assert (gitsync.state(bob.data).ahead, gitsync.state(bob.data).behind) == (0, 0)


def test_merge_request_branch_is_overwritten_when_it_diverged(
    alice: Person, bob: Person, remote: Path
):
    _gitlab_like(remote)
    gitsync.set_share_mode(bob.data, gitsync.SHARE_MERGE_REQUEST)
    bob.write("a/2026.2.yaml", "velocity: 7\n")
    branch = bob.sync("eins").merge_request_branch
    # Somebody rewrites the merge request branch on the server (rebase button).
    git(remote, "update-ref", f"refs/heads/{branch}", git(remote, "rev-parse", "main"))
    bob.write("a/2026.3.yaml", "velocity: 8\n")
    result = bob.sync("zwei")
    assert result.error is None and result.pushed
    assert git(remote, "log", "-1", "--format=%s", branch) == "zwei"


def test_merge_request_auto_merge_option_and_pull_hint(alice: Person, bob: Person, remote: Path):
    log = _gitlab_like(remote)
    gitsync.set_share_mode(bob.data, gitsync.SHARE_MERGE_REQUEST)
    assert gitsync.auto_merge(bob.data)  # default: on
    bob.write("a/2026.2.yaml", "velocity: 7\n")
    assert bob.sync("mit Automerge").error is None
    assert "merge_request.merge_when_pipeline_succeeds" in log.read_text(encoding="utf-8")
    pulled = bob.sync("holen", push=False)  # his merge request is still open
    assert pulled.error is None and any("Merge Request" in note for note in pulled.notes)
    gitsync.set_auto_merge(bob.data, False)
    assert not gitsync.auto_merge(bob.data)
    log.write_text("", encoding="utf-8")
    bob.write("a/2026.3.yaml", "velocity: 8\n")
    assert bob.sync("ohne").error is None
    assert "merge_when_pipeline_succeeds" not in log.read_text(encoding="utf-8")
