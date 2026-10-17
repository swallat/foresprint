# SPDX-License-Identifier: EUPL-1.2
"""Selbstbeendigung des Servers im App-Modus, sobald niemand mehr verbunden ist.

Der Starter erkennt das Ende des App-Fensters nur über den Browserprozess. Übergibt der Browser
an eine laufende Instanz und endet sofort (z. B. zweiter Doppelklick), bliebe der Server nach
dem Schließen des Fensters ewig stehen und sperrte Dateien (``uv tool upgrade``, os error 32).
Darum prüft der Server selbst: War einmal ein Browser verbunden und ist danach länger als die
Karenzzeit keiner mehr da, beendet er sich – unabhängig vom Verhalten des Browserprozesses.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

IDLE_ENV = "SPRINTFORECAST_IDLE_EXIT"  # Karenzzeit in Sekunden; ohne Wert bleibt der Server an
_POLL_SECONDS = 2.0

_started = False


class IdleWatch:
    """Entscheidet anhand der Zahl verbundener Sitzungen, ob der Server enden soll."""

    def __init__(self, grace: float, poll: float = _POLL_SECONDS, seen: bool = False) -> None:
        self.grace = grace
        self.poll = poll
        self._seen = seen
        self._idle_since: float | None = None
        self._last: float | None = None

    def update(self, sessions: int, now: float) -> bool:
        # Große Lücke zwischen zwei Prüfungen = Rechner schlief; der Browser braucht Zeit zum
        # Wiederverbinden, die Wartezeit beginnt dann neu.
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
    """Startet die Überwachung einmal je Serverprozess, wenn der Starter sie angefordert hat."""
    global _started
    if _started:
        return
    try:
        grace = float(os.environ.get(IDLE_ENV, ""))
    except ValueError:
        return
    _started = True
    # Aufgerufen wird aus dem Skriptlauf einer Sitzung: Es war also schon ein Browser da, auch
    # wenn er vor der ersten Zählung wieder weg ist.
    watch = IdleWatch(grace, seen=True)
    threading.Thread(
        target=_loop, args=(watch, _active_sessions, lambda: os._exit(0)), daemon=True
    ).start()
