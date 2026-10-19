# SPDX-License-Identifier: EUPL-1.2
"""Die Aktualisierung findet Git auch außerhalb des PATH: uv bekommt den Ordner vorn im PATH."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_gitfinden import fake_git

from sprintforecast import git as gitmod
from sprintforecast import updater

posix = pytest.mark.skipif(sys.platform == "win32", reason="Shell-Skript als Fake-Git")


@pytest.fixture
def no_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git ist nicht im PATH."""
    leer = tmp_path / "leerer-path"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))


@pytest.fixture
def outside(tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ein Git außerhalb des PATH, das find_git findet."""
    fake = fake_git(tmp_path / "benutzer" / "cmd")
    monkeypatch.setattr(gitmod, "git_locations", lambda: [fake])
    return fake


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)


@posix
def test_git_outside_path_is_prepended_for_uv(
    outside: Path, no_path: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    leer = os.environ["PATH"]
    before = dict(os.environ)
    env = updater.upgrade_environment()
    assert env is not None
    assert env["PATH"] == os.pathsep.join([str(outside.parent), leer])
    # nur die Kopie ändert sich: weder global noch die Umgebung für Git
    assert dict(os.environ) == before
    assert gitmod._env(False)["PATH"] == leer


@posix
def test_run_upgrade_passes_the_environment(outside: Path, monkeypatch: pytest.MonkeyPatch):
    run = Recorder()
    monkeypatch.setattr(updater.subprocess, "run", run)
    assert updater.run_upgrade("/pfad/uv") == 0
    command, kwargs = run.calls[0]
    assert command[0] == "/pfad/uv"
    assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(outside.parent)


@posix
def test_scheduled_upgrade_passes_the_environment(
    outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(updater, "log_file", lambda: tmp_path / "log" / "update.log")
    popen = Recorder()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("/pfad/uv")
    _, kwargs = popen.calls[0]
    assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(outside.parent)


@posix
def test_unchanged_when_git_is_in_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    im_path = fake_git(tmp_path / "im-path")
    ersatz = fake_git(tmp_path / "ersatz")
    monkeypatch.setenv("PATH", str(im_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [ersatz])
    assert updater.upgrade_environment() is None
    run = Recorder()
    monkeypatch.setattr(updater.subprocess, "run", run)
    updater.run_upgrade("/pfad/uv")
    assert run.calls[0][1]["env"] is None


@posix
def test_unchanged_when_git_is_missing(
    tmp_path: Path,
    no_path: None,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(gitmod, "git_locations", lambda: [tmp_path / "gibt-es-nicht"])
    assert updater.upgrade_environment() is None


@posix
def test_windows_keeps_the_spelling_of_the_variable(
    outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "environ", {"Path": "C:\\Windows", "Andere": "x"})
    monkeypatch.setattr(os, "pathsep", ";")
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)  # ohne PATH sucht which /bin
    env = updater.upgrade_environment()
    assert env is not None
    assert env["Path"] == f"{outside.parent};C:\\Windows"
    assert "PATH" not in env and env["Andere"] == "x"
