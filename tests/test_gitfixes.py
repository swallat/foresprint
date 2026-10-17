# SPDX-License-Identifier: EUPL-1.2
"""Nachbesserungen an der Git-Synchronisation (Befunde K1–K2, W1–W7, M1–M6): jeweils mit
echten Git-Repositories."""

import os
import sys
from pathlib import Path

import pytest
from gitrepos import Person, git

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
    with pytest.raises(GitError, match="Ungültige Adresse"):
        gitmod.clone_repository("--upload-pack=touch boese", tmp_path / "ziel")
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


def test_first_share_against_server_with_unrelated_history(
    alice: Person, remote: Path, tmp_path: Path
):
    carol = make_stranger(tmp_path, remote, {"a/2026.2.yaml": "velocity: 5\n"})
    result = carol.sync("Carol startet")
    assert result.ok, result.error
    assert result.pushed and result.merged
    assert (carol.data / "a" / "team.yaml").exists() and (carol.data / "a" / "2026.2.yaml").exists()
    assert git(carol.root, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_first_share_with_unrelated_history_and_conflict(
    alice: Person, remote: Path, tmp_path: Path
):
    carol = make_stranger(tmp_path, remote, {"a/team.yaml": "name: Anders\n"})
    result = carol.sync("Carol startet")
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
    (solo / "b.yaml").write_text("v: 2\n", encoding="utf-8")
    rev = commit_all(solo, "Zwei")
    git(solo, "config", "--unset", "user.name")
    git(solo, "config", "--unset", "user.email")
    git(solo, "config", "user.useConfigOnly", "true")
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("EMAIL", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(solo / "leer"))
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
