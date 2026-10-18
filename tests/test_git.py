# SPDX-License-Identifier: EUPL-1.2
import subprocess
from pathlib import Path

import pytest
from gitrepos import assume_foreign_owner

from sprintforecast import gitsync
from sprintforecast.git import (
    GitError,
    changes_in,
    commit,
    commit_directory,
    invalidate_status,
    pending_changes,
    repo_root,
    require_root,
    root_problem,
    title_for,
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "teams" / "a").mkdir(parents=True)
    (tmp_path / "teams" / "a" / "team.yaml").write_text("name: A\n")
    (tmp_path / "andere.txt").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_repo_root(repo: Path, tmp_path_factory: pytest.TempPathFactory):
    assert repo_root(repo / "teams" / "gibt-es-noch-nicht") == repo.resolve()
    assert repo_root(tmp_path_factory.mktemp("ohne-git")) is None


def test_commit_only_data_directory(repo: Path):
    teams = repo / "teams"
    (teams / "a" / "team.yaml").write_text("name: A2\n")
    (teams / "a" / "neu.yaml").write_text("x: 1\n")
    (repo / "andere.txt").write_text("geändert")
    assert sorted(f for _, f in pending_changes(teams)) == ["teams/a/neu.yaml", "teams/a/team.yaml"]

    commit_directory(teams, "Daten", ["a/2026.1"])
    assert pending_changes(teams) == []
    assert git(repo, "status", "--porcelain") == "M andere.txt"  # außerhalb bleibt offen
    assert git(repo, "tag") == "a/2026.1"


def test_deletions_are_committed(repo: Path):
    (repo / "teams" / "a" / "team.yaml").unlink()
    commit_directory(repo / "teams", "gelöscht")
    assert git(repo, "ls-files", "teams") == ""


def test_spreadsheet_is_refused(repo: Path):
    (repo / "teams" / "sheet.xlsx").write_bytes(b"x")
    with pytest.raises(GitError, match="Tabellenkalkulationen"):
        commit_directory(repo / "teams", "nicht erlaubt")
    assert git(repo, "log", "--oneline").count("\n") == 0  # nur der init-Commit


def test_nothing_to_commit(repo: Path):
    with pytest.raises(GitError, match="Keine Änderungen"):
        commit_directory(repo / "teams", "leer")


# --- Git hält den Ordner für fremd („detected dubious ownership“) -----------------------------


@pytest.fixture
def unsafe(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Das Repository, das Git nun als fremd ablehnt."""
    assume_foreign_owner(monkeypatch, repo)
    return repo


def test_repo_root_names_the_reason_for_an_unsafe_directory(unsafe: Path):
    folder = unsafe / "teams"
    assert repo_root(folder) is None  # wie bisher: kein Wurzelordner
    problem = root_problem(folder)
    assert problem is not None and problem.kind == "unsafe_directory"
    assert "dubious ownership" in str(problem)  # die Meldung von Git bleibt erhalten
    assert "ändert keine Git-Einstellungen" in problem.hint
    assert "safe.directory" not in problem.hint  # die App rät nicht zu einer Einstellung


def test_no_reason_for_a_folder_that_is_just_not_a_repository(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
):
    outside = tmp_path_factory.mktemp("ohne-git")
    assert root_problem(outside) is None and root_problem(repo) is None
    with pytest.raises(GitError, match="liegt in keinem Git-Repository") as info:
        require_root(outside)
    assert info.value.kind == "error"


def test_no_reason_without_git(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PATH", "")
    assert repo_root(repo) is None and root_problem(repo) is None


@pytest.mark.parametrize(
    "call",
    [
        lambda teams: require_root(teams),
        lambda teams: changes_in(teams),
        lambda teams: commit_directory(teams, "Daten"),
        lambda teams: gitsync.state(teams),
    ],
    ids=["require_root", "changes_in", "commit_directory", "state"],
)
def test_an_unsafe_directory_is_reported_instead_of_no_repository(unsafe: Path, call):
    with pytest.raises(GitError) as info:
        call(unsafe / "teams")
    assert info.value.kind == "unsafe_directory"
    assert "keinem Git-Repository" not in str(info.value)
    assert "Betreuung des Rechners" in info.value.hint


def test_the_reason_is_not_permanent(unsafe: Path, monkeypatch: pytest.MonkeyPatch):
    """Wird der Ordner in Ordnung gebracht, gilt das nach dem nächsten Speichern oder Abgleich."""
    assert root_problem(unsafe) is not None
    monkeypatch.delenv("GIT_TEST_ASSUME_DIFFERENT_OWNER")
    invalidate_status()
    assert repo_root(unsafe) == unsafe.resolve() and root_problem(unsafe) is None


def test_sync_reports_an_unsafe_directory(unsafe: Path):
    result = gitsync.sync(unsafe / "teams", "Daten")
    assert result.error is not None and result.error.kind == "unsafe_directory"


def test_commit_outside_a_repository_is_classified(tmp_path_factory: pytest.TempPathFactory):
    folder = tmp_path_factory.mktemp("ohne-git")
    file = folder / "team.yaml"
    file.write_text("name: A\n", encoding="utf-8")
    with pytest.raises(GitError) as caught:
        commit([file], "Ohne Repository")
    assert caught.value.kind == "not_repo"
    assert str(folder) in str(caught.value)
    assert "git init" in caught.value.hint
    assert title_for("not_repo") == "Kein Git-Repository"
