# SPDX-License-Identifier: EUPL-1.2
"""Gemeinsame Hilfen für Tests mit echten Git-Repositories: ein Server (bare) und Klone."""

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

# Ein Kennwort bzw. Token, das in keiner Anzeige, Meldung oder Konfiguration auftauchen darf.
SECRET = "GEHEIM123"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def rmtree_force(path: Path) -> None:
    """Löscht einen Ordner samt schreibgeschützter Dateien (Git-Objekte sind es unter Windows)."""

    def make_writable(function, name, _error) -> None:
        os.chmod(name, stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onexc=make_writable)


def make_local(tmp_path: Path, name: str = "work", commit: bool = True) -> Path:
    """Datenordner ``<name>/teams`` in einem Repository (ohne Server), optional mit einem Commit."""
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
    """Bare-Repository als Server; mit ``branch`` liegt dort ein Commit auf diesem Branch."""
    bare = tmp_path / name
    git(tmp_path, "init", "-q", "--bare", "-b", branch or "main", str(bare))
    if branch:
        other = make_local(tmp_path, f"{name}-quelle")
        git(other, "branch", "-m", branch)
        git(other, "push", "-q", str(bare), branch)
    return bare


def add_branches(server: Path, names: list[str]) -> None:
    """Legt viele Branches auf dem Server an; sie zeigen auf den Commit des Servers. Der Server
    braucht einen Commit, z. B. ``branch="main"``. Die Branches landen direkt in ``packed-refs``
    (hunderte Aufrufe wären langsam, und lange Namen sprengen unter Windows den Dateipfad)."""
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
    """Ein Server, der jede Anfrage mit „Anmeldung nötig“ (401) beantwortet."""

    def do_GET(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="x"')
        self.end_headers()

    def log_message(self, *args):
        pass


class NotFound(http.server.BaseHTTPRequestHandler):
    """Ein Server, der jede Anfrage mit „nicht gefunden“ (404) beantwortet."""

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def serve(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[int]:
    """Startet einen kleinen Server auf einem freien Port (``127.0.0.1``) und liefert den Port."""
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def no_login_prompt(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Kein Anmeldedienst des Rechners (Credential Manager) im Test: Er würde bei einem
    401-Server ein Fenster öffnen. Ohne System- und Benutzerkonfiguration von Git."""
    empty = tmp_path_factory.mktemp("gitconfig") / "leer"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GCM_INTERACTIVE", "never")


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
