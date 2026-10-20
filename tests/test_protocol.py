# SPDX-License-Identifier: EUPL-1.2
"""Sprint meeting minutes: write, list, obsolete when the freeze is lifted."""

import errno
import getpass
import hashlib
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import foresprint.protocol as protocol_module
from foresprint.config import config_dir
from foresprint.protocol import (
    PLANNING,
    PREPLANNING,
    REVIEW,
    PlanningSection,
    latest_planning_sections,
    list_protocols,
    mark_obsolete,
    obsolete_with_save,
    render_planning_protocol,
    render_protocol,
    save_with_protocol,
    write_protocol,
    write_protocol_new,
)
from foresprint.storage import FileAccessError, Repository

NOW = datetime(2026, 10, 16, 14, 43, 5)
LATER = datetime(2026, 10, 20, 9, 0, 0)


def test_render_escapes_table_separators_and_lists_facts():
    text = render_protocol(
        PREPLANNING,
        "Team|A",
        "2026.21",
        now=NOW,
        facts=[("Kapazität", "50,6")],
        comment="Daily\nvom 16.10. | Prognose",
        notes=[("Annahmen", ["a | b"]), ("Leer", [])],
    )
    assert "- Kapazität: 50,6" in text
    assert "Team\\|A" in text and "a \\| b" in text
    assert "Daily vom 16.10. \\| Prognose" in text
    assert "## Leer" not in text


def test_write_list_and_lf_line_endings(tmp_path: Path):
    repo = Repository(tmp_path)
    path = write_protocol(repo, "demo", "2026.21", PREPLANNING, "a\nb\n", NOW)
    assert re.fullmatch(r"2026\.21-vorplanung-20261016-144305-[0-9a-f]{4}\.md", path.name)
    assert b"\r" not in path.read_bytes()
    write_protocol(repo, "demo", "2026.21", PREPLANNING, "neu\n", LATER)
    write_protocol(repo, "demo", "2026.22", PREPLANNING, "anderer Sprint\n", LATER)
    found = list_protocols(repo, "demo", "2026.21")
    assert [(f[0], f[1], f[2]) for f in found] == [
        (LATER, PREPLANNING, False),
        (NOW, PREPLANNING, False),
    ]


def test_two_saves_in_the_same_second_keep_both_protocols(tmp_path: Path):
    repo = Repository(tmp_path)
    first = write_protocol(repo, "demo", "2026.21", PREPLANNING, "# T\n\nStand: 1\n\neins\n", NOW)
    second = write_protocol(repo, "demo", "2026.21", PREPLANNING, "# T\n\nStand: 1\n\nzwei\n", NOW)
    assert first != second
    assert "eins" in first.read_text() and "zwei" in second.read_text()
    assert len(list_protocols(repo, "demo", "2026.21")) == 2


def test_an_unchanged_save_does_not_write_another_protocol(tmp_path: Path):
    repo = Repository(tmp_path)
    one = write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nwert\n", NOW)
    again = write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 2\n\nwert\n", LATER)
    assert again == one and len(list_protocols(repo, "demo", "2026.21")) == 1
    write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 3\n\nandere Zahl\n", LATER)
    assert len(list_protocols(repo, "demo", "2026.21")) == 2


def sprint_stub(**fields):
    from foresprint.model import Sprint

    return Sprint(id="2026.21", start=date(2026, 10, 12), end=date(2026, 10, 26), **fields)


def test_a_change_the_text_does_not_show_still_creates_a_protocol(tmp_path: Path):
    """``scope_creep`` is not in the minutes text but changes the saved sprint file."""
    repo = Repository(tmp_path)
    text = "# T\n\nStand: 1\n\nwert\n"
    kwargs = dict(repo=repo, team="demo", sprint_id="2026.21", kind=REVIEW, text=text)
    first = save_with_protocol(
        now=NOW, sprints=[sprint_stub(scope_creep=0.1)], save=lambda: [], **kwargs
    )
    save_with_protocol(now=LATER, sprints=[sprint_stub(scope_creep=0.1)], save=lambda: [], **kwargs)
    assert len(list_protocols(repo, "demo", "2026.21")) == 1  # unchanged
    save_with_protocol(now=LATER, sprints=[sprint_stub(scope_creep=0.2)], save=lambda: [], **kwargs)
    assert first == [] and len(list_protocols(repo, "demo", "2026.21")) == 2


def test_the_protocol_is_written_before_the_sprint_and_removed_if_saving_fails(tmp_path: Path):
    repo = Repository(tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "protokolle").write_text("im Weg", encoding="utf-8")
    saved: list[int] = []
    with pytest.raises(FileAccessError):  # minutes not writable: sprint stays untouched
        save_with_protocol(
            repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, [sprint_stub()],
            lambda: saved.append(1) or [],
        )  # fmt: skip
    assert saved == []
    (tmp_path / "demo" / "protokolle").unlink()

    def failing() -> list[Path]:
        raise FileAccessError("kein Schreibrecht")

    with pytest.raises(FileAccessError):  # saving fails: the new minutes disappear
        save_with_protocol(
            repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, [sprint_stub()],
            failing,
        )  # fmt: skip
    assert list_protocols(repo, "demo", "2026.21") == []


