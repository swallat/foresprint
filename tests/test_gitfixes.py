# SPDX-License-Identifier: EUPL-1.2
"""Nachbesserungen an der Git-Synchronisation (Befunde K1–K2, W1–W7, M1–M6): jeweils mit
echten Git-Repositories."""

import os
import shutil
import sys
from pathlib import Path

import pytest
from gitrepos import Person, git, rmtree_force

from sprintforecast import config, githistory, gitsync, storage
from sprintforecast import git as gitmod
from sprintforecast.git import GitError, invalidate_status, pending_changes, repo_root
from sprintforecast.model import Sprint
from sprintforecast.storage import ConflictError, DataError, Repository
from sprintforecast.yamlmerge import merge3

posix = pytest.mark.skipif(sys.platform == "win32", reason="Dateinamen mit Anführungszeichen")


@pytest.fixture
def solo(tmp_path: Path) -> Path:
    """Repository, dessen Wurzel selbst der Datenordner ist (der Normalfall)."""
    root = tmp_path / "solo"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.name", "Solo")
    git(root, "config", "user.email", "solo@example.org")
    (root / "a").mkdir()
    (root / "a" / "team.yaml").write_text("name: A\n", encoding="utf-8")
    (root / "b.yaml").write_text("v: 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Start")
    invalidate_status()
    return root


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    invalidate_status()
    return git(root, "rev-parse", "HEAD")


# --- K1: Wiederherstellen darf nichts Ungespeichertes überschreiben --------------------------


@pytest.mark.parametrize("scope", ["", "a"])
def test_restore_refuses_open_changes_when_data_folder_is_the_repo_root(solo: Path, scope: str):
    first = git(solo, "rev-parse", "HEAD")
    (solo / "a" / "team.yaml").write_text("name: B\n", encoding="utf-8")
    commit_all(solo, "Zwei")
    (solo / "a" / "team.yaml").write_text("name: ungespeichert\n", encoding="utf-8")
    invalidate_status()
    head = git(solo, "rev-parse", "HEAD")
    with pytest.raises(GitError) as info:
        githistory.restore_version(solo, solo / scope if scope else solo, first)
    assert info.value.kind == "dirty"
    assert (solo / "a" / "team.yaml").read_text(encoding="utf-8") == "name: ungespeichert\n"
    assert git(solo, "rev-parse", "HEAD") == head


def test_restore_does_not_commit_untracked_files(solo: Path):
    first = git(solo, "rev-parse", "HEAD")
    (solo / "b.yaml").write_text("v: 2\n", encoding="utf-8")
    commit_all(solo, "Zwei")
    (solo / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    invalidate_status()
    head = git(solo, "rev-parse", "HEAD")
    with pytest.raises(GitError) as info:
        githistory.restore_version(solo, solo, first)
    assert info.value.kind == "dirty"
    assert git(solo, "rev-parse", "HEAD") == head
    assert (solo / "neu.yaml").exists()


# --- K2: Pfade mit Sonderzeichen -------------------------------------------------------------

NAMES = ["ä.yaml", 'q"uote.yaml', "tab\there.yaml", "ünï cödé/ß.yaml"]


@posix
@pytest.mark.parametrize("name", NAMES)
def test_special_paths_discard_history_and_restore(solo: Path, name: str):
    file = solo / name
    file.parent.mkdir(exist_ok=True)
    file.write_text("v: 1\n", encoding="utf-8")
    first = commit_all(solo, "eins")
    file.write_text("v: 2\nw: 2\n", encoding="utf-8")
    invalidate_status()
    assert pending_changes(solo) == [("M", name)]
    lost = githistory.discard_preview(solo)
    assert [(item.file, item.added, item.removed) for item in lost] == [(name, 2, 1)]
    githistory.discard(solo)
    assert file.read_text(encoding="utf-8") == "v: 1\n"
    assert git(solo, "status", "--porcelain") == ""

    file.write_text("v: 3\n", encoding="utf-8")
    commit_all(solo, "drei")
    assert name in githistory.history(solo)[0].files
    githistory.restore_version(solo, solo, first)
    assert file.read_text(encoding="utf-8") == "v: 1\n"
    assert git(solo, "status", "--porcelain") == ""


@posix
def test_special_paths_discard_untracked_and_deleted(solo: Path):
    (solo / "ä neu.yaml").write_text("x: 1\n", encoding="utf-8")
    (solo / "b.yaml").unlink()
    (solo / 'x"y.yaml').write_text("x: 1\n", encoding="utf-8")
    invalidate_status()
    githistory.discard(solo)
    assert git(solo, "status", "--porcelain") == ""
    assert (solo / "b.yaml").exists() and not (solo / "ä neu.yaml").exists()


@posix
def test_restore_removes_files_with_special_names_that_did_not_exist_then(solo: Path):
    first = git(solo, "rev-parse", "HEAD")
    (solo / "späte Datei.yaml").write_text("x: 1\n", encoding="utf-8")
    commit_all(solo, "später")
    githistory.restore_version(solo, solo, first)
    assert not (solo / "späte Datei.yaml").exists()


# --- W1: Umbenennungen und gemischte Zustände beim Verwerfen ---------------------------------


def test_discard_staged_rename_restores_the_old_name(solo: Path):
    git(solo, "mv", "b.yaml", "c.yaml")
    invalidate_status()
    lost = githistory.discard_preview(solo)
    assert [(item.status, item.file, item.orig) for item in lost] == [("R", "c.yaml", "b.yaml")]
    githistory.discard(solo)
    assert (solo / "b.yaml").read_text() == "v: 1\n" and not (solo / "c.yaml").exists()
    assert git(solo, "status", "--porcelain") == ""


def test_discard_rename_with_changes(solo: Path):
    git(solo, "mv", "b.yaml", "c.yaml")
    (solo / "c.yaml").write_text("v: 1\nw: 2\n", encoding="utf-8")
    invalidate_status()
    githistory.discard(solo)
    assert (solo / "b.yaml").read_text() == "v: 1\n" and not (solo / "c.yaml").exists()
    assert git(solo, "status", "--porcelain") == ""


def test_discard_added_then_deleted_file(solo: Path):
    (solo / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    git(solo, "add", "neu.yaml")
    (solo / "neu.yaml").unlink()
    invalidate_status()
    githistory.discard(solo)
    assert git(solo, "status", "--porcelain") == ""


# --- W2/W3: Tags ----------------------------------------------------------------------------


def test_local_only_tag_is_listed_and_can_be_uploaded(alice: Person, remote: Path, tmp_path: Path):
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "weg.git"))
    assert githistory.set_tag(alice.data, "a/lokal") is not None
    git(alice.root, "remote", "set-url", "origin", str(remote))
    tags = githistory.list_tags(alice.data, check_server=True)
    assert [(t.name, t.local, t.on_server) for t in tags] == [("a/lokal", True, False)]
    githistory.upload_tag(alice.data, "a/lokal")
    assert "a/lokal" in git(remote, "tag")
    assert githistory.list_tags(alice.data, check_server=True)[0].on_server is True


