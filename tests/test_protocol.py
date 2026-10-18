# SPDX-License-Identifier: EUPL-1.2
"""Protokolle der Sprint-Termine: schreiben, auflisten, bei Aufheben des Einfrierens obsolet."""

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import sprintforecast.protocol as protocol_module
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


def test_a_stale_lock_makes_the_next_save_use_the_following_second(tmp_path: Path):
    repo = Repository(tmp_path)
    folder = tmp_path / "demo" / "protokolle"
    folder.mkdir(parents=True)
    text = "# T\n\nStand: 1\n\nx\n"
    tag = hashlib.sha256(text.encode("utf-8")).hexdigest()[:4]  # Namensbestandteil aus dem Inhalt
    (folder / f"2026.21-review-20261016-144305-{tag}.md.lock").write_text("", encoding="utf-8")
    path = write_protocol(repo, "demo", "2026.21", REVIEW, text, NOW)
    assert path.name == f"2026.21-review-20261016-144306-{tag}.md"


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