def test_an_unreadable_protocol_folder_is_a_file_access_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(tmp_path)
    (tmp_path / "demo" / "protokolle").mkdir(parents=True)

    def broken(self):
        raise PermissionError("verweigert")

    monkeypatch.setattr(Path, "iterdir", broken)
    with pytest.raises(FileAccessError):
        list_protocols(repo, "demo", "2026.21")


def test_failed_unfreeze_save_renames_the_protocols_back(tmp_path: Path):
    repo = Repository(tmp_path)
    plan = write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nx\n", NOW)

    def failing() -> list[Path]:
        raise FileAccessError("kein Schreibrecht")

    with pytest.raises(FileAccessError):
        obsolete_with_save(repo, "demo", "2026.21", PLANNING, LATER, failing)
    assert plan.exists()
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21")] == [False]
    ok = obsolete_with_save(repo, "demo", "2026.21", PLANNING, LATER, lambda: [])
    assert ok == [] and not plan.exists()
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21")] == [True]


def test_a_failing_rename_undoes_the_ones_already_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(tmp_path)
    first = write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\na\n", NOW)
    second = write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nb\n", LATER)
    real = Path.replace
    calls: list[int] = []

    def flaky(self: Path, target):
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError("gesperrt")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(FileAccessError):
        mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER + timedelta(days=1))
    monkeypatch.setattr(Path, "replace", real)
    assert first.exists() and second.exists()
    assert not any(f[2] for f in list_protocols(repo, "demo", "2026.21"))


def test_a_failing_multi_sprint_save_restores_the_earlier_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from foresprint.model import Sprint
    from foresprint.storage import save_sprints_together

    repo = Repository(tmp_path)
    one = Sprint(id="2026.21", start=date(2026, 10, 12), end=date(2026, 10, 26), velocity=5.0)
    two = Sprint(id="2026.22", start=date(2026, 10, 26), end=date(2026, 11, 9))
    repo.save_sprint("demo", one)
    before = repo.sprint_path("demo", "2026.21").read_bytes()
    one.velocity, two.velocity = 9.0, 7.0
    real = Repository.save_sprint

    def flaky(self, key, sprint):
        if sprint.id == "2026.22":
            raise FileAccessError("gesperrt")
        return real(self, key, sprint)

    monkeypatch.setattr(Repository, "save_sprint", flaky)
    with pytest.raises(FileAccessError):
        save_sprints_together(repo, "demo", [one, two])
    assert repo.sprint_path("demo", "2026.21").read_bytes() == before  # reset
    assert not repo.sprint_path("demo", "2026.22").exists()
    monkeypatch.setattr(Repository, "save_sprint", real)
    paths = save_sprints_together(repo, "demo", [one, two])
    assert [p.name for p in paths] == ["2026.21.yaml", "2026.22.yaml"]


def test_saving_the_same_state_twice_writes_one_protocol_even_with_a_pinned_state(tmp_path: Path):
    """``save_sprint`` fixes the state of the absences when saving; the fingerprint must already
    contain the fixed state beforehand, otherwise the second save would count as new."""
    from foresprint.model import ProductValues
    from foresprint.storage import _read, sprint_from_dict

    repo = Repository(tmp_path)
    # Older file that contains only the PO pre-planning: absences unknown, nothing fixed.
    repo.save_sprint("demo", sprint_stub(products={"kwg": ProductValues(preplanned=1.0)}))
    path = repo.sprint_path("demo", "2026.21")

    def save_twice() -> int:
        for _ in range(2):
            sprint = sprint_from_dict(_read(path), str(path))  # like the page: from the file
            sprint.commitment = 12.0  # the Planning enters the commitment
            save_with_protocol(
                repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nx\n", NOW, [sprint],
                lambda sprint=sprint: [repo.save_sprint("demo", sprint)],
            )  # fmt: skip
        return len(list_protocols(repo, "demo", "2026.21"))

    assert save_twice() == 1


def test_the_protocol_name_stays_invisible_until_the_file_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """While writing (and after an abort) there is no empty file with a valid minutes name; only
    a ``.lock`` file, which is never listed."""
    repo = Repository(tmp_path)
    seen: list[list[Path]] = []
    real = protocol_module.write_text

    def spy(path: Path, text: str, newline=None) -> None:
        seen.append([f[3] for f in list_protocols(repo, "demo", "2026.21")])
        raise KeyboardInterrupt  # abort in the middle of writing

    monkeypatch.setattr(protocol_module, "write_text", spy)
    with pytest.raises(KeyboardInterrupt):
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    monkeypatch.setattr(protocol_module, "write_text", real)
    assert seen == [[]]  # nothing listed yet while writing
    assert list_protocols(repo, "demo", "2026.21") == []
    assert not list((tmp_path / "demo" / "protokolle").glob("*.lock"))  # cleaned up
    write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert len(list_protocols(repo, "demo", "2026.21")) == 1


