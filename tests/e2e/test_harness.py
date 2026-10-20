# SPDX-License-Identifier: EUPL-1.2
"""The test harness itself: clean up even if the start fails."""

import os
import signal
import subprocess
import sys

import harness
import pytest
from harness import App, copy_demo


def test_failed_start_stops_the_half_started_server(tmp_path, monkeypatch):
    """If the server does not answer in time, no process is left behind (it would keep running in
    its own session beyond the end of the test and hold port and memory)."""
    started: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        if args[0][0] == sys.executable:  # the app start, not pgrep
            started.append(process)
        return process

    monkeypatch.setattr(harness, "START_TIMEOUT", 0.05)
    monkeypatch.setattr(harness.subprocess, "Popen", recording_popen)
    work = tmp_path / "demo"
    server = App("startfehler", copy_demo(work), work)
    with pytest.raises(RuntimeError, match="startete nicht"):
        server.start()
    assert len(started) == 1
    assert started[0].poll() is not None  # terminated, no longer running


@pytest.mark.skipif(sys.platform == "win32", reason="/proc und pgrep gibt es nur unter Unix")
def test_children_are_found_without_pgrep(monkeypatch):
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time;"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)",
        ]
    )
    try:
        # pgrep is missing: the search falls back to /proc and still finds the child
        def without_pgrep(*args, **kwargs):
            raise FileNotFoundError("pgrep")

        monkeypatch.setattr(harness.subprocess, "run", without_pgrep)
        found: list[int] = []
        for _ in range(100):  # the child appears shortly after the parent process starts
            found = harness._child_processes(parent.pid)
            if found:
                break
            harness.time.sleep(0.1)
        assert len(found) == 1
    finally:
        for pid in harness._children_from_proc(parent.pid):
            os.kill(pid, signal.SIGKILL)
        parent.kill()
        parent.wait()
