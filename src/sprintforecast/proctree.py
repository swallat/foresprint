# SPDX-License-Identifier: EUPL-1.2
"""Alle Prozesse der App beenden, wenn das App-Fenster zugeht.

Der Server (Python/Streamlit), der Browser mit seinen Hilfsprozessen und Dialoge (Tk) sind
Kindprozesse des Starters. Unter Windows hält ein Job-Objekt sie zusammen: Endet der Starter
– auch abgestürzt oder abgeschossen –, beendet Windows alle Prozesse darin. Sonst blieben sie
laufen und sperren Dateien (z. B. beim Aktualisieren oder Deinstallieren mit uv).
Unter Linux/macOS bekommt der Server eine eigene Prozessgruppe, die am Ende beendet wird.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys

_job = None  # Handle bleibt bis zum Prozessende offen (Schließen löst das Beenden aus)


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
    # KILL_ON_JOB_CLOSE (0x2000) + BREAKAWAY_OK (0x800): der Aktualisierungsprozess muss das
    # Beenden überleben und löst sich dafür bewusst aus dem Job (updater.py).
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x800
    ok = kernel32.SetInformationJobObject(
        wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)
    )
    return (kernel32, job) if ok else None


def popen_options() -> dict:
    """Zusätzliche Popen-Argumente, damit der Prozess samt Kindern beendbar bleibt."""
    return {} if sys.platform == "win32" else {"start_new_session": True}


def adopt(process: subprocess.Popen) -> None:
    """Nimmt einen gestarteten Prozess (und alle seine späteren Kinder) in die Gruppe auf."""
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
    """Beendet den Prozess und alles, was er gestartet hat."""
    if process.poll() is not None and sys.platform == "win32":
        return
    if sys.platform == "win32":
        # Beendet den Baum samt Kindern; das Job-Objekt fängt den Rest beim Programmende.
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
