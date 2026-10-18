# SPDX-License-Identifier: EUPL-1.2
"""Protokolle der Sprint-Termine: schreiben, auflisten, bei Aufheben des Einfrierens obsolet."""

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

import sprintforecast.protocol as protocol_module
from sprintforecast.config import config_dir
from sprintforecast.protocol import (
    PLANNING,
    PREPLANNING,
    REVIEW,
    list_protocols,
    mark_obsolete,
    obsolete_with_save,
    render_protocol,
    save_with_protocol,
    write_protocol,
    write_protocol_new,
)
from sprintforecast.storage import FileAccessError, Repository

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
    from sprintforecast.model import Sprint

    return Sprint(id="2026.21", start=date(2026, 10, 12), end=date(2026, 10, 26), **fields)


def test_a_change_the_text_does_not_show_still_creates_a_protocol(tmp_path: Path):
    """``scope_creep`` steht nicht im Protokolltext, ändert aber die gespeicherte Sprintdatei."""
    repo = Repository(tmp_path)
    text = "# T\n\nStand: 1\n\nwert\n"
    kwargs = dict(repo=repo, team="demo", sprint_id="2026.21", kind=REVIEW, text=text)
    first = save_with_protocol(
        now=NOW, sprints=[sprint_stub(scope_creep=0.1)], save=lambda: [], **kwargs
    )
    save_with_protocol(now=LATER, sprints=[sprint_stub(scope_creep=0.1)], save=lambda: [], **kwargs)
    assert len(list_protocols(repo, "demo", "2026.21")) == 1  # unverändert
    save_with_protocol(now=LATER, sprints=[sprint_stub(scope_creep=0.2)], save=lambda: [], **kwargs)
    assert first == [] and len(list_protocols(repo, "demo", "2026.21")) == 2


def test_the_protocol_is_written_before_the_sprint_and_removed_if_saving_fails(tmp_path: Path):
    repo = Repository(tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "protokolle").write_text("im Weg", encoding="utf-8")
    saved: list[int] = []
    with pytest.raises(FileAccessError):  # Protokoll nicht schreibbar: Sprint bleibt unberührt
        save_with_protocol(
            repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, [sprint_stub()],
            lambda: saved.append(1) or [],
        )  # fmt: skip
    assert saved == []
    (tmp_path / "demo" / "protokolle").unlink()

    def failing() -> list[Path]:
        raise FileAccessError("kein Schreibrecht")

    with pytest.raises(FileAccessError):  # Speichern scheitert: das neue Protokoll verschwindet
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
    from sprintforecast.model import Sprint
    from sprintforecast.storage import save_sprints_together

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
    assert repo.sprint_path("demo", "2026.21").read_bytes() == before  # zurückgesetzt
    assert not repo.sprint_path("demo", "2026.22").exists()
    monkeypatch.setattr(Repository, "save_sprint", real)
    paths = save_sprints_together(repo, "demo", [one, two])
    assert [p.name for p in paths] == ["2026.21.yaml", "2026.22.yaml"]


def test_saving_the_same_state_twice_writes_one_protocol_even_with_a_pinned_state(tmp_path: Path):
    """``save_sprint`` legt den Stand der Fehltage beim Speichern fest; der Fingerabdruck muss den
    festgelegten Stand schon vorher enthalten, sonst gälte die zweite Speicherung als neu."""
    from sprintforecast.model import ProductValues
    from sprintforecast.storage import _read, sprint_from_dict

    repo = Repository(tmp_path)
    # Ältere Datei, die nur die PO-Vorplanung enthält: Fehltage unbekannt, nichts festgelegt.
    repo.save_sprint("demo", sprint_stub(products={"kwg": ProductValues(preplanned=1.0)}))
    path = repo.sprint_path("demo", "2026.21")

    def save_twice() -> int:
        for _ in range(2):
            sprint = sprint_from_dict(_read(path), str(path))  # wie die Seite: aus der Datei
            sprint.forecast_ist = 12.0  # das Planning trägt das Commitment ein
            save_with_protocol(
                repo, "demo", "2026.21", PLANNING, "# T\n\nStand: 1\n\nx\n", NOW, [sprint],
                lambda sprint=sprint: [repo.save_sprint("demo", sprint)],
            )  # fmt: skip
        return len(list_protocols(repo, "demo", "2026.21"))

    assert save_twice() == 1


