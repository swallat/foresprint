# SPDX-License-Identifier: EUPL-1.2
"""Gemeinsame Hilfen für Tests mit echten Git-Repositories: ein Server (bare) und Klone."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from sprintforecast import gitsync
from sprintforecast.git import invalidate_status


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@dataclass
class Person:
    name: str
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "teams"

    def write(self, rel: str, text: str) -> Path:
        file = self.data / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        invalidate_status()
        return file

    def sync(self, message: str = "Änderung", tags: list[str] | None = None, **kwargs):
        return gitsync.sync(self.data, message, tags, **kwargs)


def make_clone(remote: Path, target: Path, name: str) -> Person:
    git(target.parent, "clone", "-q", str(remote), str(target))
    git(target, "config", "user.name", name)
    git(target, "config", "user.email", f"{name.lower()}@example.org")
    return Person(name, target)


@pytest.fixture(autouse=True)
def clean_caches():
    invalidate_status()
    gitsync._FETCHED.clear()
    yield
    invalidate_status()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    return bare


@pytest.fixture
def alice(tmp_path: Path, remote: Path) -> Person:
    git(tmp_path, "init", "-q", "-b", "main", str(tmp_path / "alice"))
    person = Person("Alice", tmp_path / "alice")
    git(person.root, "config", "user.name", "Alice")
    git(person.root, "config", "user.email", "alice@example.org")
    git(person.root, "remote", "add", "origin", str(remote))
    person.write("a/team.yaml", "name: A\n")
    person.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 1\n")
    assert person.sync("Start").ok
    return person


@pytest.fixture
def bob(tmp_path: Path, remote: Path, alice: Person) -> Person:
    return make_clone(remote, tmp_path / "bob", "Bob")
