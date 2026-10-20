# SPDX-License-Identifier: EUPL-1.2
"""Shared fixtures of the web tests with real Git repositories (included in conftest.py)."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sprintforecast.git import invalidate_status
from sprintforecast.storage import save_data_dir

# State "done" in the step bar: green check icon at the end of the label (open steps
# carry no mark). Deliberately spelled out here, not taken from ui.py: the tests record what
# users see.
STEP_DONE_MARK = ":green[:material/check_circle:]"


def nav_links(at: Any) -> list[tuple[Any, bool]]:
    """The links of the step bar (``AppTest``) with ``active`` in the order of the bar. Each step
    is a link in a container with key ``board-step-...`` or ``board-active-...``, all built the
    same way, the active one only colored differently (CSS)."""
    steps = []
    for node in at.main:
        key = getattr(node, "key", None)
        if isinstance(key, str) and key.startswith(("board-step-", "board-active-")):
            [link] = [child for child in node if child.type == "page_link"]
            steps.append((link, key.startswith("board-active-")))
    return steps


def nav_steps(at: Any) -> list[tuple[str, str, bool]]:
    """Step bar of the task pages: per step (page, label, active) in the order of the bar; for
    completed steps the label contains the icon."""
    return [(link.proto.page, link.proto.label, active) for link, active in nav_links(at)]


def nav_titles(at: Any) -> list[str]:
    """Names of the steps without the done icon, in the order of the bar."""
    return [label.removesuffix(f" {STEP_DONE_MARK}") for _, label, _ in nav_steps(at)]


def nav_done(at: Any) -> dict[str, bool]:
    """Page -> step done (icon at the end of the label)."""
    return {page: label.endswith(STEP_DONE_MARK) for page, label, _ in nav_steps(at)}


def nav_help(at: Any) -> dict[str, str]:
    """Page -> tooltip of the step (says "recorded" or "still open" for the sprint)."""
    return {link.proto.page: link.proto.help for link, _ in nav_links(at)}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Git repository around ``data_dir`` (layout ``<repo>/teams``) with a commit."""
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
    """Alice (app on data_dir) and Bob (second clone) share a server."""
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