def test_the_protocol_name_stays_invisible_until_the_file_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Während des Schreibens (und nach einem Abbruch) gibt es keine leere Datei mit gültigem
    Protokollnamen; nur eine ``.lock``-Datei, die nie gelistet wird."""
    repo = Repository(tmp_path)
    seen: list[list[Path]] = []
    real = protocol_module.write_text

    def spy(path: Path, text: str, newline=None) -> None:
        seen.append([f[3] for f in list_protocols(repo, "demo", "2026.21")])
        raise KeyboardInterrupt  # Abbruch mitten im Schreiben

    monkeypatch.setattr(protocol_module, "write_text", spy)
    with pytest.raises(KeyboardInterrupt):
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    monkeypatch.setattr(protocol_module, "write_text", real)
    assert seen == [[]]  # beim Schreiben noch nichts gelistet
    assert list_protocols(repo, "demo", "2026.21") == []
    assert not list((tmp_path / "demo" / "protokolle").glob("*.lock"))  # aufgeräumt
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
    with pytest.raises(FileAccessError, match="Sprintdatei gesperrt"):
        save_with_protocol(
            repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, [sprint_stub()],
            failing,
        )  # fmt: skip


def run_concurrently(tasks: list) -> list:
    """Startet die Aufgaben gleichzeitig (Barriere) und liefert ihre Ergebnisse."""
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
    assert sum(created for _, created in results) == 1  # genau eine Sitzung hat geschrieben
    assert len({path for path, _ in results}) == 1
    assert len(list_protocols(repo, "demo", "2026.21")) == 1
    assert not list((tmp_path / "demo" / "protokolle").glob("*.lock"))  # Sperre freigegeben


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
    other_session = protocol_module._locked(folder, "2026.21", REVIEW)  # schreibt gerade
    with other_session, pytest.raises(FileAccessError, match="andere Sitzung"):
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert list_protocols(repo, "demo", "2026.21") == []
    # Nach der Freigabe geht das Speichern wieder.
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
    threading.Timer(0.3, release.set).start()  # nach 0,3 s freigeben, der Wartende wartet
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
        pass  # frei: kein Warten, kein Fehler


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
    """Aktualisiertes Datenverzeichnis ohne Ordner ``protokolle``: Eine andere Sitzung legt ihn
    gerade an und schreibt ein Protokoll. Die Aufhebung darf nicht an der Sperre vorbei
    speichern."""
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
    assert saved == []  # nichts gespeichert, solange die andere Sitzung die Sperre hält


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
    """Sitzung A hebt das Einfrieren auf, es gibt noch keinen Ordner; Sitzung B speichert in der
    Zwischenzeit das Planning samt Protokoll. B darf erst fertig werden, wenn A gespeichert hat:
    Sonst bliebe B's Protokoll gültig, obwohl A die Prognose danach aufhebt."""
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
        time.sleep(0.3)  # B hat inzwischen angefragt und wartet auf die Sperre
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
    """Sitzung A (``first(save)``) steckt in ihrem ``save`` und scheitert erst 0,3 s, nachdem
    Sitzung B (``second()``) losgelaufen ist; B startet erst, wenn A im ``save`` steckt. Liefert die
    Ergebnisse (A, B); ``order`` bekommt „a-failed“, kurz bevor A scheitert."""
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
        time.sleep(0.3)  # B hat inzwischen angefragt und wartet auf die Sperre
        release.set()

    a, b, _ = run_concurrently([lambda: first(failing_save), session_b, releaser])
    return a, b


def test_a_second_save_takes_over_the_protocol_only_after_the_first_one_has_failed(tmp_path: Path):
    """Sitzung A legt das Protokoll an, ihr Speichern scheitert; Sitzung B mit demselben Stand
    darf das Protokoll nicht übernehmen, das A gleich wieder löscht: Das Protokoll gehört zu B's
    erfolgreichem Speichern."""
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
    assert order == ["a-failed", "b-saved"]  # B wartet, bis A zurückgebaut hat
    found = list_protocols(repo, "demo", "2026.21")
    assert len(found) == 1 and found[0][3].exists()  # B's Speichern hat sein Protokoll


@pytest.mark.parametrize("second_session", ["mark_obsolete", "obsolete_with_save"])
def test_a_second_unfreeze_sees_the_protocols_only_after_the_first_one_was_rolled_back(
    tmp_path: Path, second_session: str
):
    """Sitzung A benennt das Protokoll um, ihr Speichern scheitert und sie benennt zurück. Sitzung B
    darf in der Zwischenzeit nichts sehen: Sie fände sonst keine gültigen Protokolle und speichert,
    während A das Protokoll danach wieder gültig macht."""
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
    assert order == ["a-failed", "b-done"]  # B sieht erst, wenn A zurückgebaut hat
    if second_session == "mark_obsolete":
        assert len(b) == 1  # B fand das wieder gültige Protokoll und benannte es um
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21")] == [True]  # nur obsolet


