# SPDX-License-Identifier: EUPL-1.2
"""„Speichern und teilen“, wenn Streamlit den Rückruf mittendrin stoppt: Kommt während des
Abgleichs eine weitere Anforderung des Browsers, startet Streamlit einen neuen Durchlauf und stoppt
den alten bei der nächsten Berührung von ``st.session_state`` (``StopException``). Der Abgleich ist
dann gelaufen; seine Meldung darf trotzdem nicht verloren gehen (AppTest, echte Repositories)."""

import threading

import pytest

pytest.importorskip("streamlit")

from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from test_web_k3_anbindung import sidebar_text
from test_web_k3_ui import git, sidebar_button, start

from sprintforecast import gitsync
from sprintforecast.web import ui


def test_result_survives_a_callback_that_is_stopped_after_the_sync(shared, data_dir, monkeypatch):
    root, _, server = shared
    sprint = root / "teams/demo/sprints/2026.21.yaml"
    sprint.write_text(sprint.read_text() + "\n# geändert\n")
    at = start(data_dir, monkeypatch)
    real = ui._remember_sync_result
    stopped = []

    def stop_once(result):
        if not stopped:
            stopped.append(result)
            raise StopException  # Streamlit stoppt den alten Durchlauf bei der Sitzungs-Berührung
        real(result)

    monkeypatch.setattr(ui, "_remember_sync_result", stop_once)
    sidebar_button(at, "Speichern und teilen").click().run()
    assert stopped, "der Abgleich lief nicht"
    assert git(server, "rev-parse", "main") == git(root, "rev-parse", "HEAD")  # hochgeladen
    # Der nächste Durchlauf (der neue, den Streamlit gestartet hat) holt das Ergebnis nach.
    at.run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Eigene Änderungen gesichert" in text and "Hochgeladen" in text
    assert not ui._SYNC_DONE
    at.run()  # und zeigt es nur einmal
    assert "Hochgeladen" not in sidebar_text(at)


def test_a_second_click_during_a_running_sync_starts_no_second_sync(shared, data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(ui, "sync", lambda *a, **k: calls.append(a) or gitsync.SyncResult())
    at = start(data_dir, monkeypatch)
    assert ui._SYNC_LOCK.acquire(blocking=False)  # ein Abgleich läuft gerade (anderer Thread)
    threading.Timer(1.0, ui._SYNC_LOCK.release).start()  # der neue Durchlauf wartet darauf
    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    assert not calls
    sidebar_button(at, "Speichern und teilen").click().run()
    assert len(calls) == 1
    assert "Alles ist auf dem aktuellen Stand." in sidebar_text(at)