def test_set_tag_is_idempotent_after_failed_upload(alice: Person, remote: Path, tmp_path: Path):
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "weg.git"))
    assert githistory.set_tag(alice.data, "a/x") is not None
    git(alice.root, "remote", "set-url", "origin", str(remote))
    assert githistory.set_tag(alice.data, "a/x") is None  # gleicher Stand: nur hochladen
    assert "a/x" in git(remote, "tag")
    assert githistory.set_tag(alice.data, "a/x") is None
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Weiter").ok
    with pytest.raises(GitError, match="existiert bereits"):
        githistory.set_tag(alice.data, "a/x")  # anderer Stand: weiterhin abgelehnt


def test_server_only_tag_is_listed_and_can_be_deleted(alice: Person, remote: Path):
    git(remote, "tag", "a/server", git(remote, "rev-parse", "main"))
    assert githistory.list_tags(alice.data) == []
    tags = githistory.list_tags(alice.data, check_server=True)
    assert [(t.name, t.local, t.on_server) for t in tags] == [("a/server", False, True)]
    assert githistory.delete_tag(alice.data, "a/server") is None
    assert git(remote, "tag") == ""
    assert githistory.delete_tag(alice.data, "a/server") is None  # gibt es nirgends mehr


def test_delete_tag_heals_after_partial_failure(alice: Person, remote: Path, tmp_path: Path):
    assert githistory.set_tag(alice.data, "a/y") is None
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "weg.git"))
    assert githistory.delete_tag(alice.data, "a/y") is not None  # lokal weg, Server behält
    git(alice.root, "remote", "set-url", "origin", str(remote))
    assert "a/y" in git(remote, "tag")
    assert githistory.delete_tag(alice.data, "a/y") is None
    assert git(remote, "tag") == ""


@pytest.mark.parametrize("name", ["-f", "--list", "-d", "-a"])
def test_tag_names_with_leading_dash_are_rejected(alice: Person, name: str):
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        githistory.set_tag(alice.data, name)
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        githistory.delete_tag(alice.data, name)
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        githistory.upload_tag(alice.data, name)
    assert githistory.list_tags(alice.data) == []


def test_tag_name_equal_to_branch_name_is_listed_plain(alice: Person):
    git(alice.root, "branch", "x")
    assert githistory.set_tag(alice.data, "x") is None
    assert [t.name for t in githistory.list_tags(alice.data)] == ["x"]


def test_clone_rejects_option_like_url(tmp_path: Path):
    with pytest.raises(GitError) as info:
        gitmod.clone_repository("--upload-pack=touch boese", tmp_path / "ziel")
    assert info.value.kind == "bad_url"
    assert not (tmp_path / "ziel").exists()


def test_clone_with_double_dash_still_works(alice: Person, remote: Path, tmp_path: Path):
    gitmod.clone_repository(str(remote), tmp_path / "geklont")
    assert (tmp_path / "geklont" / "teams" / "a" / "team.yaml").exists()


# --- W4: Upstream-Ref fehlt -------------------------------------------------------------------


def test_sync_against_a_new_empty_server(alice: Person, tmp_path: Path):
    empty = tmp_path / "leer.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(empty))
    git(alice.root, "remote", "set-url", "origin", str(empty))
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Umzug")
    assert result.ok, result.error
    assert result.pushed
    assert git(empty, "log", "-1", "--format=%s", "main") == "Umzug"


