# SPDX-License-Identifier: EUPL-1.2
"""„Speichern und teilen“, wenn Streamlit den Rückruf mittendrin stoppt: Kommt während des
Abgleichs eine weitere Anforderung des Browsers, startet Streamlit einen neuen Durchlauf und stoppt
den alten bei der nächsten Berührung von ``st.session_state`` (``StopException``). Der Abgleich ist
dann gelaufen; seine Meldung darf trotzdem nicht verloren gehen (AppTest, echte Repositories).

Sperre und Ergebnisse gehören zur Browser-Sitzung (Sitzungs-ID) und zum Datenordner. Unter AppTest
haben alle Instanzen dieselbe Sitzungs-ID; zwei Sitzungen stellen die Tests über ``_session_key``
nach."""

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import streamlit as st
from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from test_web_k3_anbindung import sidebar_text
from test_web_k3_ui import git, sidebar_button, start

from sprintforecast import gitsync
from sprintforecast.git import classify
from sprintforecast.web import ui

SESSION = "test session id"  # die Sitzungs-ID, die AppTest vergibt


@pytest.fixture(autouse=True)
def fresh_slots(monkeypatch):
    """Kein Zustand von einem Test zum nächsten (der Speicher gilt für den ganzen Prozess)."""
    ui._SYNC_SLOTS.clear()
    monkeypatch.setattr(ui, "SYNC_WAIT_SECONDS", 0.3)  # ein Test, der warten soll, setzt mehr
    yield
    ui._SYNC_SLOTS.clear()


def slot_of(session: str = SESSION) -> ui._SyncSlot:
    """Der Speicher einer Sitzung (wird angelegt, falls es ihn noch nicht gibt)."""
    return ui._SYNC_SLOTS.setdefault(session, ui._SyncSlot())


def all_text(at) -> str:
    """Alles, was die Sitzung zeigt (Seitenleiste und Hauptbereich)."""
    groups = (at.markdown, at.error, at.warning, at.info, at.success, at.caption)
    return "\n".join(e.value for group in groups for e in group)


def commit(rev: str = "abc1234") -> gitsync.Commit:
    return gitsync.Commit(rev=rev, author="Bob", day="2026-10-15", subject="Fehltage")


def after(seconds: float, action) -> None:
    timer = threading.Timer(seconds, action)
    timer.daemon = True
    timer.start()


def busy(session: str = SESSION, safety: float = 6.0) -> ui._SyncSlot:
    """In dieser Sitzung läuft ein Abgleich (in einem anderen Thread). Als Sicherung endet er
    nach ``safety`` Sekunden von selbst, damit ein fehlschlagender Test nicht hängt."""
    slot = slot_of(session)
    assert slot.begin()
    after(safety, slot.end)
    return slot


# --- Der Kern: das Ergebnis geht nicht verloren ------------------------------------------------


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
    assert slot_of().pending(data_dir) == stopped  # liegt bereit, ist nicht verloren
    # Der nächste Durchlauf (der neue, den Streamlit gestartet hat) holt das Ergebnis nach.
    at.run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Eigene Änderungen gesichert" in text and "Hochgeladen" in text
    assert slot_of().pending(data_dir) == []
    at.run()  # und zeigt es nur einmal
    assert "Hochgeladen" not in sidebar_text(at)


class CountingState:
    """Wie ``st.session_state``, aber der ``n``-te Zugriff wirft ``StopException``: Streamlit
    stoppt einen Durchlauf bei der nächsten Berührung des Sitzungszustands, an beliebiger Stelle."""

    def __init__(self, real, n: int):
        self.real, self.left = real, n

    def touch(self):
        self.left -= 1
        if self.left == 0:
            raise StopException

    def get(self, *args):
        self.touch()
        return self.real.get(*args)

    def pop(self, *args):
        self.touch()
        return self.real.pop(*args)

    def __getitem__(self, key):
        self.touch()
        return self.real[key]

    def __setitem__(self, key, value):
        self.touch()
        self.real[key] = value


class WithState:
    """Ersatz für ``ui.st``: der Sitzungszustand ist gezählt, alles andere bleibt."""

    def __init__(self, state):
        self.session_state = state

    def __getattr__(self, name):
        return getattr(st, name)


