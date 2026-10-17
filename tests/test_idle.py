# SPDX-License-Identifier: EUPL-1.2
from sprintforecast import idle
from sprintforecast.idle import IdleWatch


def test_never_stops_before_first_session():
    watch = IdleWatch(grace=20, poll=2)
    assert not any(watch.update(0, now) for now in range(0, 200, 2))


def test_session_gone_before_first_count_still_stops():
    watch = IdleWatch(grace=20, poll=2, seen=True)
    assert not any(watch.update(0, now) for now in range(2, 22, 2))
    assert watch.update(0, 22)


def test_stops_after_grace_without_session():
    watch = IdleWatch(grace=20, poll=2)
    assert not watch.update(1, 0)
    assert not any(watch.update(0, now) for now in range(2, 22, 2))
    assert watch.update(0, 22)


def test_reconnect_within_grace_resets_timer():
    watch = IdleWatch(grace=20, poll=2)
    watch.update(1, 0)
    watch.update(0, 2)
    assert not watch.update(1, 4)  # Neuladen des Fensters
    assert not any(watch.update(0, now) for now in range(6, 26, 2))
    assert watch.update(0, 26)


def test_long_gap_such_as_sleep_restarts_wait():
    watch = IdleWatch(grace=20, poll=2)
    watch.update(1, 0)
    watch.update(0, 2)
    assert not watch.update(0, 3600)  # Rechner schlief: Browser darf sich erst verbinden
    assert not watch.update(0, 3610)
    assert watch.update(0, 3620)


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv(idle.IDLE_ENV, raising=False)
    monkeypatch.setattr(idle, "_started", False)
    idle.start_idle_watch()
    assert idle._started is False


def test_loop_stops_server_when_idle():
    stopped = []
    counts = iter([1, 0, 0])
    watch = IdleWatch(grace=0, poll=0)
    idle._loop(watch, lambda: next(counts), lambda: stopped.append(True))
    assert stopped == [True]