def test_a_failing_rollback_keeps_the_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = Repository(tmp_path)

    def failing() -> list[Path]:
        raise FileAccessError("Sprintdatei gesperrt")

    real = Path.unlink

    def locked(self: Path, missing_ok: bool = False):
        if self.suffix == ".md":
            raise PermissionError("Protokoll gesperrt")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(FileAccessError, match="Sprintdatei gesperrt") as info:
        save_with_protocol(
            repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, [sprint_stub()],
            failing,
        )  # fmt: skip
    # The rollback error is not silent: it is attached as a note to the original error.
    assert any(
        "nicht zurückgebaut" in n and "Protokoll gesperrt" in n for n in info.value.__notes__
    )


def test_a_clock_function_is_read_only_after_the_lock_is_held(tmp_path: Path):
    repo = Repository(tmp_path)
    reads: list[str] = []

    def clock() -> datetime:
        reads.append("clock")
        return NOW

    real = protocol_module._write_locked

    def spy(*args, **kwargs):
        reads.append("locked")
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(protocol_module, "_write_locked", spy)
        path = write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nx\n", clock)
    assert reads == ["locked", "clock"]
    assert f"{NOW:%Y%m%d-%H%M%S}" in path.name


def test_a_missing_clock_uses_the_current_time(tmp_path: Path):
    path = write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "# T\n\nx\n", None)
    assert path.exists()


def run_concurrently(tasks: list) -> list:
    """Starts the tasks at the same time (barrier) and returns their results."""
    barrier = threading.Barrier(len(tasks))
    results: list = [None] * len(tasks)

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = tasks[i]()
        except BaseException as e:
            results[i] = e

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(tasks))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_concurrent_saves_of_the_same_state_write_one_protocol(tmp_path: Path):
    repo = Repository(tmp_path)
    text = "# T\n\nStand: 1\n\nx\n"
    results = run_concurrently(
        [
            lambda: write_protocol_new(repo, "demo", "2026.21", REVIEW, text, NOW, "abcd1234")
            for _ in range(6)
        ]
    )
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert sum(created for _, created in results) == 1  # exactly one session wrote
    assert len({path for path, _ in results}) == 1
    assert len(list_protocols(repo, "demo", "2026.21")) == 1
    assert not list((tmp_path / "demo" / "protokolle").glob("*.lock"))  # lock released


def test_concurrent_saves_of_different_states_keep_every_protocol(tmp_path: Path):
    repo = Repository(tmp_path)
    results = run_concurrently(
        [
            lambda i=i: write_protocol_new(
                repo, "demo", "2026.21", REVIEW, f"# T\n\nStand: 1\n\nwert {i}\n", NOW, f"{i:04x}"
            )
            for i in range(6)
        ]
    )
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len(list_protocols(repo, "demo", "2026.21")) == 6


def protocol_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "demo" / "protokolle"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_a_busy_lock_is_reported_after_the_wait(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = Repository(tmp_path)
    folder = protocol_folder(tmp_path)
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    other_session = protocol_module._locked(folder, "2026.21", REVIEW)  # is writing right now
    with other_session, pytest.raises(FileAccessError, match="andere Sitzung"):
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert list_protocols(repo, "demo", "2026.21") == []
    # After the release, saving works again.
    write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert len(list_protocols(repo, "demo", "2026.21")) == 1


def test_a_waiting_save_proceeds_when_the_lock_is_released(tmp_path: Path):
    repo = Repository(tmp_path)
    folder = protocol_folder(tmp_path)
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        with protocol_module._locked(folder, "2026.21", REVIEW):
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert holding.wait(5)
    threading.Timer(0.3, release.set).start()  # release after 0.3 s, the waiting one waits
    path, created = write_protocol_new(
        repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, "abcd1234"
    )
    holder.join()
    assert created and path.exists()


def test_the_lock_is_released_after_a_failed_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = Repository(tmp_path)

    def failing(path: Path, text: str, newline=None) -> None:
        raise FileAccessError("Platte voll")

    monkeypatch.setattr(protocol_module, "write_text", failing)
    with pytest.raises(FileAccessError):
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    with protocol_module._locked(protocol_folder(tmp_path), "2026.21", REVIEW):
        pass  # free: no waiting, no error


def test_obsoleting_takes_the_same_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = Repository(tmp_path)
    write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nx\n", NOW)
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    other_session = protocol_module._locked(protocol_folder(tmp_path), "2026.21", PLANNING)
    with other_session, pytest.raises(FileAccessError, match="andere Sitzung"):
        mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    assert not any(f[2] for f in list_protocols(repo, "demo", "2026.21"))


@pytest.mark.parametrize("session", ["mark_obsolete", "obsolete_with_save"])
def test_obsoleting_takes_the_lock_even_if_the_protocol_folder_does_not_exist_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session: str
):
    """Updated data folder without a ``protokolle`` folder: another session is creating it right
    now and writing minutes. Lifting the freeze must not save past the lock."""
    repo = Repository(tmp_path)
    (tmp_path / "demo").mkdir()
    folder = tmp_path / "demo" / "protokolle"
    assert not folder.exists()
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    saved: list[int] = []
    other_session = protocol_module._locked(folder, "2026.21", PLANNING)
    with other_session, pytest.raises(FileAccessError, match="andere Sitzung"):
        if session == "mark_obsolete":
            mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
        else:
            obsolete_with_save(
                repo, "demo", "2026.21", PLANNING, LATER, lambda: saved.append(1) or []
            )
    assert saved == []  # nothing saved as long as the other session holds the lock


