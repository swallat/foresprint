# SPDX-License-Identifier: EUPL-1.2
"""Phase P: caches never deliver stale data; heavy imports stay out of startup."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from foresprint import storage
from foresprint.git import (
    cached_pending_changes,
    commit_directory,
    invalidate_status,
    pending_changes,
)
from foresprint.storage import Repository, clear_team_cache

TEAM = "demo"


@pytest.fixture(autouse=True)
def _clean_caches():
    clear_team_cache()
    yield
    clear_team_cache()


def age(root: Path) -> None:
    """Mark all files as "old", otherwise fresh files are not cached."""
    old = time.time() - 60
    for f in root.rglob("*.yaml"):
        os.utime(f, (old, old))


def test_cache_returns_equal_independent_copy(data_dir: Path):
    age(data_dir)
    repo = Repository(data_dir)
    first = repo.load_cached(TEAM)
    second = repo.load_cached(TEAM)
    assert second is not first
    assert second.sprints == repo.load(TEAM).sprints
    second.sprints.clear()  # changes to the result must not alter the cache
    assert len(repo.load_cached(TEAM).sprints) == len(first.sprints)


def test_cache_is_used_for_unchanged_files(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    age(data_dir)
    repo = Repository(data_dir)
    repo.load_cached(TEAM)
    monkeypatch.setattr(Repository, "load", lambda *a: pytest.fail("neu gelesen"))
    repo.load_cached(TEAM)


def test_cache_sees_save_through_repository(data_dir: Path):
    age(data_dir)
    repo = Repository(data_dir)
    data = repo.load_cached(TEAM)
    sprint = data.sprints[-1]
    sprint.commitment = 123.0
    repo.save_sprint(TEAM, sprint)
    assert repo.load_cached(TEAM).sprint(sprint.id).commitment == 123.0


def write_raw(path: Path, **changes) -> None:
    """Write a sprint file outside the repository (editor, git pull)."""
    raw = yaml.safe_load(path.read_text())
    raw.update(changes)
    path.write_text(yaml.safe_dump(raw))
    os.utime(path, (time.time() - 30, time.time() - 30))


def test_cache_sees_external_edit_added_and_deleted_files(data_dir: Path):
    age(data_dir)
    repo = Repository(data_dir)
    last = repo.load_cached(TEAM).sprints[-1]
    path = repo.sprint_path(TEAM, last.id)
    write_raw(path, not_done=7)
    assert repo.load_cached(TEAM).sprint(last.id).not_done == 7
    other = repo.sprint_path(TEAM, "9999.1")  # neue Datei
    other.write_text(path.read_text())
    write_raw(other, id="9999.1", start="2099-01-01", end="2099-01-15")
    assert repo.load_cached(TEAM).sprint("9999.1") is not None
    other.unlink()  # deleted file
    assert repo.load_cached(TEAM).sprint("9999.1") is None


def test_cache_does_not_trust_fresh_files(data_dir: Path):
    """Two changes within the same time unit (same size, same modification time) must not go
    unnoticed: fresh files are not cached."""
    repo = Repository(data_dir)
    path = repo.sprint_path(TEAM, repo.load_cached(TEAM).sprints[-1].id)
    sprint_id = path.stem
    now = time.time_ns()
    for value in (11, 12):
        raw = yaml.safe_load(path.read_text())
        raw["forecast_ist"] = value
        path.write_text(yaml.safe_dump(raw))
        os.utime(path, ns=(now, now))
        assert repo.load_cached(TEAM).sprint(sprint_id).commitment == value


def test_cache_follows_data_folder_change(data_dir: Path, tmp_path: Path):
    age(data_dir)
    other = tmp_path / "other"
    other.mkdir()
    shutil.copytree(data_dir / TEAM, other / TEAM)
    sprint = Repository(other).load(TEAM).sprints[-1]
    sprint.commitment = 77.0
    Repository(other).save_sprint(TEAM, sprint)
    age(other)
    first = Repository(data_dir).load_cached(TEAM).sprint(sprint.id)
    second = Repository(other).load_cached(TEAM).sprint(sprint.id)
    assert first.commitment != 77.0
    assert second.commitment == 77.0


def test_loader_uses_c_loader_when_available():
    assert storage._YAML_LOADER is getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def test_loader_falls_back_without_c_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert storage._pick_loader() is yaml.SafeLoader
    monkeypatch.setattr(storage, "_YAML_LOADER", yaml.SafeLoader)
    (tmp_path / "a.yaml").write_text("x: 1\nd: 2026-10-15\n", encoding="utf-8")
    assert storage._read(tmp_path / "a.yaml")["x"] == 1


def test_both_loaders_read_demo_data_identically(data_dir: Path):
    for f in data_dir.rglob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert yaml.load(text, Loader=yaml.SafeLoader) == yaml.load(
            text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        )


@pytest.fixture
def git_dir(data_dir: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=data_dir, check=True)
    for k, v in (("user.email", "t@example.org"), ("user.name", "T")):
        subprocess.run(["git", "config", k, v], cwd=data_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=data_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=data_dir, check=True)
    invalidate_status()
    return data_dir


def test_git_status_invalidated_by_save(git_dir: Path):
    repo = Repository(git_dir)
    assert cached_pending_changes(git_dir) == []
    sprint = repo.load(TEAM).sprints[-1]
    sprint.commitment = 99.0
    repo.save_sprint(TEAM, sprint)  # writing invalidates the Git state
    assert [f.rsplit("/", 1)[-1] for _, f in cached_pending_changes(git_dir)] == [
        f"{sprint.id}.yaml"
    ]


def test_git_status_not_requeried_within_ttl(git_dir: Path, monkeypatch: pytest.MonkeyPatch):
    cached_pending_changes(git_dir)
    monkeypatch.setattr("foresprint.git._git", lambda *a, **k: pytest.fail("neu abgefragt"))
    assert cached_pending_changes(git_dir) == []


def test_git_status_invalidated_by_commit(git_dir: Path):
    repo = Repository(git_dir)
    sprint = repo.load(TEAM).sprints[-1]
    sprint.commitment = 98.0
    repo.save_sprint(TEAM, sprint)
    assert cached_pending_changes(git_dir)
    commit_directory(git_dir, "test")
    assert cached_pending_changes(git_dir) == []
    assert pending_changes(git_dir) == []


def test_gui_import_loads_no_heavy_modules():
    """No pandas/altair/rich/typer/CLI when importing the UI (cold start)."""
    code = (
        "import sys, foresprint.web.ui\n"
        "bad = [m for m in ('pandas', 'altair', 'rich', 'typer', 'foresprint.cli')"
        " if m in sys.modules]\n"
        "print(','.join(bad))"
    )
    pytest.importorskip("streamlit")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
