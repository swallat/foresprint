# SPDX-License-Identifier: EUPL-1.2
"""Zusammenführen auf Schlüsselebene und stabiles Schreiben."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sprintforecast.storage import ConflictError, DataError, Repository, has_conflict_markers
from sprintforecast.yamlmerge import MISSING, merge3, same

BASE = {"velocity": 10, "absences": {"anna": 1}, "note": "x", "list": [1, 2]}


def test_different_keys_are_united():
    ours = {**BASE, "velocity": 11}
    theirs = {**BASE, "absences": {"anna": 1, "ben": 2}}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert conflicts == []
    assert merged["velocity"] == 11 and merged["absences"] == {"anna": 1, "ben": 2}


def test_nan_values_are_the_same_value():
    assert same(float("nan"), float("nan"))
    assert same([1, float("nan")], [1, float("nan")])
    assert not same(float("nan"), 1.0)
    merged, conflicts = merge3(
        {"v": float("nan")}, {"v": float("nan"), "a": 1}, {"v": float("nan"), "b": 2}
    )
    assert conflicts == [] and merged["a"] == 1 and merged["b"] == 2


def test_same_change_on_both_sides_is_no_conflict():
    merged, conflicts = merge3(BASE, {**BASE, "velocity": 9}, {**BASE, "velocity": 9})
    assert conflicts == [] and merged["velocity"] == 9


def test_nested_keys_merge_but_same_value_conflicts():
    ours = {**BASE, "absences": {"anna": 2}}
    theirs = {**BASE, "absences": {"anna": 3, "ben": 1}}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert [(c.path, c.ours, c.theirs) for c in conflicts] == [(("absences", "anna"), 2, 3)]
    assert merged["absences"] == {"anna": 2, "ben": 1}  # Standard: meine Seite


def test_choices_decide_conflicts():
    ours, theirs = {**BASE, "velocity": 11}, {**BASE, "velocity": 12}
    assert merge3(BASE, ours, theirs, {("velocity",): "theirs"})[0]["velocity"] == 12
    assert merge3(BASE, ours, theirs, {("velocity",): "ours"})[0]["velocity"] == 11
    assert merge3(BASE, ours, theirs, {("velocity",): "ours"})[1] == []


def test_deleted_on_one_side_changed_on_other_is_conflict():
    ours = {k: v for k, v in BASE.items() if k != "note"}
    theirs = {**BASE, "note": "geändert"}
    merged, conflicts = merge3(BASE, ours, theirs)
    assert conflicts[0].path == ("note",) and conflicts[0].ours is MISSING
    assert "note" not in merged
    assert merge3(BASE, ours, theirs, {("note",): "theirs"})[0]["note"] == "geändert"


def test_delete_without_change_on_other_side_wins():
    ours = {k: v for k, v in BASE.items() if k != "note"}
    merged, conflicts = merge3(BASE, ours, dict(BASE))
    assert conflicts == [] and "note" not in merged


def test_lists_are_one_value_unless_entries_have_ids():
    merged, conflicts = merge3(BASE, {**BASE, "list": [1, 3]}, {**BASE, "list": [1, 2, 4]})
    assert [c.path for c in conflicts] == [("list",)]
    base = {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}]}
    ours = {"people": [{"id": "a", "fte": 0.5}, {"id": "b", "fte": 1}]}
    theirs = {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}, {"id": "c", "fte": 1}]}
    merged, conflicts = merge3(base, ours, theirs)
    assert conflicts == []
    assert merged["people"] == [
        {"id": "a", "fte": 0.5},
        {"id": "b", "fte": 1},
        {"id": "c", "fte": 1},
    ]
    theirs2 = {"people": [{"id": "a", "fte": 0.8}, {"id": "b", "fte": 1}]}
    _, conflicts = merge3(base, ours, theirs2)
    assert conflicts[0].path == ("people", "[a]", "fte")


def test_added_on_both_sides_without_base():
    merged, conflicts = merge3(MISSING, {"a": 1}, {"b": 2})
    assert conflicts == [] and merged == {"a": 1, "b": 2}


MARKED = "a: 1\n<<<<<<< HEAD\nb: 2\n=======\nb: 3\n>>>>>>> origin/main\n"


def test_conflict_markers_are_detected_before_loading(data_dir: Path):
    assert has_conflict_markers(MARKED) and not has_conflict_markers("a: 1\n")
    sprint = data_dir / "demo" / "sprints" / "2026.20.yaml"
    sprint.write_text(MARKED)
    repo = Repository(data_dir)
    with pytest.raises(ConflictError) as info:
        repo.load("demo")
    assert info.value.files == [sprint]
    assert isinstance(info.value, DataError)  # bestehende Fehlerbehandlung greift weiter
    with pytest.raises(ConflictError):
        repo.load_cached("demo")


def test_write_is_stable(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    sprint = data.sprints[-1]
    path = repo.save_sprint("demo", sprint)
    first = path.read_bytes()
    stamp = path.stat().st_mtime_ns
    repo.save_sprint("demo", repo.load("demo").sprints[-1])
    assert path.read_bytes() == first and path.stat().st_mtime_ns == stamp  # unverändert
    assert b"\r" not in first and first.endswith(b"\n")
    # Personen und Produkte erscheinen sortiert: Ergänzungen kollidieren seltener
    sprint.absences = {"zoe": 1.0, "anna": 2.0}
    text = repo.save_sprint("demo", sprint).read_text()
    assert text.index("anna:") < text.index("zoe:")
    assert not list(path.parent.glob("*.tmp"))


# --- Prognosen: Vereinigung über ``at`` ---------------------------------------------------------


def prog(minute: int, comment: str = "", **more) -> dict:
    entry = {"at": datetime(2026, 10, 18, 9, minute, 0), "forecast_ist": 20.0, **more}
    if comment:
        entry["comment"] = comment
    return entry


def sprint(*progs: dict, **more) -> dict:
    return {"velocity": 10, "prognoses": list(progs), **more}


def test_both_sides_append_a_prognosis_and_both_stay():
    a, b, c = prog(0, "Start"), prog(10, "Alice"), prog(20, "Bob")
    merged, conflicts = merge3(sprint(a), sprint(a, b), sprint(a, c))
    assert conflicts == []
    assert merged["prognoses"] == [a, b, c]


def test_base_without_prognoses():
    b, c = prog(10, "Alice"), prog(20, "Bob")
    merged, conflicts = merge3({"velocity": 10}, sprint(b), sprint(c))
    assert conflicts == [] and merged["prognoses"] == [b, c]
    merged, conflicts = merge3({"velocity": 10}, sprint(b), {"velocity": 10, "prognoses": [c]})
    assert conflicts == [] and merged["prognoses"] == [b, c]


def test_same_at_and_same_content_is_one_entry():
    a = prog(10, "gleich")
    merged, conflicts = merge3(sprint(), sprint(a, prog(30, "x")), sprint(dict(a)))
    assert conflicts == [] and merged["prognoses"] == [a, prog(30, "x")]


def test_same_at_with_other_content_conflicts_only_on_that_entry():
    start, mine, other = prog(0, "Start"), prog(10, "meine"), prog(10, "andere")
    extra = prog(20, "nur Bob")
    ours, theirs = sprint(start, mine), sprint(start, other, extra)
    merged, conflicts = merge3(sprint(start), ours, theirs)
    [conflict] = conflicts
    at = "2026-10-18T09:10:00"
    assert conflict.path == ("prognoses", f"[{at}]")
    assert conflict.label == f"prognoses.[{at}]"
    assert (conflict.ours, conflict.theirs) == (mine, other)
    assert merged["prognoses"] == [start, mine, extra]  # ohne Wahl bleibt meine Seite
    for choice, expected in (("ours", mine), ("theirs", other)):
        merged, conflicts = merge3(sprint(start), ours, theirs, {conflict.path: choice})
        assert conflicts == [] and merged["prognoses"] == [start, expected, extra]


def test_one_side_deletes_or_changes_an_existing_prognosis():
    a, b = prog(0, "a"), prog(10, "b")
    c = prog(20, "neu")
    base = sprint(a, b)
    merged, conflicts = merge3(base, sprint(b), sprint(a, b, c))  # ich lösche a, andere hängen an
    assert conflicts == [] and merged["prognoses"] == [b, c]
    changed = prog(10, "geändert")
    merged, conflicts = merge3(base, sprint(a, changed), sprint(a, b, c))
    assert conflicts == [] and merged["prognoses"] == [a, changed, c]
    # eine Seite löscht, die andere ändert denselben Eintrag: Konflikt nur dieses Eintrags
    merged, conflicts = merge3(base, sprint(a), sprint(a, changed))
    [conflict] = conflicts
    assert conflict.ours is MISSING and conflict.theirs == changed
    assert merged["prognoses"] == [a]
    merged, _ = merge3(base, sprint(a), sprint(a, changed), {conflict.path: "theirs"})
    assert merged["prognoses"] == [a, changed]


def test_result_is_sorted_by_at_and_stable():
    early, mid, late = prog(0), prog(10), prog(50)
    merged, _ = merge3(sprint(), sprint(late, early), sprint(mid))
    assert merged["prognoses"] == [early, mid, late]


def test_at_as_datetime_and_as_text_is_the_same_time():
    as_text = {**prog(10, "gleich"), "at": "2026-10-18T09:10:00"}
    as_space = {**prog(10, "gleich"), "at": "2026-10-18 09:10:00"}
    merged, conflicts = merge3(sprint(), sprint(prog(10, "gleich")), sprint(as_text))
    assert conflicts == [] and len(merged["prognoses"]) == 1
    other = prog(5, "früher")
    merged, conflicts = merge3(sprint(), sprint(as_space, prog(20)), sprint(other))
    assert conflicts == []
    assert [p["at"] for p in merged["prognoses"]] == [other["at"], "2026-10-18 09:10:00",
                                                       prog(20)["at"]]  # fmt: skip


def test_zone_aware_and_naive_times_can_be_sorted_together():
    aware = {**prog(10, "mit Zone"), "at": datetime(2026, 10, 18, 9, 10, tzinfo=UTC)}
    merged, conflicts = merge3(sprint(), sprint(aware), sprint(prog(5)))
    assert conflicts == [] and len(merged["prognoses"]) == 2


def test_zone_aware_times_are_sorted_by_the_instant_not_the_wall_clock():
    plus2 = {
        **prog(0, "07:05 UTC"),
        "at": datetime(2026, 10, 18, 9, 5, tzinfo=timezone(timedelta(hours=2))),
    }
    utc = {**prog(0, "09:03 UTC"), "at": datetime(2026, 10, 18, 9, 3, tzinfo=UTC)}
    merged, conflicts = merge3(sprint(), sprint(utc), sprint(plus2))
    assert conflicts == [] and merged["prognoses"] == [plus2, utc]


def test_microseconds_do_not_make_a_different_time():
    """Wie beim Speichern (``replace(microsecond=0)``) zählt ``at`` auf die Sekunde genau."""
    precise = {**prog(10, "gleich"), "at": datetime(2026, 10, 18, 9, 10, 0, 123456)}
    merged, conflicts = merge3(sprint(), sprint(prog(10, "gleich")), sprint(precise))
    assert conflicts == [] and len(merged["prognoses"]) == 1
    other = {**precise, "comment": "anders"}
    merged, conflicts = merge3(sprint(), sprint(prog(10, "gleich")), sprint(other))
    [conflict] = conflicts
    assert conflict.path == ("prognoses", "[2026-10-18T09:10:00]")
    assert len(merged["prognoses"]) == 1


@pytest.mark.parametrize(
    "broken",
    [
        [{"comment": "ohne at"}],
        [prog(10), prog(10, "doppelt")],
        [{"at": "kein Zeitpunkt"}],
    ],
)
@pytest.mark.parametrize("side", ["ours", "theirs", "base"])
def test_missing_or_duplicate_at_falls_back_to_one_value(broken, side):
    base, ours, theirs = sprint(prog(0)), sprint(prog(0), prog(20)), sprint(prog(0), prog(30))
    if side == "base":
        base = sprint(*broken)
    elif side == "ours":
        ours = sprint(*broken)
    else:
        theirs = sprint(*broken)
    merged, conflicts = merge3(base, ours, theirs)
    [conflict] = conflicts
    assert conflict.path == ("prognoses",)  # die ganze Liste als ein Wert
    assert merged["prognoses"] == ours["prognoses"]


def test_other_lists_without_id_stay_one_value():
    entry = prog(10)
    _, conflicts = merge3({"notes": [entry]}, {"notes": [entry, prog(20)]},
                               {"notes": [entry, prog(30)]})  # fmt: skip
    [conflict] = conflicts
    assert conflict.path == ("notes",)
