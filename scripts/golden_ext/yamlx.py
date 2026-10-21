# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the YAML reading (PyYAML ``CSafeLoader``, YAML 1.1) that every Python
module relies on: how plain scalars are resolved (bool, int, float, null, timestamp, merge, str),
how they are constructed (octal, hex, binary, sexagesimal, underscores, time zones), how mappings
are built (merge keys, duplicate keys, ``1 == True`` as keys) and which documents are rejected.

Values are written with a type tag so that ``1`` and ``1.0`` and ``true`` can be told apart:
``{"t": "int", "v": "12"}``, ``{"t": "map", "entries": [[key, value], ...]}`` and so on.

Written to ``golden/expected/yamlx/cases.json``. The Go port is ``go/internal/yamlx``."""

from __future__ import annotations

import datetime
import math
from typing import Any

import yaml

from foresprint.storage import _YAML_LOADER

SCALARS = [
    # null
    "",
    "~",
    "null",
    "Null",
    "NULL",
    "nULL",
    "none",
    "None",
    # bool
    "true",
    "True",
    "TRUE",
    "tRue",
    "false",
    "False",
    "FALSE",
    "yes",
    "Yes",
    "YES",
    "no",
    "No",
    "NO",
    "on",
    "On",
    "ON",
    "off",
    "Off",
    "OFF",
    "y",
    "n",
    "Y",
    "N",
    "oN",
    # int
    "0",
    "-0",
    "+0",
    "1",
    "-1",
    "+1",
    "007",
    "0o7",
    "010",
    "08",
    "09",
    "0b101",
    "0B1",
    "-0b11",
    "0x1F",
    "0X1f",
    "-0xff",
    "+0x10",
    "1_000",
    "1__0",
    "_1",
    "1_",
    "0_7",
    "0x_f",
    "0b_1",
    "12:30",
    "1:30:15",
    "-1:30",
    "+1:61",
    "1:60",
    "190:20:30",
    "0:0",
    "9223372036854775807",
    "9223372036854775808",
    "-9223372036854775808",
    "-9223372036854775809",
    "123456789012345678901234567890",
    "0x7FFFFFFFFFFFFFFF",
    "0xFFFFFFFFFFFFFFFFF",
    "1:2:3:4:5:6:7:8:9:10:11:12",
    # float
    "1.0",
    "1.",
    ".5",
    "-.5",
    "+.5",
    "1.5e+3",
    "1.5E-3",
    "1e3",
    "1e+3",
    "1.e3",
    "1.0e3",
    ".5e+1",
    ".inf",
    ".Inf",
    ".INF",
    "-.inf",
    "+.inf",
    ".nan",
    ".NaN",
    ".NAN",
    ".iNf",
    "inf",
    "nan",
    "NaN",
    "1_0.0_1",
    "1.0_",
    "1:30.5",
    "-1:30.5",
    "1:30:15.25",
    "0.1",
    "0.30000000000000004",
    "1e-7",
    "0.0001",
    "0.00001",
    "123456789012345678.0",
    "1e16",
    "1.0e+16",
    "1.0e+15",
    "9007199254740993.0",
    "5e-324",
    "1.7976931348623157e+308",
    "1.0e+400",
    "-0.0",
    "0.0",
    "100.0",
    "1e22",
    "1.0e+22",
    "12345678901234567890.0",
    # timestamp
    "2026-01-01",
    "2026-1-1",
    "2026-13-01",
    "2026-02-30",
    "0000-01-01",
    "2026-01-01T10:00:00",
    "2026-01-01t10:00:00",
    "2026-01-01 10:00:00",
    "2026-01-01  10:00:00",
    "2026-01-01\t10:00:00",
    "2026-01-01 1:00:00",
    "2026-01-01 10:00:00.5",
    "2026-01-01 10:00:00.123456789",
    "2026-01-01 10:00:00.",
    "2026-01-01 10:00:00Z",
    "2026-01-01 10:00:00 Z",
    "2026-01-01 10:00:00 +1",
    "2026-01-01 10:00:00+01:30",
    "2026-01-01 10:00:00 -05",
    "2026-01-01 10:00:00-5:00",
    "2026-01-01 24:00:00",
    "2026-01-01 10:60:00",
    "2026-01-01 10:00:60",
    "2026-01-01T10:00:00+99:00",
    "26-01-01",
    "2026-01",
    "2026/01/01",
    "12026-01-01",
    "2026-01-01 ",
    "2026-01-01x",
    # merge, value, strings
    "<<",
    "=",
    "<",
    "==",
    "foo",
    "Foo Bar",
    "a: b",
    "# c",
    "-",
    "- a",
    "?",
    "!",
    "&",
    "*",
    "0x",
    "0b",
    "0.",
    "0:",
    ":1",
    "1:",
    "1:1:",
    "e3",
    ".",
    "..",
    "-.",
    ".e1",
    "+",
    "1 2",
    "1,000",
    "1.2.3",
    "٣",
    "１２",
    "0_",
    "-_1",
    "+1_0",
]

# Documents (complete YAML texts).
DOCS = [
    ("empty", ""),
    ("comment", "# x\n"),
    ("scalar", "5\n"),
    ("null-doc", "~\n"),
    ("simple-map", "a: 1\nb: [1, 2.5, x]\nc: {d: true, e: null}\n"),
    ("order", "z: 1\na: 2\nm: 3\n"),
    ("duplicate-key", "a: 1\nb: 2\na: 3\n"),
    ("keys-equal-in-python", "1: a\ntrue: b\n1.0: c\n"),
    ("keys-nan", ".nan: 1\n.nan: 2\n"),
    ("keys-inf", ".inf: 1\n.Inf: 2\n"),
    ("keys-zero", "0: a\n-0: b\n0.0: c\n-0.0: d\n"),
    ("keys-date", "2026-01-01: a\n2026-01-01 00:00:00: b\n"),
    ("keys-null", "~: a\nnull: b\n'': c\n"),
    ("keys-str-vs-int", "1: a\n'1': b\n"),
    ("keys-big", "9007199254740993: a\n9007199254740992.0: b\n9007199254740992: c\n"),
    ("keys-multiple-types", "1: a\n'a': b\nnull: c\n2.5: d\ntrue: e\n"),
    ("key-unhashable-list", "? [1, 2]\n: x\n"),
    ("key-unhashable-map", "? {a: 1}\n: x\n"),
    ("merge-basic", "base: &b {a: 1, b: 2}\nx:\n  <<: *b\n  b: 3\n  c: 4\n"),
    ("merge-order", "base: &b {a: 1, b: 2}\nx:\n  c: 4\n  <<: *b\n"),
    ("merge-list", "a: &a {k: 1, x: 1}\nb: &b {k: 2, y: 2}\nx:\n  <<: [*a, *b]\n"),
    ("merge-two-keys", "a: &a {k: 1, x: 1}\nb: &b {k: 2, y: 2}\nx:\n  <<: *a\n  <<: *b\n"),
    ("merge-nested", "a: &a {k: 1}\nb: &b {<<: *a, j: 2}\nx:\n  <<: *b\n"),
    ("merge-string-key", "x:\n  '<<': 1\n"),
    ("merge-scalar", "x:\n  <<: 1\n"),
    ("merge-list-of-scalars", "x:\n  <<: [1, 2]\n"),
    ("merge-twice-same", "a: &a {k: 1}\nx:\n  <<: [*a, *a]\n"),
    ("value-key", "x:\n  =: 1\n"),
    ("value-scalar", "x: =\n"),
    ("anchors", "a: &x [1, 2]\nb: *x\nc: *x\n"),
    ("alias-undefined", "a: *nope\n"),
    ("anchor-recursive", "a: &x [*x]\n"),
    ("quoted-not-resolved", "a: '1'\nb: \"true\"\nc: '~'\nd: ''\ne: \"2026-01-01\"\n"),
    ("quoted-escapes", "a: \"x\\ty\\u00e4\\x41\\n\"\nb: 'it''s'\n"),
    ("multiline-plain", "a: one\n  two\n  three\nb: x\n"),
    ("literal-block", "a: |\n  one\n  two\nb: >\n  folded\n  text\n\n  para\n"),
    ("flow-nested", "a: {b: [1, {c: 2}], d: [ ]}\n"),
    ("flow-empty-values", "a: {b: , c: }\nd: [, 1]\n"),
    ("tag-str", "a: !!str 1\nb: !!str true\nc: !!str\n"),
    ("tag-int", "a: !!int '12'\nb: !!int 0x10\nc: !!int 010\n"),
    ("tag-int-bad", "a: !!int abc\n"),
    ("tag-float", "a: !!float 1\nb: !!float '1.5'\nc: !!float .inf\n"),
    ("tag-float-bad", "a: !!float x\n"),
    ("tag-bool", "a: !!bool yes\nb: !!bool 'off'\n"),
    ("tag-bool-bad", "a: !!bool maybe\n"),
    ("tag-null", "a: !!null ''\nb: !!null x\n"),
    ("tag-timestamp", "a: !!timestamp 2026-01-01\nb: !!timestamp '2026-01-01 10:00:00'\n"),
    ("tag-timestamp-bad", "a: !!timestamp nope\n"),
    ("tag-seq-map", "a: !!seq [1]\nb: !!map {x: 1}\n"),
    ("tag-binary", "a: !!binary aGVsbG8=\n"),
    ("tag-set", "a: !!set {x, y}\n"),
    ("tag-omap", "a: !!omap [x: 1, y: 2]\n"),
    ("tag-python", "a: !!python/object/apply:os.system ['echo hi']\n"),
    ("tag-unknown", "a: !foo 1\n"),
    ("tag-local-str", "a: !foo bar\n"),
    ("multi-document", "a: 1\n---\nb: 2\n"),
    ("explicit-document-start", "---\na: 1\n...\n"),
    ("tabs", "a:\n\t- 1\n"),
    ("bad-indent", "a:\n  b: 1\n c: 2\n"),
    ("unclosed-flow", "a: [1, 2\n"),
    ("unclosed-quote", "a: 'x\n"),
    ("bom", "\ufeffa: 1\n"),
    ("crlf", "a: 1\r\nb: 2\r\n"),
    ("unicode", "grün: ä\n日本: 語\n"),
    ("emoji", "a: 😀\n"),
    ("control-char", 'a: "\\x07"\n'),
    ("long-int", "a: 123456789012345678901234567890\n"),
    ("sequence-of-maps", "- id: a\n  v: 1\n- id: b\n  v: 2\n"),
    ("top-level-seq", "- 1\n- [2, 3]\n"),
    ("complex-keys-seq", "? - a\n  - b\n: 1\n"),
    ("yaml-directive", "%YAML 1.1\n---\na: 1\n"),
    ("yaml-directive-12", "%YAML 1.2\n---\na: 1\n"),
    ("set-of-keys-null-values", "a:\nb:\n"),
    ("question-null", "? a\n? b\n"),
    ("date-values", "d: 2026-07-08\nt: 2026-07-08 09:05:00\nz: 2026-07-08T09:05:00Z\n"),
    (
        "project-like",
        "schema: 1\nimported: 2026-10-14 08:30:00\nitems:\n- key: W-1\n  estimate: 5\n",
    ),
]


def encode(v: Any) -> Any:
    if v is None:
        return {"t": "null"}
    if isinstance(v, bool):
        return {"t": "bool", "v": v}
    if isinstance(v, int):
        return {"t": "int", "v": str(v)}
    if isinstance(v, float):
        if math.isnan(v):
            return {"t": "float", "v": "nan", "repr": "nan"}
        if math.isinf(v):
            return {"t": "float", "v": "inf" if v > 0 else "-inf", "repr": repr(v)}
        return {"t": "float", "v": repr(v), "repr": repr(v), "hex": v.hex()}
    if isinstance(v, str):
        return {"t": "str", "v": v}
    if isinstance(v, datetime.datetime):
        return {"t": "datetime", "v": v.isoformat(), "str": str(v)}
    if isinstance(v, datetime.date):
        return {"t": "date", "v": v.isoformat(), "str": str(v)}
    if isinstance(v, dict):
        return {"t": "map", "entries": [[encode(k), encode(x)] for k, x in v.items()]}
    if isinstance(v, list):
        return {"t": "seq", "items": [encode(x) for x in v]}
    if isinstance(v, bytes):
        return {"t": "bytes", "v": v.hex()}
    if isinstance(v, set):
        return {"t": "set", "items": [encode(x) for x in sorted(v, key=repr)]}
    return {"t": type(v).__name__, "v": repr(v)}


def load(text: str) -> dict[str, Any]:
    try:
        value = yaml.load(text, Loader=_YAML_LOADER)
    except Exception as err:
        return {"error": type(err).__name__}
    try:
        return {"value": encode(value)}
    except RecursionError:
        return {"error": "recursive"}


def generate(ctx) -> None:
    scalars = []
    for text in SCALARS:
        entry: dict[str, Any] = {"text": text}
        # As a mapping value: plain (resolved) and as a quoted string (not resolved).
        entry["plain"] = load(f"x: {text}\n") if text.strip() == text and "#" not in text else None
        try:
            node = yaml.compose(f"x: {text}\n", Loader=_YAML_LOADER)
            entry["tag"] = node.value[0][1].tag if text.strip() == text and text else None
        except yaml.YAMLError:
            entry["tag"] = None
        scalars.append(entry)
    docs = [{"name": n, "text": t, **load(t)} for n, t in DOCS]
    ctx.write("yamlx/cases.json", ctx.dump_json({"scalars": scalars, "docs": docs}))