def test_the_lock_file_lies_outside_the_data_folder_and_is_per_sprint_and_kind(tmp_path: Path):
    folder = protocol_folder(tmp_path)
    one = protocol_module._lock_file(folder, "2026.21", REVIEW)
    assert tmp_path not in one.parents  # nie im Git-Arbeitsverzeichnis
    assert one != protocol_module._lock_file(folder, "2026.22", REVIEW)
    assert one != protocol_module._lock_file(folder, "2026.21", PLANNING)
    assert one == protocol_module._lock_file(folder, "2026.21", REVIEW)


def test_the_lock_file_lies_in_the_users_settings_folder(tmp_path: Path):
    """Nicht in einem festen Ordner des gemeinsamen Temp-Verzeichnisses, sondern beim Benutzer. Die
    Fixture ``isolated_config`` (conftest) lenkt ihn für Tests in ein Wegwerfverzeichnis."""
    one = protocol_module._lock_file(protocol_folder(tmp_path), "2026.21", REVIEW)
    assert one.parent == config_dir() / "sperren" and one.parent.is_dir()
    assert Path(os.environ["XDG_CONFIG_HOME"]) in one.parents  # nicht der echte Einstellungsordner
    if sys.platform != "win32":
        assert one.parent.stat().st_mode & 0o777 == 0o700  # nur für den Benutzer selbst


def block(path: Path) -> Path:
    """Ein Pfad unter einer Datei: Anlegen von Ordnern dort scheitert."""
    path.write_text("im Weg", encoding="utf-8")
    return path / "sprintforecast"


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
    assert one.parent == temp / f"sprintforecast-sperren-{user}"  # je Benutzer, nicht fest
    # Gesperrt und geschrieben wird dort ganz normal.
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
    """Der Ordner ``sperren`` im Einstellungsordner ist da, aber ein Öffnen der Sperrdatei darin
    scheitert (hier: an ihrer Stelle liegt ein Ordner; unter POSIX wäre es ein fehlendes
    Schreibrecht). Dann zählt dieselbe Datei im Temp-Ordner, für alle Sitzungen gleich."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(protocol_module.tempfile, "gettempdir", lambda: str(temp))
    monkeypatch.setattr(protocol_module, "LOCK_WAIT_SECONDS", 0.2)
    folder = protocol_folder(tmp_path)
    primary = protocol_module._lock_file(folder, "2026.21", REVIEW)
    primary.mkdir()  # ein Ordner statt der Sperrdatei: Öffnen scheitert mit OSError
    path, created = write_protocol_new(
        Repository(tmp_path), "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW, "abcd1234"
    )
    assert created and path.exists()
    (fallback_dir,) = temp.glob("sprintforecast-sperren-*")
    assert (fallback_dir / primary.name).is_file()  # derselbe Dateiname wie im Einstellungsordner
    # Die Datei sperrt wirklich: Wer sie hält, hält andere Sitzungen mit denselben Rechten auf.
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
    fallback.mkdir()  # auch im Temp-Ordner taugt die Sperrdatei nicht
    with pytest.raises(FileAccessError, match="nicht gespeichert") as info:
        write_protocol(repo, "demo", "2026.21", REVIEW, "# T\n\nStand: 1\n\nx\n", NOW)
    assert str(fallback) in str(info.value)  # nennt, wo es gescheitert ist
    assert list_protocols(repo, "demo", "2026.21") == []  # nichts ohne Sperre geschrieben


def test_a_settings_lock_folder_without_write_access_is_replaced_by_the_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Der Ordner ``sperren`` gibt es schon; ``mkdir(exist_ok=True)`` gelingt, aber er ist nicht
    beschreibbar (POSIX: ``os.access``)."""
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
    # Der Ordner gehört dem echten Benutzer; für den Aufrufer (anderes Konto) ist er fremd.
    (temp / f"sprintforecast-sperren-{real_uid + 1}").mkdir()
    monkeypatch.setattr(protocol_module.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(FileAccessError, match="anderen Benutzer"):
        protocol_module._lock_file(protocol_folder(tmp_path), "2026.21", REVIEW)


def test_an_existing_file_name_moves_the_new_protocol_to_the_next_second(tmp_path: Path):
    """Gleicher Name (Sekunde und Kennung), aber anderer Inhalt: nichts wird überschrieben."""
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
    """Zwei Klone, die in derselben Sekunde Verschiedenes speichern, erzeugen nie denselben
    Dateinamen (der Inhalt geht in den Namen ein)."""
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
    # ein zweites Aufheben benennt Obsoletes nicht noch einmal um
    assert mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER) == []
