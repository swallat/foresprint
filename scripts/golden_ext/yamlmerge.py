# SPDX-License-Identifier: EUPL-1.2
# ruff: noqa: E501
"""Golden references of the three-way merge (``foresprint.yamlmerge``).

Each case has the three versions (base, ours, theirs), optional decisions for conflicts and the
result of ``merge3``. Values are written as tagged JSON so that the type survives exactly:

    ["map", [[key, value], ...]]  ["list", [...]]   ["str", "x"]     ["int", "5"]
    ["float", "5.0"]              ["bool", true]     ["null"]        ["missing"]
    ["date", "2026-01-31"]        ["datetime", "2026-10-18T09:10:00+00:00"]

Floats are Python's ``repr`` so that ``nan`` and ``1e+16`` are exact. The Go test reads the three
versions, merges them and compares result and conflicts.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from foresprint.yamlmerge import MISSING, header_of, merge3


def tag(value: Any) -> Any:
    if value is MISSING:
        return ["missing"]
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, dict):
        return ["map", [[tag(k), tag(v)] for k, v in value.items()]]
    if isinstance(value, list):
        return ["list", [tag(v) for v in value]]
    raise TypeError(type(value))


NAN = float("nan")
BASE = {"velocity": 10, "absences": {"anna": 1}, "note": "x", "list": [1, 2]}


def prog(minute: int, comment: str = "", **more: Any) -> dict:
    entry = {"at": datetime(2026, 10, 18, 9, minute, 0), "forecast_ist": 20.0, **more}
    if comment:
        entry["comment"] = comment
    return entry


def sprint(*progs: dict, **more: Any) -> dict:
    return {"velocity": 10, "prognoses": list(progs), **more}


def cases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def case(name: str, base: Any, ours: Any, theirs: Any, choices=None) -> None:
        out.append(
            {"name": name, "base": base, "ours": ours, "theirs": theirs, "choices": choices or []}
        )

    no_note = {k: v for k, v in BASE.items() if k != "note"}
    case("different-keys", BASE, {**BASE, "velocity": 11},
         {**BASE, "absences": {"anna": 1, "ben": 2}})  # fmt: skip
    case("nan", {"v": NAN}, {"v": NAN, "a": 1}, {"v": NAN, "b": 2})
    case("same-change", BASE, {**BASE, "velocity": 9}, {**BASE, "velocity": 9})
    case("nested", BASE, {**BASE, "absences": {"anna": 2}},
         {**BASE, "absences": {"anna": 3, "ben": 1}})  # fmt: skip
    ours, theirs = {**BASE, "velocity": 11}, {**BASE, "velocity": 12}
    case("choice-theirs", BASE, ours, theirs, [[["velocity"], "theirs"]])
    case("choice-ours", BASE, ours, theirs, [[["velocity"], "ours"]])
    case("conflict-default", BASE, ours, theirs)
    case("delete-vs-change", BASE, no_note, {**BASE, "note": "geändert"})
    case("delete-vs-change-theirs", BASE, no_note, {**BASE, "note": "geändert"},
         [[["note"], "theirs"]])  # fmt: skip
    case("delete-wins", BASE, no_note, dict(BASE))
    case("list-one-value", BASE, {**BASE, "list": [1, 3]}, {**BASE, "list": [1, 2, 4]})
    people = {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}]}
    mine = {"people": [{"id": "a", "fte": 0.5}, {"id": "b", "fte": 1}]}
    case("keyed-union", people, mine,
         {"people": [{"id": "a", "fte": 1}, {"id": "b", "fte": 1}, {"id": "c", "fte": 1}]})  # fmt: skip
    case("keyed-conflict", people, mine,
         {"people": [{"id": "a", "fte": 0.8}, {"id": "b", "fte": 1}]})  # fmt: skip
    case("keyed-int-ids", {"p": [{"id": 1, "x": 1}]}, {"p": [{"id": 1, "x": 2}, {"id": 2, "x": 1}]},
         {"p": [{"id": 1, "x": 1}, {"id": 3, "x": 1}]})  # fmt: skip
    case("keyed-duplicate-ids", {"p": [{"id": "a"}]}, {"p": [{"id": "a"}, {"id": "a", "x": 1}]},
         {"p": [{"id": "b"}]})  # fmt: skip
    case("keyed-base-missing", MISSING, {"a": 1}, {"b": 2})
    case("keyed-from-empty", {"p": []}, {"p": [{"id": "a"}]}, {"p": [{"id": "b"}]})
    case("bool-is-not-int", {"v": True}, {"v": 1}, {"v": True, "w": 2})
    case("int-float-equal", {"v": 1}, {"v": 1.0}, {"v": 1, "w": 2})
    case("types", {"d": date(2026, 1, 1), "f": 1e16, "s": "x"},
         {"d": date(2026, 1, 2), "f": 1e16, "s": "x"},
         {"d": date(2026, 1, 1), "f": 1.5e-7, "s": "x"})  # fmt: skip
    case("non-string-keys", {1: "a", "k": "b"}, {1: "c", "k": "b"}, {1: "a", "k": "d", 2: "x"})
    case("scalar-vs-map", {"a": {"b": 1}}, {"a": 5}, {"a": {"b": 2}})

    # Prognoses
    a, b, c = prog(0, "Start"), prog(10, "Alice"), prog(20, "Bob")
    case("prog-append-both", sprint(a), sprint(a, b), sprint(a, c))
    case("prog-base-missing", {"velocity": 10}, sprint(b), sprint(c))
    case("prog-base-none", {"velocity": 10, "prognoses": None}, sprint(b), sprint(c))
    g = prog(10, "gleich")
    case("prog-same-entry", sprint(), sprint(g, prog(30, "x")), sprint(dict(g)))
    start, mine_, other = prog(0, "Start"), prog(10, "meine"), prog(10, "andere")
    extra = prog(20, "nur Bob")
    key = "2026-10-18T09:10:00"
    for name, choices in (("none", []), ("ours", [[["prognoses", f"[{key}]"], "ours"]]),
                          ("theirs", [[["prognoses", f"[{key}]"], "theirs"]])):  # fmt: skip
        case(f"prog-conflict-{name}", sprint(start), sprint(start, mine_),
             sprint(start, other, extra), choices)  # fmt: skip
    x, y, z = prog(0, "a"), prog(10, "b"), prog(20, "neu")
    changed = prog(10, "geändert")
    case("prog-delete-append", sprint(x, y), sprint(y), sprint(x, y, z))
    case("prog-change-append", sprint(x, y), sprint(x, changed), sprint(x, y, z))
    case("prog-delete-vs-change", sprint(x, y), sprint(x), sprint(x, changed))
    case("prog-delete-vs-change-theirs", sprint(x, y), sprint(x), sprint(x, changed),
         [[["prognoses", f"[{key}]"], "theirs"]])  # fmt: skip
    early, mid, late = prog(0), prog(10), prog(50)
    case("prog-sorted", sprint(), sprint(late, early), sprint(mid))
    as_text = {**prog(10, "gleich"), "at": "2026-10-18T09:10:00"}
    as_space = {**prog(10, "gleich"), "at": "2026-10-18 09:10:00"}
    case("prog-text-vs-datetime", sprint(), sprint(prog(10, "gleich")), sprint(as_text))
    case("prog-text-sorted", sprint(), sprint(as_space, prog(20)), sprint(prog(5, "früher")))
    aware = {**prog(10, "mit Zone"), "at": datetime(2026, 10, 18, 9, 10, tzinfo=UTC)}
    case("prog-aware-and-naive", sprint(), sprint(aware), sprint(prog(5)))
    plus2 = {**prog(0, "07:05 UTC"),
             "at": datetime(2026, 10, 18, 9, 5, tzinfo=timezone(timedelta(hours=2)))}  # fmt: skip
    utc = {**prog(0, "09:03 UTC"), "at": datetime(2026, 10, 18, 9, 3, tzinfo=UTC)}
    case("prog-instant-order", sprint(), sprint(utc), sprint(plus2))
    utc9 = {**prog(0, "gleich"), "at": datetime(2026, 10, 18, 9, 0, tzinfo=UTC)}
    plus1 = {**utc9, "at": datetime(2026, 10, 18, 10, 0, tzinfo=timezone(timedelta(hours=1)))}
    case("prog-same-instant", sprint(), sprint(utc9), sprint(plus1))
    case(
        "prog-same-instant-conflict", sprint(), sprint(utc9), sprint({**plus1, "comment": "anders"})
    )
    case("prog-same-instant-theirs", sprint(), sprint(utc9), sprint({**plus1, "comment": "anders"}),
         [[["prognoses", "[2026-10-18T09:00:00]"], "theirs"]])  # fmt: skip
    t0 = {**utc9, "at": "2026-10-18T09:00:00+00:00"}
    t1 = {**utc9, "at": "2026-10-18T10:00:00+01:00"}
    case("prog-text-zones", sprint(), sprint(t0), sprint(t1))
    case("prog-z-suffix", sprint(), sprint({**utc9, "at": "2026-10-18T09:00:00Z"}), sprint(t0))
    precise = {**prog(10, "gleich"), "at": datetime(2026, 10, 18, 9, 10, 0, 123456)}
    case("prog-microseconds", sprint(), sprint(prog(10, "gleich")), sprint(precise))
    case("prog-microseconds-conflict", sprint(), sprint(prog(10, "gleich")),
         sprint({**precise, "comment": "anders"}))  # fmt: skip
    for label, broken in (("no-at", [{"comment": "ohne at"}]),
                          ("duplicate-at", [prog(10), prog(10, "doppelt")]),
                          ("bad-at", [{"at": "kein Zeitpunkt"}])):  # fmt: skip
        for side in ("ours", "theirs", "base"):
            base_, ours_, theirs_ = (
                sprint(prog(0)),
                sprint(prog(0), prog(20)),
                sprint(prog(0), prog(30)),
            )
            if side == "base":
                base_ = sprint(*broken)
            elif side == "ours":
                ours_ = sprint(*broken)
            else:
                theirs_ = sprint(*broken)
            case(f"prog-fallback-{label}-{side}", base_, ours_, theirs_)
    entry = prog(10)
    case("other-list-no-id", {"notes": [entry]}, {"notes": [entry, prog(20)]},
         {"notes": [entry, prog(30)]})  # fmt: skip
    return out


def run(case: dict[str, Any]) -> dict[str, Any]:
    choices = {tuple(path): side for path, side in case["choices"]}
    merged, conflicts = merge3(case["base"], case["ours"], case["theirs"], choices)
    return {
        "name": case["name"],
        "base": tag(case["base"]),
        "ours": tag(case["ours"]),
        "theirs": tag(case["theirs"]),
        "choices": case["choices"],
        "merged": tag(merged),
        "conflicts": [
            {"path": list(c.path), "label": c.label, "ours": tag(c.ours), "theirs": tag(c.theirs)}
            for c in conflicts
        ],
    }


HEADERS = [
    "",
    "no header\nkey: 1\n",
    "# comment\n\n# more\nkey: 1\n# not header\n",
    "\n\n# x\r\nkey: 1\r\n",
    "# only comment",
    "   \n# after blank with spaces\nkey: 2\n",
]


def generate(ctx) -> None:
    assert not math.isnan(1.0)
    ctx.write(
        "yamlmerge/merge3.json",
        ctx.dump_json({"cases": [run(case) for case in cases()]}),
    )
    ctx.write(
        "yamlmerge/header.json",
        ctx.dump_json([{"text": text, "header": header_of(text)} for text in HEADERS]),
    )
