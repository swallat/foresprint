# SPDX-License-Identifier: EUPL-1.2
"""References for the YAML writer of the Go core (go/internal/yamlx): values of every type the
storage writes, dumped with ``storage.dump_yaml`` (PyYAML safe_dump, width 100).

Each case is ``{"name", "value", "yaml"}``; the value is encoded with explicit types so that Go
builds exactly the same value: ``{"str": s}``, ``{"int": "12"}``, ``{"float": "repr"}``,
``{"bool": b}``, ``{"null": 0}``, ``{"date": iso}``, ``{"datetime": iso}``, ``{"list": [..]}``,
``{"map": [[key, value], ..]}``.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from foresprint import storage

STRINGS = [
    "",
    " ",
    "a",
    "plain text",
    "2026.1",
    "2026.20",
    "1",
    "-1",
    "0",
    "007",
    "0x1F",
    "1_000",
    "1:30",
    "1e3",
    ".5",
    "5.",
    "+.inf",
    ".nan",
    "1.0e+10",
    "true",
    "True",
    "no",
    "NO",
    "on",
    "Off",
    "yes",
    "null",
    "Null",
    "~",
    "=",
    "<<",
    "!",
    "&a",
    "*a",
    "#x",
    "a #b",
    "a#b",
    "- x",
    "-x",
    "?",
    "? x",
    ":",
    ": x",
    "a: b",
    "a:b",
    "a :b",
    "[x]",
    "{x}",
    "x, y",
    "x,y",
    "a'b",
    "'a'",
    '"a"',
    'a"b',
    'O\'Neil: the "second"',
    "back\\slash",
    "tab\there",
    "line\nbreak",
    "two\n\nbreaks",
    "trail\n",
    "\nlead",
    " lead",
    "trail ",
    "a  b",
    "a \n b",
    "a\n b",
    "---",
    "--- x",
    "...",
    "...x",
    "Zoë Äpfel",
    "日本語のテキスト",
    "emoji 😀 here",
    " nbsp",
    "a b",
    " x",
    "x\u0085y",
    "﻿bom",
    "ctl\x01x",
    "del\x7fx",
    "\x00",
    "2026-01-07",
    "2026-01-07 10:00:00",
    "2026-1-7",
    "2026-01-07T10:00:00Z",
    "%percent",
    "@at",
    "`tick",
    "|pipe",
    ">gt",
    "a|b",
    "a>b",
    "x" * 99,
    "x" * 100,
    "x" * 101,
    "x" * 130,
    "word " * 30,
    "word " * 30 + "end",
    " ".join(["w"] * 120),
    "a" * 98 + " b c d e f",
    "ab " * 40,
    "é" * 120,
    ("é" * 10 + " ") * 12,
    "A long note that has to wrap because it is longer than one hundred characters, which is "
    "the width the dumper uses.",
    "'" * 5,
    "it's " * 25,
    ("it's a " * 20).strip(),
    '"' * 3,
    ('say "hi" ' * 16).strip(),
    ("tab\t" * 30),
    ("\\ " * 60),
    ("é\n" * 3),
    "a\n" * 3 + "b",
    ("x" * 90) + " " + ("y" * 30) + "\n" + "z",
]

FLOATS = [
    0.0,
    -0.0,
    1.0,
    -1.0,
    0.5,
    0.1,
    0.30000000000000004,
    41.5,
    67.0,
    1e15,
    1e16,
    1.5e16,
    1e17,
    123456789012345678.0,
    1e22,
    1e-4,
    1e-5,
    1.5e-5,
    123456.789e-10,
    5e-324,
    1.7976931348623157e308,
    2.5e-7,
    100.0,
    1234567.125,
    0.000123,
    1 / 3,
    2 / 3,
    1e100,
    -1e-100,
    float("inf"),
    float("-inf"),
    float("nan"),
]

INTS = [0, 1, -1, 7, 14, 2026, 10**15, 10**18, -(10**18), 2**63 - 1, 2**64, 10**30, -(2**70)]


def enc(v: Any) -> Any:
    if v is None:
        return {"null": 0}
    if isinstance(v, bool):
        return {"bool": v}
    if isinstance(v, int):
        return {"int": str(v)}
    if isinstance(v, float):
        return {"float": repr(v)}
    if isinstance(v, str):
        return {"str": v}
    if isinstance(v, datetime):
        return {"datetime": v.isoformat(" ")}
    if isinstance(v, date):
        return {"date": v.isoformat()}
    if isinstance(v, list):
        return {"list": [enc(x) for x in v]}
    if isinstance(v, dict):
        return {"map": [[enc(k), enc(x)] for k, x in v.items()]}
    raise TypeError(type(v))


def scalar_pool(rng: random.Random) -> Any:
    kind = rng.randrange(9)
    if kind <= 3:
        return rng.choice(STRINGS)
    if kind == 4:
        return rng.choice(FLOATS[:-1])
    if kind == 5:
        return rng.choice(INTS)
    if kind == 6:
        return rng.choice([True, False, None])
    if kind == 7:
        return date(2026, 1, 1) + timedelta(days=rng.randrange(900))
    return datetime(2026, 1, 1, 8, 0, 0) + timedelta(seconds=rng.randrange(10**7))


def tree(rng: random.Random, depth: int) -> Any:
    kind = rng.randrange(6) if depth < 4 else 0
    if kind == 0 or kind == 1:
        return scalar_pool(rng)
    if kind in (2, 3):
        items = [tree(rng, depth + 1) for _ in range(rng.randrange(0, 5))]
        return items
    keys = rng.sample(STRINGS, rng.randrange(0, 5))
    return {k: tree(rng, depth + 1) for k in keys}


def root(rng: random.Random) -> Any:
    if rng.random() < 0.15:
        return [tree(rng, 1) for _ in range(rng.randrange(0, 5))]
    keys = rng.sample(STRINGS, rng.randrange(0, 7))
    return {k: tree(rng, 1) for k in keys}


def generate(ctx: Any) -> None:
    cases: list[dict[str, Any]] = []

    def add(name: str, value: Any) -> None:
        cases.append({"name": name, "value": enc(value), "yaml": storage.dump_yaml(value)})

    for i, s in enumerate(STRINGS):
        add(f"string-{i}", {"key": s})
        add(f"string-in-list-{i}", [s])
        add(f"string-as-key-{i}", {s: 1})
        add(f"string-nested-{i}", {"a": {"b": [s, {"c": s}]}})
    for i, f in enumerate(FLOATS):
        add(f"float-{i}", {"value": f})
    for i, n in enumerate(INTS):
        add(f"int-{i}", {"value": n})
    add("empty-map", {})
    add("empty-list", [])
    add("empties", {"a": {}, "b": [], "c": [[], {}], "d": [{"x": []}]})
    add(
        "indentless",
        {"list": [1, 2], "nested": [[1, 2], [3, [4]]], "maps": [{"a": 1, "b": [1]}, {}]},
    )
    add(
        "dates",
        {
            "d": date(2026, 1, 7),
            "t": datetime(2026, 10, 14, 8, 0, 0),
            "u": datetime(2026, 10, 14, 8, 0, 0, 123456),
        },
    )
    add("bool-keys", {True: 1, 5: 2, 1.5: 3})
    add("tz-aware", {"t": datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone(timedelta(hours=2)))})
    rng = random.Random(20261021)
    for i in range(400):
        add(f"random-{i}", root(rng))
    ctx.write("yamlemit/cases.json", ctx.dump_json(cases))