def test_result_survives_a_stop_at_every_step_of_remembering(shared, data_dir, monkeypatch):
    """Der Abbruch kann an jeder Berührung des Sitzungszustands in ``_remember_sync_result``
    kommen. Der nächste Durchlauf holt das Ergebnis nach; es erscheint genau einmal."""
    monkeypatch.setattr(
        ui,
        "sync",
        lambda *a, **k: gitsync.SyncResult(
            committed="abc1234", pulled=[commit()], pulled_files=[("M", "x.yaml")], pushed=True
        ),
    )
    at = start(data_dir, monkeypatch)
    real = ui._remember_sync_result
    stops = []

    def shown_once(n: int) -> None:
        assert not at.exception, (n, at.exception)
        text = sidebar_text(at)
        assert text.count("Hochgeladen") == 1, (n, text)
        assert "1 Änderung(en) von anderen übernommen" in text, n
        assert slot_of().pending(data_dir) == [], n
        assert "sync_result" not in at.session_state and "sync_earlier" not in at.session_state, n

    for n in range(1, 60):
        outcome = []

        def remember(result, n=n, outcome=outcome):
            ui.st = WithState(CountingState(st.session_state, n))  # hier stoppt Streamlit
            try:
                real(result)
            except StopException:
                outcome.append("stopped")
                raise
            finally:
                ui.st = st
            outcome.append("finished")

        monkeypatch.setattr(ui, "_remember_sync_result", remember)
        sidebar_button(at, "Speichern und teilen").click().run()
        monkeypatch.setattr(ui, "_remember_sync_result", real)
        assert outcome, "der Abgleich lief nicht"
        if outcome == ["finished"]:  # kein Abbruch mehr: die Meldung steht gleich da
            shown_once(n)
            break
        at.run()  # der Durchlauf, den Streamlit gestartet hat
        shown_once(n)
        stops.append(n)
    else:
        pytest.fail("die Übernahme wurde nie vollständig")
    assert len(stops) >= 5, stops  # die Probe hat tatsächlich mitten in der Übernahme gestoppt


def test_a_second_sync_before_the_first_result_was_taken_shows_both(shared, data_dir, monkeypatch):
    """Das Ergebnis des ersten Abgleichs liegt noch bereit (sein Durchlauf wurde gestoppt), da
    startet der zweite Klick den nächsten: Beide Meldungen erscheinen, keine überschreibt die
    andere."""
    results = iter(
        [
            gitsync.SyncResult(committed="aaa1111", pushed=True),
            gitsync.SyncResult(pulled=[commit("bbb2222")], pulled_files=[("M", "y.yaml")]),
        ]
    )
    monkeypatch.setattr(ui, "sync", lambda *a, **k: next(results))
    at = start(data_dir, monkeypatch)
    real = ui._remember_sync_result
    stopped = []

    def stop_once(result):
        if not stopped:
            stopped.append(result)
            raise StopException
        real(result)

    monkeypatch.setattr(ui, "_remember_sync_result", stop_once)
    button = sidebar_button(at, "Speichern und teilen")
    button.click().run()  # Abgleich 1 fertig, Übernahme gestoppt: Ergebnis liegt bereit
    assert len(slot_of().pending(data_dir)) == 1
    button.click().run()  # Abgleich 2: übernimmt zuerst das bereitliegende Ergebnis
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Eigene Änderungen gesichert (aaa1111)" in text and "Hochgeladen" in text
    assert "1 Änderung(en) von anderen übernommen" in text
    assert text.index("aaa1111") < text.index("von anderen übernommen")  # in der Reihenfolge
    assert slot_of().pending(data_dir) == []


def test_earlier_results_show_no_second_copy_of_the_input_fields(shared, data_dir, monkeypatch):
    """Zwei Abgleiche hintereinander mit „Name und E-Mail fehlen“: Die Eingabefelder erscheinen
    einmal (derselbe Schlüssel zweimal wäre ein Fehler), beide Meldungen stehen da."""
    at = start(data_dir, monkeypatch)
    problem = classify("*** Please tell me who you are.")
    at.session_state["sync_earlier"] = [gitsync.SyncResult(error=problem)]
    at.session_state["sync_result"] = gitsync.SyncResult(error=problem)
    at.run()
    assert not at.exception, at.exception
    assert [e.key for e in at.sidebar.text_input if e.key == "git-name"] == ["git-name"]
    assert sidebar_text(at).count("Name und E-Mail-Adresse fehlen") == 2


# --- Ein zweiter Klick, ein langer Abgleich ------------------------------------------------------