def test_unfreezing_without_a_protocol_folder_still_saves_and_finds_nothing_to_rename(
    tmp_path: Path,
):
    repo = Repository(tmp_path)
    assert mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER) == []
    saved = obsolete_with_save(
        repo, "demo", "2026.21", PLANNING, LATER, lambda: [tmp_path / "2026.21.yaml"]
    )
    assert saved == [tmp_path / "2026.21.yaml"]
    assert list_protocols(repo, "demo", "2026.21") == []


def test_an_unfreeze_without_a_protocol_folder_excludes_a_concurrent_planning_save(tmp_path: Path):
    """Session A lifts the freeze and there is no folder yet; session B meanwhile saves the Planning
    including minutes. B may only finish once A has saved: otherwise B's minutes would stay valid
    although A unfreezes the forecast afterwards."""
    repo = Repository(tmp_path)
    in_save, release = threading.Event(), threading.Event()
    order: list[str] = []

    def save_a() -> list[Path]:
        in_save.set()
        release.wait(5)
        order.append("a-saved")
        return []

    def session_b() -> list[Path]:
        assert in_save.wait(5)

        def save_b() -> list[Path]:
            order.append("b-saved")
            return []

        return save_with_protocol(
            repo,
            "demo",
            "2026.21",
            PLANNING,
            "# T\n\nStand: 1\n\nx\n",
            NOW,
            [sprint_stub()],
            save_b,
        )

    def releaser() -> None:
        assert in_save.wait(5)
        time.sleep(0.3)  # B has asked meanwhile and waits for the lock
        release.set()

    results = run_concurrently(
        [
            lambda: obsolete_with_save(repo, "demo", "2026.21", PLANNING, LATER, save_a),
            session_b,
            releaser,
        ]
    )
    assert results[:2] == [[], []], results
    assert order == ["a-saved", "b-saved"]


def run_with_failing_first_session(first, second, order: list[str]) -> tuple:
    """Session A (``first(save)``) is stuck in its ``save`` and fails only 0.3 s after session B
    (``second()``) has started; B starts only once A is stuck in ``save``. Returns the results
    (A, B); ``order`` receives "a-failed" shortly before A fails."""
    in_save, b_started, release = (threading.Event() for _ in range(3))

    def failing_save() -> list[Path]:
        in_save.set()
        release.wait(5)
        order.append("a-failed")
        raise FileAccessError("kein Schreibrecht")

    def session_b():
        assert in_save.wait(5)
        b_started.set()
        return second()

    def releaser() -> None:
        assert in_save.wait(5) and b_started.wait(5)
        time.sleep(0.3)  # B has asked meanwhile and waits for the lock
        release.set()

    a, b, _ = run_concurrently([lambda: first(failing_save), session_b, releaser])
    return a, b


def test_a_second_save_takes_over_the_protocol_only_after_the_first_one_has_failed(tmp_path: Path):
    """Session A creates the minutes, its save fails; session B with the same state must not adopt
    the minutes that A deletes again right away: the minutes belong to B's successful save."""
    repo = Repository(tmp_path)
    text = "# T\n\nStand: 1\n\nx\n"
    order: list[str] = []

    def session(save) -> list[Path]:
        return save_with_protocol(repo, "demo", "2026.21", REVIEW, text, NOW, [sprint_stub()], save)

    def save_b() -> list[Path]:
        order.append("b-saved")
        return []

    a, b = run_with_failing_first_session(session, lambda: session(save_b), order)
    assert isinstance(a, FileAccessError) and b == []
    assert order == ["a-failed", "b-saved"]  # B waits until A has rolled back
    found = list_protocols(repo, "demo", "2026.21")
    assert len(found) == 1 and found[0][3].exists()  # B's save has its minutes


