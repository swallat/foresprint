# SPDX-License-Identifier: EUPL-1.2
"""The update finds Git outside the PATH too: uv gets the folder at the end of the PATH."""

import base64
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_gitfinden import fake_git

from sprintforecast import git as gitmod
from sprintforecast import updater

posix = pytest.mark.skipif(sys.platform == "win32", reason="Shell-Skript als Fake-Git")


@pytest.fixture
def no_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git is not in the PATH."""
    leer = tmp_path / "leerer-path"
    leer.mkdir()
    monkeypatch.setenv("PATH", str(leer))


@pytest.fixture
def outside(tmp_path: Path, no_path: None, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Git outside the PATH that find_git finds."""
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
def test_git_outside_path_is_appended_for_uv(outside: Path):
    leer = os.environ["PATH"]
    before = dict(os.environ)
    env = updater.upgrade_environment()
    assert env is not None
    # at the end: a program of the same name (python, uv ...) in the Git folder shadows nothing
    assert env["PATH"] == os.pathsep.join([leer, str(outside.parent)])
    # only the copy changes: neither the global one nor the environment for Git
    assert dict(os.environ) == before
    assert gitmod._env(False)["PATH"] == leer


@posix
def test_unset_path_keeps_the_system_default(outside: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PATH")
    monkeypatch.setattr(
        updater.shutil, "which", lambda name: None
    )  # without PATH, which searches /bin
    env = updater.upgrade_environment()
    assert env is not None
    assert env["PATH"] == os.pathsep.join([os.defpath, str(outside.parent)])


@posix
def test_run_upgrade_passes_the_environment(outside: Path, monkeypatch: pytest.MonkeyPatch):
    run = Recorder()
    monkeypatch.setattr(updater.subprocess, "run", run)
    assert updater.run_upgrade("/pfad/uv") == 0
    command, kwargs = run.calls[0]
    assert command[0] == "/pfad/uv"
    assert kwargs["env"]["PATH"].split(os.pathsep)[-1] == str(outside.parent)


@posix
def test_scheduled_upgrade_changes_the_path_only_for_uv(
    outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The restart (``then``) runs with the original PATH, uv with the extended one."""
    monkeypatch.setattr(updater, "log_file", lambda: tmp_path / "log" / "update.log")
    leer = os.environ["PATH"]
    uv_out, then_out = tmp_path / "uv.txt", tmp_path / "then.txt"
    uv = tmp_path / "uv"
    uv.write_text(f'#!/bin/sh\necho "$PATH" > {uv_out}\n', encoding="utf-8")
    uv.chmod(0o755)
    done = subprocess.Popen(["/bin/true"])
    done.wait()
    updater.schedule_after_exit(
        str(uv),
        pids=[done.pid],
        then=["/bin/sh", "-c", f'echo "$PATH" > {then_out}'],
        cwd=str(tmp_path),
    )
    deadline = time.monotonic() + 20
    while not then_out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    assert uv_out.read_text(encoding="utf-8").strip() == f"{leer}{os.pathsep}{outside.parent}"
    assert then_out.read_text(encoding="utf-8").strip() == leer


@posix
def test_scheduled_upgrade_does_not_touch_the_environment_of_the_script(
    outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(updater, "log_file", lambda: tmp_path / "log" / "update.log")
    popen = Recorder()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("/pfad/uv")
    command, kwargs = popen.calls[0]
    assert "env" not in kwargs
    assert f"PATH={os.environ['PATH']}:{outside.parent} /pfad/uv" in command[2]


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
    monkeypatch.setattr(updater, "log_file", lambda: tmp_path / "log" / "update.log")
    popen = Recorder()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("/pfad/uv")
    assert "PATH=" not in popen.calls[0][0][2]


@posix
def test_unusable_git_in_path_gives_way_to_the_fallback_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Only a blocked ``git`` (Store alias) is in the PATH, the usable one in a replacement
    location: uv gets the replacement folder at the end of the PATH, otherwise it would start the
    broken one."""
    im_path = fake_git(tmp_path / "im-path")
    ersatz = fake_git(tmp_path / "ersatz")
    monkeypatch.setenv("PATH", str(im_path.parent))
    monkeypatch.setattr(gitmod, "git_locations", lambda: [ersatz])
    gitmod._mark_broken(str(im_path))
    assert gitmod.find_git() == str(ersatz)
    assert updater.upgrade_path() == os.pathsep.join([str(im_path.parent), str(ersatz.parent)])
    env = updater.upgrade_environment()
    assert env is not None and env["PATH"].split(os.pathsep)[-1] == str(ersatz.parent)


@posix
def test_unchanged_when_the_usable_git_is_a_later_path_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The usable Git is already in the PATH (behind the blocked one): appending changes nothing."""
    erstes = fake_git(tmp_path / "eins")
    zweites = fake_git(tmp_path / "zwei")
    monkeypatch.setenv("PATH", os.pathsep.join([str(erstes.parent), str(zweites.parent)]))
    gitmod._mark_broken(str(erstes))
    assert gitmod.find_git() == str(zweites)
    assert updater.upgrade_path() is None


@posix
def test_unchanged_when_git_is_missing(
    tmp_path: Path,
    no_path: None,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(gitmod, "git_locations", lambda: [tmp_path / "gibt-es-nicht"])
    assert updater.upgrade_environment() is None
    assert updater.upgrade_path() is None


@pytest.fixture
def windows(outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Runs on Windows (simulated): variable "Path", separator ";", flags and protocol."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "environ", {"Path": "C:\\Windows", "Andere": "x"})
    monkeypatch.setattr(os, "pathsep", ";")
    monkeypatch.setattr(
        updater.shutil, "which", lambda name: None
    )  # without PATH, which searches /bin
    for name, value in {
        "CREATE_NEW_PROCESS_GROUP": 0x200,
        "CREATE_NEW_CONSOLE": 0x10,
        "CREATE_NO_WINDOW": 0x8000000,
        "CREATE_BREAKAWAY_FROM_JOB": 0x1000000,
    }.items():
        monkeypatch.setattr(subprocess, name, value, raising=False)
    monkeypatch.setattr(updater, "log_file", lambda: tmp_path / "log" / "update.log")
    return outside


def decoded(command: list[str]) -> list[str]:
    script = base64.b64decode(command[command.index("-EncodedCommand") + 1]).decode("utf-16-le")
    return script.splitlines()


def test_windows_keeps_the_spelling_of_the_variable(windows: Path):
    env = updater.upgrade_environment()
    assert env is not None
    assert env["Path"] == f"C:\\Windows;{windows.parent}"
    assert "PATH" not in env and env["Andere"] == "x"


@pytest.mark.parametrize("visible", [False, True], ids=["unsichtbar", "sichtbar"])
def test_windows_script_sets_the_path_only_around_uv(
    windows: Path, monkeypatch: pytest.MonkeyPatch, visible: bool
):
    popen = Recorder()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("C:\\uv.exe", visible=visible, then=["C:\\sf.exe", "web"])
    assert len(popen.calls) == 1
    command, kwargs = popen.calls[0]
    assert "env" not in kwargs  # the PowerShell process itself inherits the PATH unchanged
    assert kwargs["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    lines = decoded(command)
    new = f"$env:PATH = 'C:\\Windows;{windows.parent}'"
    call = next(i for i, line in enumerate(lines) if "'C:\\uv.exe'" in line)
    assert lines.index("$sfPath = $env:PATH") < lines.index(new) < call
    assert call < lines.index("$env:PATH = $sfPath")
    assert lines.index("$env:PATH = $sfPath") < next(
        i for i, line in enumerate(lines) if line.startswith("Start-Process")
    )


def test_windows_fallback_without_breakaway_gets_the_same_script(
    windows: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        if kwargs["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB:
            raise OSError("Zugriff verweigert")

    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("C:\\uv.exe")
    assert len(calls) == 2
    (first, first_kwargs), (second, second_kwargs) = calls
    assert not second_kwargs["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert "env" not in first_kwargs and "env" not in second_kwargs
    assert decoded(first) == decoded(second)
    assert f"$env:PATH = 'C:\\Windows;{windows.parent}'" in decoded(second)


def test_windows_script_unchanged_when_git_is_in_path(
    windows: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "C:\\Git\\git.exe")
    popen = Recorder()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    updater.schedule_after_exit("C:\\uv.exe")
    assert not any("$env:PATH" in line for line in decoded(popen.calls[0][0]))
