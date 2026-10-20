# SPDX-License-Identifier: EUPL-1.2
"""Shared helpers for tests with real Git repositories: a server (bare) and clones."""

import contextlib
import http.server
import os
import shutil
import stat
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from sprintforecast import gitsync
from sprintforecast.git import invalidate_status

# A password or token that must not appear in any display, message or configuration.
SECRET = "GEHEIM123"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def rmtree_force(path: Path) -> None:
    """Deletes a folder including read-only files (Git objects are read-only on Windows)."""

    def make_writable(function, name, _error) -> None:
        os.chmod(name, stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onexc=make_writable)


def make_local(tmp_path: Path, name: str = "work", commit: bool = True) -> Path:
    """Data folder ``<name>/teams`` in a repository (without server), optionally with a commit."""
    root = tmp_path / name
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.org")
    (root / "teams").mkdir()
    if commit:
        (root / "teams" / "team.yaml").write_text("name: A\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "Start")
    return root


def make_server(tmp_path: Path, name: str = "server.git", branch: str | None = None) -> Path:
    """Bare repository as server; with ``branch`` it holds a commit on that branch."""
    bare = tmp_path / name
    git(tmp_path, "init", "-q", "--bare", "-b", branch or "main", str(bare))
    if branch:
        other = make_local(tmp_path, f"{name}-quelle")
        git(other, "branch", "-m", branch)
        git(other, "push", "-q", str(bare), branch)
    return bare


def add_branches(server: Path, names: list[str]) -> None:
    """Creates many branches on the server; they point to the server's commit. The server needs a
    commit, e.g. ``branch="main"``. The branches go straight into ``packed-refs`` (hundreds of
    calls would be slow, and long names exceed the file path limit on Windows)."""
    commit = git(server, "rev-parse", "HEAD")
    git(server, "pack-refs", "--all")
    packed = server / "packed-refs"
    lines = []
    if packed.exists():
        lines = [x for x in packed.read_text(encoding="utf-8").splitlines() if x[:1] != "#"]
    lines += [f"{commit} refs/heads/{name}" for name in names]
    header = "# pack-refs with: peeled fully-peeled \n"
    packed.write_text(header + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")


class Denying(http.server.BaseHTTPRequestHandler):
    """A server that answers every request with "login required" (401)."""

    def do_GET(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="x"')
        self.end_headers()

    def log_message(self, *args):
        pass


class NotFound(http.server.BaseHTTPRequestHandler):
    """A server that answers every request with "not found" (404)."""

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def serve(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[int]:
    """Starts a small server on a free port (``127.0.0.1``) and returns the port."""
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def no_login_prompt(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """No credential service of the machine (Credential Manager) in the test: it would open a window
    for a 401 server. Without Git system and user configuration."""
    empty = tmp_path_factory.mktemp("gitconfig") / "leer"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GCM_INTERACTIVE", "never")


def assume_foreign_owner(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """From here on Git considers ``repo`` the folder of another user account ("detected dubious
    ownership") without changing permissions or owner (that would not work on Windows).
    The caller creates the repository beforehand: the helpers in this file would hit the error too.
    Skipped if the Git version does not check ownership."""
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    probe = subprocess.run(["git", "rev-parse"], cwd=repo, capture_output=True, text=True)
    if "dubious ownership" not in probe.stderr:
        pytest.skip("Diese Git-Version prüft den Besitzer des Ordners nicht")
    invalidate_status()


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