@pytest.mark.parametrize("second_session", ["mark_obsolete", "obsolete_with_save"])
def test_a_second_unfreeze_sees_the_protocols_only_after_the_first_one_was_rolled_back(
    tmp_path: Path, second_session: str
):
    """Session A renames the minutes, its save fails and it renames them back. Session B must not
    see anything in the meantime: it would otherwise find no valid minutes and save, while A makes
    the minutes valid again afterwards."""
    repo = Repository(tmp_path)
    write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nx\n", NOW)
    order: list[str] = []

    def second() -> list[Path]:
        if second_session == "mark_obsolete":
            renamed = mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
        else:
            renamed = obsolete_with_save(repo, "demo", "2026.21", PLANNING, LATER, lambda: [])
        order.append("b-done")
        return renamed

    a, b = run_with_failing_first_session(
        lambda save: obsolete_with_save(repo, "demo", "2026.21", PLANNING, LATER, save),
        second,
        order,
    )
    assert isinstance(a, FileAccessError) and not isinstance(b, BaseException), (a, b)
    assert order == ["a-failed", "b-done"]  # B only sees them once A has rolled back
    if second_session == "mark_obsolete":
        assert len(b) == 1  # B found the minutes that became valid again and renamed them
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21")] == [True]  # only obsolete


def test_the_lock_file_lies_outside_the_data_folder_and_is_per_sprint_and_kind(tmp_path: Path):
    folder = protocol_folder(tmp_path)
    one = protocol_module._lock_file(folder, "2026.21", REVIEW)
    assert tmp_path not in one.parents  # never in the Git working directory
    assert one != protocol_module._lock_file(folder, "2026.22", REVIEW)
    assert one != protocol_module._lock_file(folder, "2026.21", PLANNING)
    assert one == protocol_module._lock_file(folder, "2026.21", REVIEW)


def test_the_lock_file_lies_in_the_users_settings_folder(tmp_path: Path):
    """Not in a fixed folder of the shared temp directory but with the user. The fixture
    ``isolated_config`` (conftest) redirects it to a throwaway directory for tests."""
    one = protocol_module._lock_file(protocol_folder(tmp_path), "2026.21", REVIEW)
    assert one.parent == config_dir() / "sperren" and one.parent.is_dir()
    assert Path(os.environ["XDG_CONFIG_HOME"]) in one.parents  # not the real settings folder
    if sys.platform != "win32":
        assert one.parent.stat().st_mode & 0o777 == 0o700  # only for the user themselves


def block(path: Path) -> Path:
    """A path below a file: creating folders there fails."""
    path.write_text("im Weg", encoding="utf-8")
    return path / "foresprint"


def test_an_unwritable_settings_folder_falls_back_to_a_per_user_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    blocked = block(tmp_path / "einstellungen")
    monkeypatch.setattr(protocol_module, "config_dir", lambda: blocked)
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    folder = protocol_folder(tmp_path)
    one = protocol_module._lock_file(folder, "2026.21", REVIEW)
    user = str(os.getuid()) if sys.platform != "win32" else re.sub(r"\W", "_", getpass.getuser())
    assert one.parent == temp / f"sprintforecast-sperren-{user}"  # per user, not fixed
    # Locking and writing work as usual there.
    path, created = write_protocol_new(
        Repository(tmp_path), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, "abcd1234"
    )
    assert created and path.exists() and one.exists()


def test_an_unwritable_temp_fallback_is_a_file_access_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    blocked = block(tmp_path / "einstellungen")
    monkeypatch.setattr(protocol_module, "config_dir", lambda: blocked)
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(blocked))
    with pytest.raises(FileAccessError):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)


def test_an_unopenable_lock_file_falls_back_to_the_same_file_in_the_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The ``sperren`` folder in the settings folder exists, but opening the lock file in it fails
    (here: a folder lies in its place; under POSIX it would be a missing write permission). Then
    the same file in the temp folder counts, the same for all sessions."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    folder = protocol_folder(tmp_path)
    primary = protocol_module._lock_file(folder, "2026.21", REVIEW)
    primary.mkdir()  # a folder instead of the lock file: opening fails with OSError
    path, created = write_protocol_new(
        Repository(tmp_path), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, "abcd1234"
    )
    assert created and path.exists()
    (fallback_dir,) = temp.glob("sprintforecast-sperren-*")
    assert (fallback_dir / primary.name).is_file()  # same file name as in the settings folder
    # The file really locks: whoever holds it holds up other sessions with the same permissions.
    with (
        protocol_module._locked(folder, "2026.21", REVIEW),
        pytest.raises(FileAccessError, match="andere Sitzung"),
    ):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "andere\n", NOW)


def test_lock_files_that_cannot_be_opened_anywhere_are_a_file_access_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    repo = Repository(tmp_path)
    folder = protocol_folder(tmp_path)
    primary = protocol_module._lock_file(folder, "2026.21", REVIEW)
    primary.mkdir()
    fallback = protocol_module._fallback_lock_dir() / primary.name
    fallback.mkdir()  # the lock file is no good in the temp folder either
    with pytest.raises(FileAccessError, match="nicht gespeichert") as info:
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert str(fallback) in str(info.value)  # names where it failed
    assert list_protocols(repo, "demo", "2026.21") == []  # nothing written without a lock


