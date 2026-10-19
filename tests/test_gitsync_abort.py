# SPDX-License-Identifier: EUPL-1.2
"""Sperre des Abgleichs: Hinweis statt ewigen Wartens, Abbruch von Hand."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from sprintforecast import git as gitmod
from sprintforecast import gitsync


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_waiting_call_gets_busy_error_while_lock_is_held(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gitsync, "LOCK_WARN_SECONDS", 0.2)
    monkeypatch.setattr(gitsync, "_LOCK_POLL_SECONDS", 0.05)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with gitsync._locked(repo):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert held.wait(5)
    try:
        result = gitsync.sync(repo, "msg", None, None)
        assert result.error is not None and result.error.kind == "sync_busy"
        assert "Sekunden" in str(result.error)
        gitsync.fetch(repo)  # wirft nicht
    finally:
        release.set()
        thread.join()
    with gitsync._locked(repo):  # danach wieder frei
        pass


def test_lock_is_reentrant(repo: Path):
    with gitsync._locked(repo), gitsync._locked(repo, wait=0):
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="posix sleep")
def test_abort_running_sync_terminates_the_child(repo: Path, monkeypatch: pytest.MonkeyPatch):
    real = gitmod.git_command
    monkeypatch.setattr(
        gitmod, "git_command", lambda *a: ["sleep", "30"] if a == ("sleep",) else real(*a)
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            with gitsync._locked(repo):
                with pytest.raises(gitmod.GitError) as killed:
                    gitmod._git_result(repo.resolve(), "sleep")
                assert killed.value.kind == "aborted"
                with pytest.raises(gitmod.GitError) as raised:
                    gitmod._git_result(repo.resolve(), "sleep")  # nach dem Abbruch: nichts Neues
                assert raised.value.kind == "aborted"
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=run)
    start = time.monotonic()
    thread.start()
    for _ in range(100):
        if gitmod._ACTIVE:
            break
        time.sleep(0.05)
    assert gitsync.abort_running_sync(repo) is True
    thread.join(10)
    assert not thread.is_alive() and not errors
    assert time.monotonic() - start < 20
    assert gitsync.abort_running_sync(repo) is False  # nichts läuft mehr
    with gitsync._locked(repo):  # der nächste Abgleich darf wieder starten
        gitmod._raise_if_aborted(repo)


@pytest.mark.skipif(sys.platform == "win32", reason="posix sleep")
def test_killed_call_reports_aborted_and_reads_work_afterwards(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    real = gitmod.git_command
    monkeypatch.setattr(
        gitmod, "git_command", lambda *a: ["sleep", "30"] if a == ("sleep",) else real(*a)
    )
    kinds: list[str] = []
    release = threading.Event()

    def run() -> None:
        with gitsync._locked(repo):
            try:
                gitmod._git(repo.resolve(), "sleep")
            except gitmod.GitError as e:
                kinds.append(e.kind)
            release.wait(10)  # der Abgleich hält die Sperre noch

    thread = threading.Thread(target=run)
    thread.start()
    for _ in range(100):
        if gitmod._ACTIVE:
            break
        time.sleep(0.05)
    assert gitsync.abort_running_sync(repo)
    for _ in range(100):
        if kinds:
            break
        time.sleep(0.05)
    assert kinds == ["aborted"]
    gitsync.state(repo)  # andere Fäden lesen weiter, auch bei laufendem Abgleich
    release.set()
    thread.join(10)
    gitmod.invalidate_status()
    gitsync.state(repo)  # und nach dem Ende des Abgleichs
    assert not gitmod._ABORTED


def test_background_fetch_skips_while_sync_runs(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gitsync, "background_fetch_due", lambda p: True)
    monkeypatch.delenv(gitsync.BACKGROUND_OFF_ENV, raising=False)
    with gitsync._locked(repo):
        assert gitsync.sync_running_seconds(repo) is not None
        assert gitsync.start_background_fetch(repo) is False
    assert gitsync.sync_running_seconds(repo) is None
