# SPDX-License-Identifier: EUPL-1.2
"""Gemeinsame Fixtures der Web-Tests mit echten Git-Repositories (in conftest.py eingebunden)."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sprintforecast.git import invalidate_status
from sprintforecast.storage import save_data_dir

# Zustand „erledigt“ in der Schrittleiste: grünes Haken-Symbol am Ende der Beschriftung (offene
# Schritte tragen kein Zeichen). Bewusst hier ausgeschrieben, nicht aus ui.py übernommen: Die
# Tests halten fest, was die Nutzer sehen.
STEP_DONE_MARK = ":green[:material/check_circle:]"


def nav_links(at: Any) -> list[tuple[Any, bool]]:
    """Die Links der Schrittleiste (``AppTest``) mit ``aktiv`` in der Reihenfolge der Leiste.
    Jeder Schritt ist ein Link in einem Container mit Schlüssel ``board-step-…`` bzw.
    ``board-active-…`` – alle gleich aufgebaut, der aktive nur anders gefärbt (CSS)."""
    steps = []
    for node in at.main:
        key = getattr(node, "key", None)
        if isinstance(key, str) and key.startswith(("board-step-", "board-active-")):
            [link] = [child for child in node if child.type == "page_link"]
            steps.append((link, key.startswith("board-active-")))
    return steps


def nav_steps(at: Any) -> list[tuple[str, str, bool]]:
    """Schrittleiste der Aufgabenseiten: je Schritt (Seite, Beschriftung, aktiv) in der
    Reihenfolge der Leiste; die Beschriftung enthält bei erledigten Schritten das Symbol."""
    return [(link.proto.page, link.proto.label, active) for link, active in nav_links(at)]


def nav_titles(at: Any) -> list[str]:
    """Namen der Schritte ohne das Erledigt-Symbol, in der Reihenfolge der Leiste."""
    return [label.removesuffix(f" {STEP_DONE_MARK}") for _, label, _ in nav_steps(at)]


def nav_done(at: Any) -> dict[str, bool]:
    """Seite → Schritt erledigt (Symbol am Ende der Beschriftung)."""
    return {page: label.endswith(STEP_DONE_MARK) for page, label, _ in nav_steps(at)}


def nav_help(at: Any) -> dict[str, str]:
    """Seite → Tooltip des Schritts (sagt „erfasst“ bzw. „noch offen“ für den Sprint)."""
    return {link.proto.page: link.proto.help for link, _ in nav_links(at)}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Git-Repository um ``data_dir`` (Aufbau ``<repo>/teams``) mit einem Commit."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    root = data_dir.parent
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    invalidate_status()
    return root


@pytest.fixture
def second_folder(data_dir: Path, tmp_path: Path) -> Path:
    second = tmp_path / "zweiter-ordner"
    shutil.copytree(data_dir / "demo", second / "zweit")
    save_data_dir(second)
    save_data_dir(data_dir)
    return second


@pytest.fixture
def shared(data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch):
    """Alice (App auf data_dir) und Bob (zweiter Klon) teilen sich einen Server."""
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@t")
    work = tmp_path_factory.mktemp("zwei-personen")
    server = work / "server.git"
    _git(work, "init", "-q", "--bare", "-b", "main", str(server))
    root = data_dir.parent
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", str(server))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Start")
    _git(root, "push", "-q", "-u", "origin", "main")
    bob = work / "bob"
    _git(work, "clone", "-q", str(server), str(bob))
    invalidate_status()
    return root, bob, server