def test_a_settings_lock_folder_without_write_access_is_replaced_by_the_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The ``sperren`` folder already exists; ``mkdir(exist_ok=True)`` succeeds, but it is not
    writable (POSIX: ``os.access``)."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    root = config_dir() / "sperren"
    root.mkdir(parents=True)
    real_access = os.access

    def access(path, mode, **kwargs) -> bool:
        return False if Path(path) == root else real_access(path, mode, **kwargs)

    monkeypatch.setattr(protocol_module.os, "access", access)
    one = protocol_module._lock_file(protocol_folder(tmp_path), "2026.21", REVIEW)
    assert one.parent.parent == temp and root not in one.parents


def patch_os_locking(monkeypatch: pytest.MonkeyPatch, fail) -> list[int]:
    """Makes the operating system's lock (``msvcrt.locking`` or ``fcntl.flock``) fail with the error
    ``fail(n)`` on the nth lock attempt (from 1) (``None``: really lock). Releasing stays real.
    Returns the list of lock attempts so far."""
    attempts: list[int] = []

    def error_of_next() -> OSError | None:
        attempts.append(len(attempts) + 1)
        return fail(len(attempts))

    if sys.platform == "win32":
        import msvcrt

        real_locking = msvcrt.locking

        def locking(fd: int, mode: int, nbytes: int) -> None:
            if mode != msvcrt.LK_UNLCK and (error := error_of_next()):
                raise error
            real_locking(fd, mode, nbytes)

        monkeypatch.setattr(msvcrt, "locking", locking)
    else:
        import fcntl

        real_flock = fcntl.flock

        def flock(fd: int, operation: int) -> None:
            if not operation & fcntl.LOCK_UN and (error := error_of_next()):
                raise error
            real_flock(fd, operation)

        monkeypatch.setattr(fcntl, "flock", flock)
    return attempts


def os_error(code: int) -> OSError:
    return OSError(code, os.strerror(code))


# Errors reported by a file system without file locks (e.g. some network folders).
PERMANENT_ERRNOS = [errno.ENOLCK, errno.ENOSYS, errno.EINVAL, errno.EIO, errno.EOPNOTSUPP]
BUSY_ERRNOS = [errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK]


@pytest.mark.parametrize("code", BUSY_ERRNOS)
def test_a_lock_held_by_another_session_is_busy_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
):
    patch_os_locking(monkeypatch, lambda n: os_error(code))
    with (tmp_path / "x.lock").open("a+b") as handle:
        assert protocol_module._try_lock(handle) is False


@pytest.mark.parametrize("code", PERMANENT_ERRNOS)
def test_any_other_locking_error_is_permanent(tmp_path: Path, monkeypatch, code: int):
    patch_os_locking(monkeypatch, lambda n: os_error(code))
    with (
        (tmp_path / "x.lock").open("a+b") as handle,
        pytest.raises(protocol_module._LockUnsupported),
    ):
        protocol_module._try_lock(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Fehlernummern")
@pytest.mark.parametrize("winerror", [32, 33])
def test_windows_sharing_and_lock_violations_are_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int
):
    patch_os_locking(monkeypatch, lambda n: OSError(0, "belegt", None, winerror))
    with (tmp_path / "x.lock").open("a+b") as handle:
        assert protocol_module._try_lock(handle) is False


def test_a_permanent_locking_error_falls_back_to_the_temp_folder_without_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The settings folder is on a drive without file locks: the lock goes through the same file in
    the temp folder, immediately."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 5.0)
    attempts = patch_os_locking(monkeypatch, lambda n: os_error(errno.ENOLCK) if n == 1 else None)
    started = time.monotonic()
    path, created = write_protocol_new(
        Repository(tmp_path), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, "abcd1234"
    )
    assert created and path.exists()
    assert time.monotonic() - started < 2.5  # no waiting time
    assert len(attempts) == 2  # first the settings folder, then the temp folder once
    (fallback_dir,) = temp.glob("sprintforecast-sperren-*")
    assert len(list(fallback_dir.glob("*.lock"))) == 1


def test_a_permanent_locking_error_everywhere_is_a_file_access_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 5.0)
    attempts = patch_os_locking(monkeypatch, lambda n: os_error(errno.ENOLCK))
    repo = Repository(tmp_path)
    started = time.monotonic()
    with pytest.raises(FileAccessError, match="Dateisperren") as info:
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert "andere Sitzung" not in str(info.value)
    assert time.monotonic() - started < 2.5  # no waiting time
    assert len(attempts) == 2  # once the settings folder, once the temp folder, no more
    assert list_protocols(repo, "demo", "2026.21") == []  # nothing is written without a lock