# --- W5: erster Push gegen einen Server mit demselben Branch ---------------------------------


def make_stranger(tmp_path: Path, remote: Path, files: dict[str, str]) -> Person:
    root = tmp_path / "carol"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.name", "Carol")
    git(root, "config", "user.email", "carol@example.org")
    git(root, "remote", "add", "origin", str(remote))
    person = Person("Carol", root)
    for rel, text in files.items():
        person.write(rel, text)
    return person


def test_first_share_against_server_with_unrelated_history_is_refused(
    alice: Person, remote: Path, tmp_path: Path
):
    server_head = git(remote, "rev-parse", "main")
    carol = make_stranger(tmp_path, remote, {"a/2026.2.yaml": "velocity: 5\n"})
    result = carol.sync("Carol startet")
    assert result.error is not None and result.error.kind == "unrelated_histories"
    assert str(remote) in str(result.error) and "main" in str(result.error)
    assert "ausdrücklich" in result.error.hint
    assert result.committed  # die eigenen Änderungen sind gesichert
    assert not result.pushed and not result.merged
    assert git(remote, "rev-parse", "main") == server_head
    assert not (carol.data / "a" / "team.yaml").exists()
    assert gitsync.state(carol.data).upstream is None  # auch nicht verbunden


def test_first_share_against_server_with_unrelated_history_when_confirmed(
    alice: Person, remote: Path, tmp_path: Path
):
    carol = make_stranger(tmp_path, remote, {"a/2026.2.yaml": "velocity: 5\n"})
    result = carol.sync("Carol startet", allow_unrelated=True)
    assert result.ok, result.error
    assert result.pushed and result.merged
    assert (carol.data / "a" / "team.yaml").exists() and (carol.data / "a" / "2026.2.yaml").exists()
    assert git(carol.root, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_code_repository_on_the_server_is_not_merged_silently(remote: Path, tmp_path: Path):
    code = tmp_path / "code"
    git(tmp_path, "init", "-q", "-b", "main", str(code))
    git(code, "config", "user.name", "Dev")
    git(code, "config", "user.email", "dev@example.org")
    (code / "app.py").write_text("print('hallo')\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-qm", "Code")
    git(code, "push", "-q", str(remote), "main")
    server_head = git(remote, "rev-parse", "main")
    carol = make_stranger(tmp_path, remote, {"a/team.yaml": "name: A\n"})
    result = carol.sync("Daten")
    assert result.error is not None and result.error.kind == "unrelated_histories"
    assert git(remote, "rev-parse", "main") == server_head
    assert not (carol.root / "app.py").exists()


def test_unrelated_histories_with_same_named_gitignore_and_readme(
    alice: Person, remote: Path, tmp_path: Path
):
    (alice.root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (alice.root / "README.md").write_text("Alices Daten\n", encoding="utf-8")
    git(alice.root, "add", ".gitignore", "README.md")
    git(alice.root, "commit", "-qm", "Dateien im Hauptordner")
    assert alice.sync("Weiter").ok
    carol = make_stranger(tmp_path, remote, {"a/2026.2.yaml": "velocity: 5\n"})
    (carol.root / ".gitignore").write_text("*.bak\n", encoding="utf-8")
    (carol.root / "README.md").write_text("Carols Daten\n", encoding="utf-8")
    git(carol.root, "add", ".gitignore", "README.md")
    git(carol.root, "commit", "-qm", "Carols Hauptordner")
    refused = carol.sync("Carol startet")
    assert refused.error is not None and refused.error.kind == "unrelated_histories"
    assert gitsync.state(carol.data).unfinished is None
    result = carol.sync("Carol startet", allow_unrelated=True)
    assert result.error is not None and result.error.kind == "conflict"
    assert sorted(c.file for c in result.conflicts) == [".gitignore", "README.md"]
    assert all(c.whole for c in result.conflicts)
    assert gitsync.state(carol.data).unfinished == "merge"


def test_reinitialised_server_is_refused_even_with_connected_upstream(
    alice: Person, remote: Path, tmp_path: Path
):
    rmtree_force(remote)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    fresh = tmp_path / "frisch"
    git(tmp_path, "init", "-q", "-b", "main", str(fresh))
    git(fresh, "config", "user.name", "Neu")
    git(fresh, "config", "user.email", "neu@example.org")
    (fresh / "README.md").write_text("neu\n", encoding="utf-8")
    git(fresh, "add", "-A")
    git(fresh, "commit", "-qm", "Neu aufgesetzt")
    git(fresh, "push", "-q", str(remote), "main")
    server_head = git(remote, "rev-parse", "main")
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Weiter")
    assert result.error is not None and result.error.kind == "unrelated_histories"
    assert result.committed and not result.merged and not result.pushed
    assert git(remote, "rev-parse", "main") == server_head
    assert gitsync.state(alice.data).upstream == "origin/main"


def test_merge_base_errors_are_not_mistaken_for_unrelated_histories(alice: Person):
    with pytest.raises(GitError):
        gitsync._unrelated(alice.root, "origin", "origin/gibt-es-nicht")


def test_shallow_clone_is_not_mistaken_for_unrelated_histories(
    alice: Person, remote: Path, tmp_path: Path
):
    shallow = tmp_path / "flach"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{remote}", str(shallow))
    git(shallow, "config", "user.name", "Flach")
    git(shallow, "config", "user.email", "flach@example.org")
    for i in (1, 2):
        alice.write("a/x.yaml", f"v: {i}\n")
        assert alice.sync(f"Stand {i}").ok
    git(shallow, "fetch", "-q", "--depth", "1", "origin")  # abgeschnittene, getrennte Spitze
    person = Person("Flach", shallow)
    person.write("b/team.yaml", "name: B\n")
    result = person.sync("Flach", allow_invalid=True)  # die Testdaten sind fachlich unvollständig
    assert result.ok, result.error
    assert result.pushed
    assert git(shallow, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_first_share_with_unrelated_history_and_conflict(
    alice: Person, remote: Path, tmp_path: Path
):
    carol = make_stranger(tmp_path, remote, {"a/team.yaml": "name: Anders\n"})
    result = carol.sync("Carol startet", allow_unrelated=True)
    assert result.error is not None and result.error.kind == "conflict"
    assert [c.file for c in result.conflicts] == ["teams/a/team.yaml"]
    assert gitsync.state(carol.data).unfinished == "merge"


# --- W6: Einstellungen -----------------------------------------------------------------------


def test_config_update_reports_unwritable_settings(tmp_path: Path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocker))
    monkeypatch.setenv("APPDATA", str(blocker))
    with pytest.raises(config.SettingsError, match="Einstellungen"):
        config.update(a=1)


def test_config_update_is_atomic(monkeypatch):
    config.update(a=1)
    file = config.config_dir() / "settings.json"

    def broken(*args, **kwargs):
        raise OSError("gesperrt")

    real = os.replace
    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(config.SettingsError):
        config.update(a=2)
    monkeypatch.setattr(os, "replace", real)
    assert config.load() == {"a": 1}
    assert [p.name for p in file.parent.iterdir()] == ["settings.json"]  # keine Reste


def test_config_update_keeps_a_damaged_file():
    file = config.config_dir() / "settings.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('{"data_dir": "/x", "hal', encoding="utf-8")
    config.update(a=1)
    assert config.load() == {"a": 1}
    assert (file.parent / "settings.json.defekt").read_text(encoding="utf-8").startswith('{"data')


def test_recent_data_dirs_ignore_empty_entries():
    config.update(recent_data_dirs=["", "  ", "/irgendwo"])
    assert storage.recent_data_dirs() == [Path("/irgendwo")]


# --- W7: Wurzel-Cache --------------------------------------------------------------------------


def test_init_data_repository_is_seen_immediately(tmp_path: Path):
    folder = tmp_path / "neu"
    folder.mkdir()
    assert repo_root(folder) is None  # wird zwischengespeichert
    gitmod.init_data_repository(folder)
    assert repo_root(folder) == folder.resolve()


def test_clone_is_seen_immediately(alice: Person, remote: Path, tmp_path: Path):
    target = tmp_path / "geklont"
    assert repo_root(target) is None
    gitmod.clone_repository(str(remote), target)
    assert repo_root(target) == target.resolve()


# --- M1: Papierkorb und Zurücknehmen -----------------------------------------------------------


def test_trash_folders_never_collide(solo: Path, monkeypatch):
    monkeypatch.setattr(githistory.time, "strftime", lambda *a: "20260101-000000")
    (solo / "b.yaml").write_text("v: 11\n", encoding="utf-8")
    first = githistory.discard(solo)
    (solo / "b.yaml").write_text("v: 22\n", encoding="utf-8")
    second = githistory.discard(solo)
    assert first and second and first != second
    assert (first / "b.yaml").read_text() == "v: 11\n"
    assert (second / "b.yaml").read_text() == "v: 22\n"


def test_discard_stops_before_changing_anything_if_backup_fails(solo: Path, monkeypatch):
    (solo / "b.yaml").write_text("v: 11\n", encoding="utf-8")

    def broken(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(githistory.shutil, "copy2", broken)
    with pytest.raises(GitError, match="Sicherung"):
        githistory.discard(solo)
    assert (solo / "b.yaml").read_text() == "v: 11\n"


def test_revert_names_missing_identity_correctly(solo: Path, monkeypatch: pytest.MonkeyPatch):
    # Bytes mit LF: ``write_text`` schriebe unter Windows CRLF, und ohne die Systemeinstellung
    # ``core.autocrlf`` (unten abgeschaltet) gälte die Datei danach als geändert.
    (solo / "b.yaml").write_bytes(b"v: 2\n")
    rev = commit_all(solo, "Zwei")
    git(solo, "config", "--unset", "user.name")
    git(solo, "config", "--unset", "user.email")
    git(solo, "config", "user.useConfigOnly", "true")
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("EMAIL", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Keine Benutzereinstellungen des Rechners (unter Windows: USERPROFILE statt HOME): sonst
    # fände Git dort einen Namen und der Test sähe nie „keine Identität“.
    empty_config = solo.parent / "leer.gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    for variable in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(variable, str(solo / "leer"))
    with pytest.raises(GitError) as info:
        githistory.revert_commit(solo, rev)
    assert info.value.kind == "identity"


def test_revert_checks_the_whole_repository_for_open_changes(alice: Person):
    (alice.root / "readme.txt").write_text("a\n")
    git(alice.root, "add", "readme.txt")
    git(alice.root, "commit", "-qm", "readme")
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Zwei").ok
    rev = githistory.history(alice.data)[0].rev
    (alice.root / "readme.txt").write_text("geändert\n")
    invalidate_status()
    with pytest.raises(GitError) as info:
        githistory.revert_commit(alice.data, rev)
    assert info.value.kind == "dirty"


# --- M2: Sprint-Tag-Wettlauf -----------------------------------------------------------------


def test_sync_reports_a_sprint_tag_already_taken_on_the_server(alice: Person, bob: Person):
    alice.write("a/s1.yaml", "velocity: 1\n")
    assert alice.sync("A", ["a/1"]).ok
    bob.write("a/s2.yaml", "velocity: 2\n")
    result = bob.sync("B", ["a/1"])
    assert result.ok and result.pushed
    assert any("a/1" in note for note in result.notes)


def test_sync_has_no_note_when_tags_arrive(alice: Person):
    alice.write("a/s1.yaml", "velocity: 1\n")
    result = alice.sync("A", ["a/1"])
    assert result.ok and result.notes == []


# --- M3: ungültige Datumswerte -------------------------------------------------------------


def test_invalid_date_in_a_file_is_a_data_error(tmp_path: Path):
    file = tmp_path / "s.yaml"
    file.write_text("start: 2026-13-45\n", encoding="utf-8")
    with pytest.raises(DataError):
        storage._read(file)


def test_invalid_date_in_a_conflicting_file_is_decided_as_a_whole(alice: Person, bob: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    bob.write("a/2026.1.yaml", "velocity: 12\nstart: 2026-13-45\n")
    assert alice.sync("A").ok
    result = bob.sync("B")
    assert result.error is not None and result.error.kind == "conflict"
    assert result.conflicts[0].whole


# --- M4: übrig gebliebene Zwischendateien -------------------------------------------------------


def test_write_leaves_no_tmp_file_after_unexpected_error(tmp_path: Path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("Absturz")

    monkeypatch.setattr(storage.os, "replace", broken)
    with pytest.raises(RuntimeError):
        storage._write(tmp_path / "x.yaml", "# h\n", {"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_new_data_repositories_ignore_tmp_files(tmp_path: Path):
    gitmod.init_data_repository(tmp_path / "daten")
    assert "*.tmp" in (tmp_path / "daten" / ".gitignore").read_text().splitlines()


def test_tmp_files_in_new_data_repositories_stay_out_of_git(tmp_path: Path):
    root = tmp_path / "daten"
    teams = gitmod.init_data_repository(root)
    (teams / "tmpk3j2h1.tmp").write_text("halb: geschrieben\n", encoding="utf-8")
    (teams / "team.yaml").write_text("name: A\n", encoding="utf-8")
    status = git(root, "status", "--porcelain", "--untracked-files=all")
    assert "teams/team.yaml" in status
    assert ".tmp" not in status


def test_new_data_repositories_keep_yaml_and_reports_on_lf(tmp_path: Path):
    teams = gitmod.init_data_repository(tmp_path / "daten")
    lines = (teams / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "*.yaml text eol=lf" in lines
    assert "*.yml text eol=lf" in lines
    assert "*.md text eol=lf" in lines
    assert not (
        tmp_path / "daten" / ".gitattributes"
    ).exists()  # nur im Datenordner, der geteilt wird


def test_gitattributes_lies_in_the_data_folder_without_a_teams_folder(tmp_path: Path):
    data = gitmod.init_data_repository(tmp_path / "daten", teams_folder=False)
    assert data == tmp_path / "daten" and (data / ".gitattributes").is_file()


def test_existing_gitattributes_are_not_overwritten(tmp_path: Path):
    root = tmp_path / "daten"
    (root / "teams").mkdir(parents=True)
    (root / "teams" / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    gitmod.init_data_repository(root)
    assert (root / "teams" / ".gitattributes").read_text(encoding="utf-8") == "* -text\n"


def test_existing_gitignore_is_not_overwritten_but_gitattributes_is_added(tmp_path: Path):
    root = tmp_path / "daten"
    root.mkdir()
    (root / ".gitignore").write_text("eigene\n", encoding="utf-8")
    teams = gitmod.init_data_repository(root)
    assert (root / ".gitignore").read_text(encoding="utf-8") == "eigene\n"
    assert (teams / ".gitattributes").is_file()


def test_existing_repositories_stay_untouched(tmp_path: Path):
    """Im Index könnten CRLF-Dateien liegen, die mit einer neuen Festlegung als geändert gälten."""
    root = tmp_path / "daten"
    root.mkdir()
    git(root, "init", "-q")
    teams = gitmod.init_data_repository(root)
    assert not (teams / ".gitattributes").exists()
    assert (root / ".gitignore").is_file()  # wie bisher


def test_gitattributes_is_committed_with_the_data_and_reaches_clones(tmp_path: Path):
    """Der Windows-Fall am Klon: Mit ``core.autocrlf`` läge die Datei dort sonst als CRLF vor,
    und das erste Speichern schriebe alle Zeilenenden auf LF um (Phantom-Änderung)."""
    server = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(server))
    root = tmp_path / "daten"
    teams = gitmod.init_data_repository(root)
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.org")
    (teams / "team.yaml").write_bytes(b"name: A\n")
    gitmod.commit_directory(teams, "Start")
    assert "teams/.gitattributes" in git(root, "ls-files").splitlines()
    git(root, "remote", "add", "origin", str(server))
    git(root, "push", "-q", "origin", "HEAD:main")

    clone = tmp_path / "klon"
    git(tmp_path, "clone", "-q", "-c", "core.autocrlf=true", str(server), str(clone))
    assert (clone / "teams" / "team.yaml").read_bytes() == b"name: A\n"
    (clone / "teams" / "team.yaml").write_bytes(b"name: A\n")  # erneutes Speichern mit LF
    assert pending_changes(clone / "teams") == []


def test_yaml_files_stay_on_lf_in_checkout_despite_autocrlf(tmp_path: Path):
    """Windows-Fall: Mit ``core.autocrlf`` läge die Datei sonst als CRLF vor, und das erste
    Speichern schriebe alle Zeilenenden auf LF um."""
    root = tmp_path / "daten"
    teams = gitmod.init_data_repository(root)
    git(root, "config", "core.autocrlf", "true")
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.org")
    datei = teams / "team.yaml"
    datei.write_bytes(b"name: A\r\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Start")
    datei.unlink()
    git(root, "checkout", "--", "teams/team.yaml")
    assert datei.read_bytes() == b"name: A\n"


def test_data_repository_template_matches_new_repositories(tmp_path: Path):
    root = tmp_path / "daten"
    teams = gitmod.init_data_repository(root)
    template = Path(__file__).resolve().parents[1] / "templates" / "daten-repo"
    assert (template / ".gitignore").read_text(encoding="utf-8") == (root / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert (template / ".gitattributes").read_text(encoding="utf-8") == (
        teams / ".gitattributes"
    ).read_text(encoding="utf-8")


# --- M5: Speichern über Konfliktmarkierungen ------------------------------------------------


MARKED = "<<<<<<< HEAD\nvelocity: 1\n=======\nvelocity: 2\n>>>>>>> origin/main\n"


def test_saving_over_conflict_markers_is_refused(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    team, sprint = data.team, data.sprints[0]
    path = repo.sprint_path("demo", sprint.id)
    path.write_text(MARKED, encoding="utf-8")
    with pytest.raises(ConflictError):
        repo.save_sprint("demo", sprint)
    assert path.read_text(encoding="utf-8") == MARKED
    with pytest.raises(ConflictError):
        repo.save_sprint("demo", Sprint(sprint.id, sprint.start, sprint.end, velocity=3.0))
    (data_dir / "demo" / "team.yaml").write_text(MARKED, encoding="utf-8")
    with pytest.raises(ConflictError):
        repo.save_team(team)


def test_conflict_markers_with_windows_line_endings_are_detected(data_dir: Path):
    """Unter Windows schreibt Git die Markierungen mit CRLF; auch dann darf nichts darüber
    gespeichert werden."""
    crlf = MARKED.replace("\n", "\r\n")
    assert storage.has_conflict_markers(crlf)
    assert not storage.has_conflict_markers("velocity: 1\r\nnote: =======\r\n")
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprints[0]
    path = repo.sprint_path("demo", sprint.id)
    path.write_bytes(crlf.encode("utf-8"))
    with pytest.raises(ConflictError):
        repo.save_sprint("demo", sprint)
    assert path.read_bytes() == crlf.encode("utf-8")  # unverändert


def test_import_over_conflict_markers_is_refused(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprints[0]
    repo.sprint_path("demo", sprint.id).write_text(MARKED, encoding="utf-8")
    with pytest.raises(ConflictError):
        storage.import_sprints(repo, data.team, [sprint])


# --- M6: yamlmerge unterscheidet Wahrheitswerte von Zahlen --------------------------------------


def test_merge_does_not_treat_true_as_one():
    merged, conflicts = merge3({"a": 1}, {"a": True}, {"a": 1})
    assert merged == {"a": True} and merged["a"] is True and conflicts == []
    merged, conflicts = merge3({"a": 0}, {"a": 0}, {"a": False})
    assert merged["a"] is False and conflicts == []
    merged, conflicts = merge3({"a": 1}, {"a": True}, {"a": 2})
    assert [c.path for c in conflicts] == [("a",)]


# --- Review-Nachbesserungen: Tags vor dem Commit prüfen ----------------------------------------


def head_of(person: Person) -> str:
    return git(person.root, "rev-parse", "HEAD")


def test_sync_with_an_existing_tag_aborts_before_committing(alice: Person, remote: Path):
    git(alice.root, "tag", "-a", "-m", "alt", "a/t")
    before = head_of(alice)
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Neu", ["a/t"])
    assert result.error is not None and result.error.kind == "tag_exists"
    assert result.committed is None and not result.pushed
    assert head_of(alice) == before
    assert pending_changes(alice.data)  # die Änderungen sind unverändert offen
    again = alice.sync("Neu", ["a/t"])  # kein stilles Gelingen beim zweiten Mal
    assert again.error is not None and again.error.kind == "tag_exists"
    assert "a/t" not in git(remote, "tag").split()


def test_sync_with_an_invalid_tag_name_aborts_before_committing(alice: Person):
    before = head_of(alice)
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    result = alice.sync("Neu", ["a/ungültig name"])
    assert result.error is not None and "Ungültiger Tag-Name" in str(result.error)
    assert result.committed is None and head_of(alice) == before
    assert pending_changes(alice.data)


def test_sync_adds_a_missing_tag_without_a_new_commit(alice: Person, remote: Path):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "Schon committet")
    invalidate_status()
    before = head_of(alice)
    result = alice.sync("Neu", ["a/nachgeholt"])
    assert result.ok, result.error
    assert result.committed is None and head_of(alice) == before
    assert git(remote, "rev-list", "-n", "1", "a/nachgeholt") == before
    assert result.notes == []


def test_sync_notes_a_tag_that_points_to_another_commit(alice: Person):
    git(alice.root, "tag", "-a", "-m", "alt", "a/alt")
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "Schon committet")
    invalidate_status()
    result = alice.sync("Neu", ["a/alt"])
    assert result.ok, result.error
    assert any("a/alt" in n and "anderen Commit" in n for n in result.notes)


def test_tag_notes_report_a_tag_on_a_foreign_commit(alice: Person):
    tree = git(alice.root, "rev-parse", "HEAD^{tree}")
    foreign = git(alice.root, "commit-tree", tree, "-m", "fremd")
    git(alice.root, "tag", "-a", "-m", "fremd", "a/fremd", foreign)
    current = gitsync.state(alice.data)
    notes = gitsync._tag_notes(alice.root, current, ["a/fremd"])
    assert any("a/fremd" in n and "anderen Commit" in n for n in notes)


def test_commit_invalidates_the_status_cache_even_if_tagging_fails(alice: Person, monkeypatch):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert gitmod.cached_pending_changes(alice.data)  # füllt den Zwischenspeicher
    real = gitmod._git

    def flaky(cwd, *args, **kwargs):
        if args[:1] == ("tag",):
            raise GitError("Tag kaputt")
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git", flaky)
    with pytest.raises(GitError, match="Tag kaputt"):
        gitmod.commit_directory(alice.data, "Neu", ["a/neu"])
    monkeypatch.setattr(gitmod, "_git", real)
    assert gitmod.cached_pending_changes(alice.data) == []  # der Commit ist erfolgt


# --- Tag-Namen -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["HEAD", "@", " a/x", "a/x ", "\ta/x", "  "])
def test_ambiguous_or_padded_tag_names_are_rejected(alice: Person, name: str):
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        githistory.set_tag(alice.data, name)
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        githistory.delete_tag(alice.data, name)
    with pytest.raises(GitError, match="Ungültiger Tag-Name"):
        gitmod.check_name(name)
    assert githistory.list_tags(alice.data) == []


def test_set_tag_refuses_a_name_the_server_has_for_another_version(
    alice: Person, bob: Person, remote: Path
):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Weiter", ["a/s"]).ok  # bob kennt den Tag und den Stand noch nicht
    with pytest.raises(GitError) as info:
        githistory.set_tag(bob.data, "a/s")
    assert info.value.kind == "tag_exists" and "a/s" in str(info.value)
    assert githistory.list_tags(bob.data) == []  # nichts abweichend angelegt


def test_set_tag_adopts_a_server_tag_for_the_same_version(alice: Person, bob: Person):
    assert githistory.set_tag(alice.data, "a/gleich") is None
    assert githistory.set_tag(bob.data, "a/gleich") is None
    assert [t.name for t in githistory.list_tags(bob.data, check_server=True)] == ["a/gleich"]
    assert githistory.list_tags(bob.data, check_server=True)[0].differs is False


# --- Einstellungen: ältere Sicherung bleibt ------------------------------------------------------


def test_config_update_keeps_every_damaged_file():
    file = config.config_dir() / "settings.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('{"erste": ', encoding="utf-8")
    config.update(a=1)
    file.write_text('{"zweite": ', encoding="utf-8")
    config.update(a=2)
    file.write_text('{"dritte": ', encoding="utf-8")
    config.update(a=3)
    backups = [p for p in file.parent.iterdir() if p.name.startswith("settings.json.defekt")]
    assert sorted(p.read_text(encoding="utf-8") for p in backups) == [
        '{"dritte": ',
        '{"erste": ',
        '{"zweite": ',
    ]


# --- Verwerfen: Rollback bei Teilfehler ----------------------------------------------------------


def mixed_state(solo: Path) -> str:
    """Umbenennung (vorgemerkt), gelöschte und geänderte Datei; liefert den Status davor."""
    (solo / "c.yaml").write_text("w: 1\n", encoding="utf-8")
    commit_all(solo, "c")
    git(solo, "mv", "b.yaml", "d.yaml")
    (solo / "a" / "team.yaml").unlink()
    (solo / "c.yaml").write_text("w: 2\n", encoding="utf-8")
    invalidate_status()
    return git(solo, "status", "--porcelain")


def assert_mixed_state(solo: Path) -> None:
    assert (solo / "d.yaml").read_text(encoding="utf-8") == "v: 1\n"
    assert not (solo / "b.yaml").exists()
    assert not (solo / "a" / "team.yaml").exists()
    assert (solo / "c.yaml").read_text(encoding="utf-8") == "w: 2\n"


@pytest.mark.parametrize("fail_after_restore", [False, True])
def test_discard_partial_failure_restores_files_deletions_and_index(
    solo: Path, monkeypatch, fail_after_restore: bool
):
    before = mixed_state(solo)
    real = githistory._git

    def flaky(cwd, *args, **kwargs):
        if args[:1] == ("restore",):
            if fail_after_restore:
                real(cwd, *args, **kwargs)
            raise GitError("kaputt")
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(githistory, "_git", flaky)
    with pytest.raises(GitError) as info:
        githistory.discard(solo)
    monkeypatch.setattr(githistory, "_git", real)
    assert git(solo, "status", "--porcelain") == before  # auch die Umbenennung ist vorgemerkt
    assert_mixed_state(solo)
    assert "wiederhergestellt" in info.value.hint
    assert "nicht vollständig" not in info.value.hint
    assert "sprintforecast-verworfen" in info.value.hint


def test_discard_partial_failure_reports_honestly_what_could_not_be_restored(
    solo: Path, monkeypatch
):
    mixed_state(solo)
    real = githistory._git
    real_copy = shutil.copy2

    def flaky(cwd, *args, **kwargs):
        if args[:1] == ("restore",):
            raise GitError("kaputt")
        return real(cwd, *args, **kwargs)

    def copy(src, dst, *args, **kwargs):
        if ".git" not in Path(dst).parts:  # nur das Zurücklegen scheitert, nicht die Sicherung
            raise OSError("gesperrt")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(githistory, "_git", flaky)
    monkeypatch.setattr(githistory.shutil, "copy2", copy)
    with pytest.raises(GitError) as info:
        githistory.discard(solo)
    hint = info.value.hint
    assert "nicht vollständig" in hint and "c.yaml" in hint
    assert "sprintforecast-verworfen" in hint
    assert "Zustand (Dateien und Vormerkung) wurde wiederhergestellt" not in hint


# --- Wiederherstellen: Rollback und ignorierte Dateien -----------------------------------------


def test_restore_version_failed_commit_rolls_back_completely(solo: Path, monkeypatch):
    first = git(solo, "rev-parse", "HEAD")
    (solo / "b.yaml").write_text("v: 2\n", encoding="utf-8")
    (solo / "a" / "team.yaml").unlink()
    (solo / "neu.yaml").write_text("x: 1\n", encoding="utf-8")
    commit_all(solo, "Zwei")
    head = git(solo, "rev-parse", "HEAD")
    real = githistory._git

    def flaky(cwd, *args, **kwargs):
        if args[:1] == ("commit",):
            raise GitError("Commit kaputt")
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(githistory, "_git", flaky)
    with pytest.raises(GitError, match="Commit kaputt"):
        githistory.restore_version(solo, solo, first)
    monkeypatch.setattr(githistory, "_git", real)
    assert git(solo, "rev-parse", "HEAD") == head
    assert git(solo, "status", "--porcelain") == ""
    assert (solo / "b.yaml").read_text(encoding="utf-8") == "v: 2\n"
    assert not (solo / "a" / "team.yaml").exists()
    assert (solo / "neu.yaml").exists()


def ignored_setup(solo: Path) -> str:
    """Ein früherer Stand verfolgt ``x.tmp``; jetzt ist die Datei ignoriert und lokal anders."""
    (solo / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (solo / "x.tmp").write_text("alt\n", encoding="utf-8")
    git(solo, "add", "-f", "-A")
    git(solo, "commit", "-qm", "mit tmp")
    old = git(solo, "rev-parse", "HEAD")
    git(solo, "rm", "-q", "--cached", "x.tmp")
    git(solo, "commit", "-qm", "ohne tmp")
    (solo / "x.tmp").write_text("lokal wichtig\n", encoding="utf-8")
    invalidate_status()
    assert git(solo, "status", "--porcelain") == ""
    return old


def test_restore_version_saves_ignored_files_it_would_overwrite(solo: Path):
    old = ignored_setup(solo)
    githistory.restore_version(solo, solo, old)
    assert (solo / "x.tmp").read_text(encoding="utf-8") == "alt\n"
    saved = list((solo / ".git" / "sprintforecast-verworfen").glob("*/x.tmp"))
    assert [p.read_text(encoding="utf-8") for p in saved] == ["lokal wichtig\n"]


def test_restore_version_rollback_puts_ignored_files_back(solo: Path, monkeypatch):
    old = ignored_setup(solo)
    real = githistory._git

    def flaky(cwd, *args, **kwargs):
        if args[:1] == ("commit",):
            raise GitError("Commit kaputt")
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(githistory, "_git", flaky)
    with pytest.raises(GitError, match="Commit kaputt"):
        githistory.restore_version(solo, solo, old)
    monkeypatch.setattr(githistory, "_git", real)
    assert (solo / "x.tmp").read_text(encoding="utf-8") == "lokal wichtig\n"
    assert git(solo, "status", "--porcelain") == ""
