# SPDX-License-Identifier: EUPL-1.2
"""Sync lock: a hint instead of waiting forever, manual abort."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from foresprint import git as gitmod
from foresprint import gitsync


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
        gitsync.fetch(repo)  # does not raise
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
                    gitmod._git_result(repo.resolve(), "sleep")  # after the abort: nothing new
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
    assert gitsync.abort_running_sync(repo) is False  # nothing is running anymore
    with gitsync._locked(repo):  # the next sync may start again
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
            release.wait(10)  # the sync still holds the lock

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
    gitsync.state(repo)  # other threads keep reading, even while a sync is running
    release.set()
    thread.join(10)
    gitmod.invalidate_status()
    gitsync.state(repo)  # and after the sync has ended
    assert not gitmod._ABORTED


def test_background_fetch_skips_while_sync_runs(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gitsync, "background_fetch_due", lambda p: True)
    monkeypatch.delenv(gitsync.BACKGROUND_OFF_ENV, raising=False)
    with gitsync._locked(repo):
        assert gitsync.sync_running_seconds(repo) is not None
        assert gitsync.start_background_fetch(repo) is False
    assert gitsync.sync_running_seconds(repo) is None


@pytest.mark.skipif(sys.platform == "win32", reason="posix sleep")
def test_abort_only_touches_the_sync_holder_not_readers(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    real = gitmod.git_command
    monkeypatch.setattr(
        gitmod, "git_command", lambda *a: ["sleep", "30"] if a == ("sleep",) else real(*a)
    )
    outcome: dict[str, str] = {}
    release = threading.Event()

    def call(name: str) -> None:
        try:
            gitmod._git(repo.resolve(), "sleep", timeout=3)
            outcome[name] = "ok"
        except gitmod.GitError as e:
            outcome[name] = e.kind

    def holder() -> None:
        with gitsync._locked(repo):
            call("holder")
            release.wait(10)

    threads = [threading.Thread(target=holder)]
    threads[0].start()
    for _ in range(100):
        if gitmod._ACTIVE:
            break
        time.sleep(0.05)
    reader = threading.Thread(target=call, args=("reader",))
    reader.start()
    for _ in range(100):
        if sum(map(len, gitmod._ACTIVE.values())) == 2:
            break
        time.sleep(0.05)
    assert gitsync.abort_running_sync(repo) is True
    time.sleep(0.5)
    assert "reader" not in outcome  # keeps running (until its own timeout)
    reader.join(10)
    assert outcome["reader"] == "timeout" or outcome["reader"] != "aborted"
    assert outcome["holder"] == "aborted"
    release.set()
    threads[0].join(10)
    assert not gitmod._ABORTED and not gitmod._HOLDERS  # nothing survives the sync
    assert gitsync.abort_running_sync(repo) is False


def test_aborted_fetch_is_not_recorded_as_server_result(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    import types

    fake = types.SimpleNamespace(remote="origin", url="")

    def aborted(*a, **k):
        raise gitmod.GitError("x", "aborted")

    monkeypatch.setattr(gitsync, "state", lambda p: fake)
    monkeypatch.setattr(gitsync, "_git", aborted)
    gitsync._FETCHED.pop(gitsync._root(repo), None)
    with pytest.raises(gitmod.GitError):
        gitsync._fetch_locked(repo)
    assert gitsync._root(repo) not in gitsync._FETCHED