def test_the_missing_file_lock_support_is_reported_in_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, english
):
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(tmp_path))
    patch_os_locking(monkeypatch, lambda n: os_error(errno.ENOLCK))
    with pytest.raises(FileAccessError, match="File locks are not supported"):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)


@pytest.mark.parametrize("code", [errno.EACCES, errno.EAGAIN])
def test_real_contention_still_waits_and_reports_another_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.3)
    attempts = patch_os_locking(monkeypatch, lambda n: os_error(code))
    started = time.monotonic()
    with pytest.raises(FileAccessError, match="andere Sitzung"):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)
    assert time.monotonic() - started >= 0.3  # waited
    assert len(attempts) > 2  # tried several times
    assert not list(temp.glob("sprintforecast-sperren-*"))  # temp folder untouched


@pytest.mark.skipif(sys.platform == "win32", reason="Eigentümer von Ordnern nur auf POSIX")
def test_a_temp_folder_owned_by_another_user_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    blocked = block(tmp_path / "einstellungen")
    monkeypatch.setattr(protocol_module, "config_dir", lambda: blocked)
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    real_uid = os.getuid()
    # The folder belongs to the real user; for the caller (another account) it is foreign.
    (temp / f"sprintforecast-sperren-{real_uid + 1}").mkdir()
    monkeypatch.setattr(protocol_module.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(FileAccessError, match="anderen Benutzer"):
        protocol_module._lock_file(protocol_folder(tmp_path), "2026.21", REVIEW)


def test_an_existing_file_name_moves_the_new_protocol_to_the_next_second(tmp_path: Path):
    """Same name (second and identifier), but different content: nothing is overwritten."""
    repo = Repository(tmp_path)
    folder = protocol_folder(tmp_path)
    text = "# T\n\nStand: 1\n\nx\n"
    tag = hashlib.sha256(text.encode("utf-8")).hexdigest()[:4]
    taken = folder / f"2026.21-review-20261016-144305-{tag}.md"
    taken.write_text("# T\n\nStand: 1\n\nanderer Inhalt\n", encoding="utf-8")
    path = write_protocol(repo, "demo", "2026.21", REVIEW, text, NOW)
    assert path.name == f"2026.21-review-20261016-144306-{tag}.md"
    assert "anderer Inhalt" in taken.read_text(encoding="utf-8")


def test_different_states_saved_in_the_same_second_get_different_names(tmp_path: Path):
    """Two clones that save different things in the same second never produce the same file name
    (the content goes into the name)."""
    first = write_protocol(
        Repository(tmp_path / "a"), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nalice\n", NOW
    )
    second = write_protocol(
        Repository(tmp_path / "b"), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nbob\n", NOW
    )
    assert first.name != second.name


def test_a_protocol_with_invalid_utf8_does_not_break_writing(tmp_path: Path):
    repo = Repository(tmp_path)
    folder = tmp_path / "demo" / "protokolle"
    folder.mkdir(parents=True)
    (folder / "2026.21-review-20261016-144305.md").write_bytes(b"\xff\xfe kaputt \x80")
    new = write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", LATER)
    assert new.read_text(encoding="utf-8").startswith("# T")
    assert len(list_protocols(repo, "demo", "2026.21")) == 2


def test_a_filename_with_an_impossible_date_is_ignored(tmp_path: Path):
    repo = Repository(tmp_path)
    folder = tmp_path / "demo" / "protokolle"
    folder.mkdir(parents=True)
    (folder / "2026.21-review-20261340-250000.md").write_text("x", encoding="utf-8")
    good = write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert [f[3] for f in list_protocols(repo, "demo", "2026.21")] == [good]


def test_two_unfreezes_in_the_same_second_keep_both_obsolete_files(tmp_path: Path):
    repo = Repository(tmp_path)
    write_protocol(repo, "demo", "2026.21", PLANNING, "a\n", NOW)
    mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    write_protocol(repo, "demo", "2026.21", PLANNING, "b\n", NOW + timedelta(hours=1))
    mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    obsolete = [f for f in list_protocols(repo, "demo", "2026.21") if f[2]]
    assert sorted(f[3].read_text() for f in obsolete) == ["a\n", "b\n"]


def test_a_blocked_protocol_folder_is_a_file_access_error(tmp_path: Path):
    repo = Repository(tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "protokolle").write_text("im Weg", encoding="utf-8")
    with pytest.raises(FileAccessError):
        write_protocol(repo, "demo", "2026.21", PREPLANNING, "x\n", NOW)


def test_writing_or_renaming_invalidates_the_git_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[int] = []
    monkeypatch.setattr(protocol_module, "invalidate_status", lambda: calls.append(1))
    repo = Repository(tmp_path)
    write_protocol(repo, "demo", "2026.21", PLANNING, "x\n", NOW)
    assert len(calls) == 1
    mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    assert len(calls) == 2


def test_unfreeze_marks_only_the_planning_protocol_obsolete(tmp_path: Path):
    repo = Repository(tmp_path)
    plan = write_protocol(repo, "demo", "2026.21", PLANNING, "x\n", NOW)
    pre = write_protocol(repo, "demo", "2026.21", PREPLANNING, "y\n", NOW)
    renamed = mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    assert len(renamed) == 1
    assert renamed[0].name.endswith("_obsolet_20261020-090000.md")
    assert not plan.exists() and pre.exists() and renamed[0].read_text() == "x\n"
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21") if f[1] == PLANNING] == [True]
    # a second unfreeze does not rename obsolete minutes again
    assert mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER) == []


