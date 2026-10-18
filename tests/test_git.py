# SPDX-License-Identifier: EUPL-1.2
import subprocess
from pathlib import Path

import pytest

from sprintforecast.git import (
    GitError,
    commit,
    commit_directory,
    pending_changes,
    repo_root,
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
