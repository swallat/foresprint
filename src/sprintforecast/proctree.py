# SPDX-License-Identifier: EUPL-1.2
"""Terminate all processes of the app when the app window closes.

The server (Python/Streamlit), the browser with its helper processes and dialogs (Tk) are
child processes of the launcher. On Windows a job object keeps them together: when the launcher
ends, even if it crashed or was killed, Windows terminates all processes in it. Otherwise they
would keep running and lock files (e.g. when updating or uninstalling with uv).
On Linux/macOS the server gets its own process group, which is terminated at the end.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys

_job = None  # handle stays open until the process ends (closing it triggers the termination)


def _create_job():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    # KILL_ON_JOB_CLOSE (0x2000) + BREAKAWAY_OK (0x800): the update process has to survive the
    # termination and deliberately breaks away from the job for that (updater.py).
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x800
    ok = kernel32.SetInformationJobObject(
        wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)
    )
    return (kernel32, job) if ok else None


def popen_options() -> dict:
    """Extra Popen arguments so the process can still be terminated together with its children."""
    return {} if sys.platform == "win32" else {"start_new_session": True}


def adopt(process: subprocess.Popen) -> None:
    """Add a started process (and all its later children) to the group."""
    global _job
    if sys.platform != "win32":
        return
    try:
        if _job is None:
            _job = _create_job()
        if _job is not None:
            kernel32, job = _job
            kernel32.AssignProcessToJobObject(job, int(process._handle))  # type: ignore[attr-defined]
    except OSError, AttributeError:
        pass


def terminate_tree(process: subprocess.Popen, timeout: float = 10) -> None:
    """Terminate the process and everything it started."""
    if process.poll() is not None and sys.platform == "win32":
        return
    if sys.platform == "win32":
        # Terminates the tree including children; the job object catches the rest at program exit.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
