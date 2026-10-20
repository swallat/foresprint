# SPDX-License-Identifier: EUPL-1.2
"""Self-termination of the server in app mode once nobody is connected anymore.

The launcher only detects the end of the app window via the browser process. If the browser
hands over to a running instance and exits immediately (e.g. second double-click), the server
would keep running forever after the window closes and lock files (``uv tool upgrade``, os error
32). So the server checks itself: once a browser has been connected and none has been there for
longer than the grace period, it terminates, regardless of what the browser process does.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

IDLE_ENV = (
    "SPRINTFORECAST_IDLE_EXIT"  # grace period in seconds; without a value the server stays up
)
_POLL_SECONDS = 2.0

_started = False


class IdleWatch:
    """Decide from the number of connected sessions whether the server should exit."""

    def __init__(self, grace: float, poll: float = _POLL_SECONDS, seen: bool = False) -> None:
        self.grace = grace
        self.poll = poll
        self._seen = seen
        self._idle_since: float | None = None
        self._last: float | None = None

    def update(self, sessions: int, now: float) -> bool:
        # Large gap between two checks = the machine was asleep; the browser needs time to
        # reconnect, so the wait starts over.
        if self._last is not None and now - self._last > 5 * self.poll:
            self._idle_since = None
        self._last = now
        if sessions > 0:
            self._seen = True
            self._idle_since = None
            return False
        if not self._seen:
            return False
        if self._idle_since is None:
            self._idle_since = now
        return now - self._idle_since >= self.grace


def _active_sessions() -> int | None:
    try:
        from streamlit.runtime import Runtime

        return Runtime.instance()._session_mgr.num_active_sessions()
    except Exception:
        return None


def _loop(watch: IdleWatch, count: Callable[[], int | None], stop: Callable[[], None]) -> None:
    while True:
        time.sleep(watch.poll)
        sessions = count()
        if sessions is not None and watch.update(sessions, time.monotonic()):
            stop()
            return


def start_idle_watch() -> None:
    """Start the monitoring once per server process if the launcher requested it."""
    global _started
    if _started:
        return
    try:
        grace = float(os.environ.get(IDLE_ENV, ""))
    except ValueError:
        return
    _started = True
    # Called from a session's script run, so a browser was already there, even if it is
    # gone again before the first count.
    watch = IdleWatch(grace, seen=True)
    threading.Thread(
        target=_loop, args=(watch, _active_sessions, lambda: os._exit(0)), daemon=True
    ).start()