def planning_text(repo: Repository, now: datetime, *, plan: bool, commitment: bool) -> str:
    return render_planning_protocol(
        "Team",
        "2026.21",
        now=now,
        facts=[("Kapazität (PT)", "50")],
        sections=[
            PlanningSection("absences", "Fehltage", ["- Anna: 2 Tage"]),
            PlanningSection("plan", "Einplanung", ["- Eingeplant: 8"], recorded=plan),
            PlanningSection("commitment", "Commitment", ["- Commitment: 9"], recorded=commitment),
        ],
        previous=latest_planning_sections(repo, "demo", "2026.21"),
    )


def test_planning_protocol_lists_every_section_and_marks_missing_ones(tmp_path: Path):
    repo = Repository(tmp_path)
    text = planning_text(repo, NOW, plan=False, commitment=False)
    assert text.index("## Fehltage") < text.index("## Einplanung") < text.index("## Commitment")
    assert "- Anna: 2 Tage" in text and "_noch nicht erfasst_" in text
    assert text.count("_Stand: 16.10.2026 14:43_") == 1  # only the recorded section


def test_each_section_keeps_its_own_stand_while_unchanged(tmp_path: Path):
    repo = Repository(tmp_path)
    write_protocol(
        repo,
        "demo",
        "2026.21",
        PLANNING,
        planning_text(repo, NOW, plan=False, commitment=False),
        NOW,
    )
    second = planning_text(repo, LATER, plan=True, commitment=False)
    assert "_Stand: 16.10.2026 14:43_\n\n- Anna: 2 Tage" in second  # absences: old state
    assert "_Stand: 20.10.2026 09:00_\n\n- Eingeplant: 8" in second  # scheduling: new
    write_protocol(repo, "demo", "2026.21", PLANNING, second, LATER)
    sections = latest_planning_sections(repo, "demo", "2026.21")
    assert sections["absences"] == ("Stand: 16.10.2026 14:43", ["- Anna: 2 Tage"])
    assert sections["plan"][0] == "Stand: 20.10.2026 09:00"


def test_an_unchanged_planning_state_gives_the_same_text_and_no_new_protocol(tmp_path: Path):
    repo = Repository(tmp_path)
    one = write_protocol(
        repo, "demo", "2026.21", PLANNING, planning_text(repo, NOW, plan=True, commitment=True), NOW
    )
    again_text = planning_text(repo, LATER, plan=True, commitment=True)
    assert write_protocol(repo, "demo", "2026.21", PLANNING, again_text, LATER) == one
    assert len(list_protocols(repo, "demo", "2026.21")) == 1


def test_a_missing_or_unreadable_planning_protocol_yields_no_sections(tmp_path: Path):
    repo = Repository(tmp_path)
    assert latest_planning_sections(repo, "demo", "2026.21") == {}
    path = write_protocol(repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n", NOW)
    path.write_bytes(b"\xff\xfe")
    assert latest_planning_sections(repo, "demo", "2026.21") == {}


def test_a_transient_error_creating_the_lock_folder_is_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))

    def flaky(path):
        raise OSError(errno.EMFILE, "Zu viele offene Dateien")

    monkeypatch.setattr(protocol_module, "_private_dir", flaky)
    with pytest.raises(FileAccessError, match="nicht gespeichert"):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)
    assert not list(temp.glob("sprintforecast-sperren-*"))


def test_a_transient_error_opening_the_lock_file_is_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    real = Path.open

    def flaky(self, mode="r", *args, **kwargs):
        if self.suffix == ".lock":
            raise OSError(errno.EMFILE, "Zu viele offene Dateien")
        return real(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky)
    with pytest.raises(FileAccessError, match="nicht gespeichert"):
        write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)
    assert not list(temp.glob("sprintforecast-sperren-*"))


def test_a_file_where_the_lock_folder_belongs_falls_back_to_the_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp = tmp_path / "temp"
    temp.mkdir()
    settings = tmp_path / "einstellungen"
    settings.mkdir()
    (settings / "sperren").write_text("keine Ordner")
    monkeypatch.setattr(protocol_module, "config_dir", lambda: settings)
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    path = write_protocol(Repository(tmp_path), "demo", "2026.21", REVIEW, "x\n", NOW)
    assert path.exists()
    assert list(temp.glob("sprintforecast-sperren-*"))