def test_a_dropped_click_is_answered(shared, data_dir, monkeypatch):
    """Läuft in dieser Sitzung schon ein Abgleich, startet der Klick keinen zweiten und sagt,
    dass er nicht ausgeführt wurde."""
    calls = []
    monkeypatch.setattr(ui, "sync", lambda *a, **k: calls.append(a) or gitsync.SyncResult())
    at = start(data_dir, monkeypatch)
    slot = busy()
    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    assert not calls
    assert "Dieser Klick wurde nicht ausgeführt" in all_text(at)
    slot.end()
    at.run()
    sidebar_button(at, "Speichern und teilen").click().run()
    assert len(calls) == 1  # danach geht es wieder
    assert "Alles ist auf dem aktuellen Stand." in sidebar_text(at)


def test_a_new_run_waits_for_the_running_sync_and_shows_its_result(shared, data_dir, monkeypatch):
    monkeypatch.setattr(ui, "SYNC_WAIT_SECONDS", 8.0)
    at = start(data_dir, monkeypatch)
    slot = busy(safety=7.0)

    def finish():
        slot.put(data_dir, gitsync.SyncResult(committed="abc1234", pushed=True))
        slot.end()

    after(0.5, finish)
    started = time.monotonic()
    at.run()
    assert time.monotonic() - started >= 0.4  # hat gewartet
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Eigene Änderungen gesichert (abc1234)" in text and "Hochgeladen" in text
    assert "läuft noch" not in text


def test_a_run_stops_waiting_after_the_time_limit_and_says_the_sync_is_still_running(
    shared, data_dir, monkeypatch
):
    at = start(data_dir, monkeypatch)
    slot = busy(safety=8.0)
    started = time.monotonic()
    at.run()
    assert time.monotonic() - started < 5.0  # nicht bis zum Ende des Abgleichs
    assert not at.exception, at.exception
    assert at.header, "die Seite wurde nicht gezeichnet"
    assert "Der Abgleich mit dem Server läuft noch" in sidebar_text(at)
    labels = [b.label for b in at.sidebar.button]
    assert "Aktualisieren" in labels and "Speichern und teilen" not in labels
    # Der Abgleich endet; „Aktualisieren“ holt das Ergebnis.
    slot.put(data_dir, gitsync.SyncResult(committed="abc1234", pushed=True))
    slot.end()
    next(b for b in at.sidebar.button if b.label == "Aktualisieren").click().run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Eigene Änderungen gesichert (abc1234)" in text and "Hochgeladen" in text
    assert "läuft noch" not in text
    assert "Speichern und teilen" in [b.label for b in at.sidebar.button]


