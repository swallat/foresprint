# SPDX-License-Identifier: EUPL-1.2
"""„Speichern und teilen“ mit echten Git-Repositories: ein Server (bare) und zwei Klone."""

import http.server
import subprocess
import threading
from datetime import date
from pathlib import Path

import pytest
import yaml
from gitrepos import Denying, Person, git, make_clone

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
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "gibt-es-nicht.git"))
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Offline")
    assert result.error and result.error.kind == "offline"
    assert result.committed and not result.pushed
    state = gitsync.state(alice.data)
    assert state.offline and state.ahead == 1


def test_timeout_counts_as_offline():
    assert classify("", timeout=True).kind == "offline"


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
            raise classify(message)
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
        raise classify(message)

    monkeypatch.setattr(gitmod, "_git", failing)
    with pytest.raises(GitError) as info:
        clone_repository(url, tmp_path / "ziel")
    assert info.value.kind == "auth"
    assert expected in info.value.hint and absent not in info.value.hint


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
    assert gitsync.reattach(alice.data) == "main"
    assert gitsync.state(alice.data).branch == "main"


def test_reattach_rescues_orphan_commits(alice: Person):
    git(alice.root, "checkout", "-q", "--detach")
    (alice.root / "teams" / "a" / "neu.yaml").write_text("x: 1\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "auf losem Stand")
    invalidate_status()
    assert gitsync.reattach(alice.data) == "main"
    assert "rettung-" in git(alice.root, "branch", "--list")


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
    ],
)
def test_classify(text: str, kind: str):
    assert classify(text).kind == kind