def test_the_lock_is_released_when_the_sync_raises(shared, data_dir, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(ui, "sync", broken)
    at = start(data_dir, monkeypatch)
    sidebar_button(at, "Speichern und teilen").click().run()
    assert any("kaputt" in e.value for e in at.exception)
    assert not slot_of().running
    assert slot_of().pending(data_dir) == []
    monkeypatch.setattr(ui, "sync", lambda *a, **k: gitsync.SyncResult())
    at.run()
    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    assert "Alles ist auf dem aktuellen Stand." in sidebar_text(at)


# --- Sitzungen und Datenordner ----------------------------------------------------------------


def test_two_sessions_do_not_block_each_other(shared, data_dir, monkeypatch):
    """In Sitzung A läuft ein Abgleich. Sitzung B wartet nicht darauf, ihr Klick wird nicht
    verworfen, und ihr Ergebnis landet bei B."""
    current = {"session": "A"}
    monkeypatch.setattr(ui, "_session_key", lambda: current["session"])
    monkeypatch.setattr(ui, "SYNC_WAIT_SECONDS", 8.0)
    calls = []
    monkeypatch.setattr(ui, "sync", lambda *a, **k: calls.append(a) or gitsync.SyncResult())
    start(data_dir, monkeypatch)
    slot_a = ui._find_sync_slot(create=True)  # so findet auch der Code Sitzung A: unter "A"
    assert slot_a is ui._SYNC_SLOTS["A"] and slot_a.begin()
    after(7.0, slot_a.end)  # Sicherung: Ein fehlschlagender Test soll nicht hängen
    current["session"] = "B"
    at = start(data_dir, monkeypatch)
    started = time.monotonic()
    sidebar_button(at, "Speichern und teilen").click().run()
    assert time.monotonic() - started < 4.0  # B musste nicht auf A warten
    assert not at.exception, at.exception
    assert len(calls) == 1, "der Klick in B wurde verworfen"
    assert "Alles ist auf dem aktuellen Stand." in sidebar_text(at)
    assert slot_a.running and not slot_of("B").running
    assert slot_a.pending(data_dir) == []  # nichts von B bei A


def test_pending_messages_survive_the_cleanup_of_stale_inputs(shared, data_dir, monkeypatch):
    """Haben sich die Dateien geändert (hier: durch das Teilen), verwirft die Seite offene
    Eingaben. Die Meldungen zum Abgleich gehören nicht dazu."""
    at = start(data_dir, monkeypatch)
    at.switch_page("seiten/review.py").run()  # eine Teamseite merkt sich den Stand der Dateien
    assert not at.exception, at.exception
    sprint = data_dir / "demo/sprints/2026.20.yaml"
    sprint.write_text(sprint.read_text().replace("velocity: 9.75", "velocity: 5.0"))  # von außen
    at.session_state["sync_earlier"] = [gitsync.SyncResult(committed="aaa1111", pushed=True)]
    at.session_state["sync_result"] = gitsync.SyncResult(committed="bbb2222")
    slot_of().begin()  # und ein weiterer Abgleich läuft noch
    at.run()
    assert not at.exception, at.exception
    assert "Die Daten haben sich geändert" in all_text(at)  # die Bereinigung lief
    text = sidebar_text(at)
    assert "aaa1111" in text and "bbb2222" in text
    assert "Der Abgleich mit dem Server läuft noch" in text


def test_results_for_another_data_folder_are_not_applied(shared, data_dir, tmp_path, monkeypatch):
    """Mehrere Schlüssel: Was zu einem anderen Datenordner gehört, wird nicht angewendet (die
    Sitzung hat den Ordner inzwischen gewechselt) und verfällt; das für diesen Ordner erscheint."""
    at = start(data_dir, monkeypatch)
    slot = slot_of()
    elsewhere = tmp_path / "anderer-ordner"
    slot.put(elsewhere, gitsync.SyncResult(committed="fff9999", pushed=True))
    slot.put(data_dir, gitsync.SyncResult(committed="abc1234", pushed=True))
    at.run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "abc1234" in text and "fff9999" not in text
    assert slot.pending(elsewhere) == [] and slot.pending(data_dir) == []
    at.run()
    assert "fff9999" not in sidebar_text(at)


def test_orphaned_slots_are_cleaned_up(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(ui, "_now", lambda: clock["now"])
    monkeypatch.setattr(ui, "_session_key", lambda: "meine")
    for session in ("verwaist", "laeuft", "frisch"):
        slot_of(session).put(Path("x"), gitsync.SyncResult(pushed=True))
    ui._SYNC_SLOTS["laeuft"].begin()  # ein Abgleich läuft noch: bleibt, wie lange auch immer
    clock["now"] += ui.SYNC_SLOT_TTL + 1
    ui._SYNC_SLOTS["frisch"].touched = clock["now"]  # gerade benutzt
    assert ui._find_sync_slot(create=False) is None  # kein Speicher angelegt, wo keiner war
    assert set(ui._SYNC_SLOTS) == {"laeuft", "frisch"}  # der Zugriff räumt auf
    clock["now"] += ui.SYNC_SLOT_TTL + 1
    own = ui._find_sync_slot(create=True)  # die eigene Sitzung gilt als gerade benutzt
    assert own is not None and set(ui._SYNC_SLOTS) == {"laeuft", "meine"}


# --- Der Speicher selbst ------------------------------------------------------------------------


def test_begin_is_refused_while_running_and_wait_idle_times_out():
    slot = ui._SyncSlot()
    assert slot.begin()
    assert not slot.begin() and slot.running
    started = time.monotonic()
    assert slot.wait_idle(0.2) is False
    assert 0.15 <= time.monotonic() - started < 2.0
    after(0.2, slot.end)
    assert slot.wait_idle(5.0) is True  # wacht auf, sobald der Abgleich endet
    assert slot.begin()


def test_discarding_one_result_leaves_an_equal_one(tmp_path):
    slot = ui._SyncSlot()
    first, second = gitsync.SyncResult(pushed=True), gitsync.SyncResult(pushed=True)
    assert first == second and first is not second
    slot.put(tmp_path, first)
    slot.put(tmp_path, second)
    slot.discard(tmp_path, second)  # gleich ist auch ``first``: Es zählt, welches gemeint ist
    [left] = slot.pending(tmp_path)
    assert left is first
    slot.discard(tmp_path, first)
    assert slot.pending(tmp_path) == []
