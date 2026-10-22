# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the value diff (``foresprint.diff.diff_values``), the excerpt of kept
values (``_slim``) and the key text, on pairs of YAML documents.

Written to ``golden/expected/diff/cases.json``. The Go port is ``go/internal/diff``."""

from __future__ import annotations

from typing import Any

import yaml

from foresprint import diff
from foresprint.yamlmerge import MISSING, keyed

PAIRS: list[tuple[str, str, str]] = [
    ("equal", "a: 1\nb: [1, 2]\n", "a: 1\nb: [1, 2]\n"),
    ("changed-scalar", "a: 1\nb: 2\n", "a: 1\nb: 3\n"),
    ("added-removed", "a: 1\nb: 2\n", "a: 1\nc: 3\n"),
    ("bool-vs-int", "a: true\nb: 1\n", "a: 1\nb: true\n"),
    ("int-vs-float", "a: 1\nb: 2.0\n", "a: 1.0\nb: 2\n"),
    ("nan", "a: .nan\n", "a: .nan\n"),
    ("null-and-empty-string", "a:\nb: ''\n", "a: ''\nb:\n"),
    ("nested", "a:\n  b:\n    c: 1\n    d: 2\n", "a:\n  b:\n    c: 1\n    d: 3\n    e: 4\n"),
    ("list-as-value", "a: [1, 2, 3]\n", "a: [1, 2, 4]\n"),
    (
        "keyed-list-changed",
        "people:\n- id: anna\n  fte: 1\n- id: ben\n  fte: 1\n",
        "people:\n- id: anna\n  fte: 0.5\n- id: ben\n  fte: 1\n",
    ),
    (
        "keyed-list-added-removed",
        "people:\n- id: anna\n  fte: 1\n- id: ben\n  fte: 1\n",
        "people:\n- id: ben\n  fte: 1\n- id: cem\n  fte: 1\n",
    ),
    (
        "keyed-list-reordered",
        "people:\n- id: anna\n- id: ben\n- id: cem\n",
        "people:\n- id: cem\n- id: anna\n- id: ben\n",
    ),
    (
        "keyed-list-reordered-and-changed",
        "people:\n- id: anna\n  fte: 1\n- id: ben\n",
        "people:\n- id: ben\n- id: anna\n  fte: 2\n",
    ),
    ("keyed-list-numeric-ids", "x:\n- id: 1\n- id: 2\n", "x:\n- id: 2\n- id: 1\n"),
    ("keyed-list-duplicate-ids", "x:\n- id: a\n- id: a\n", "x:\n- id: a\n- id: b\n"),
    ("keyed-list-without-id", "x:\n- id: a\n- name: b\n", "x:\n- id: a\n- name: c\n"),
    ("empty-list-to-keyed", "x: []\n", "x:\n- id: a\n  v: 1\n"),
    ("keyed-to-empty-list", "x:\n- id: a\n  v: 1\n", "x: []\n"),
    ("empty-list-to-plain", "x: []\n", "x: [1]\n"),
    ("list-to-mapping", "x: [1]\n", "x: {a: 1}\n"),
    ("mapping-to-scalar", "x: {a: 1}\n", "x: 3\n"),
    ("prognoses-are-one-value", "p:\n- at: a\n  v: 1\n", "p:\n- at: a\n  v: 2\n"),
    ("dates", "d: 2026-01-01\n", "d: 2026-01-02\n"),
    ("timestamps", "d: 2026-01-01 10:00:00\n", "d: 2026-01-01 10:00:01\n"),
    ("key-spellings", "null: 1\ntrue: 2\n3: 4\n1.5: 5\n", "null: 2\ntrue: 3\n3: 5\n1.5: 6\n"),
    ("top-level-scalar", "1\n", "2\n"),
    ("top-level-list", "[1, 2]\n", "[1, 3]\n"),
    ("top-level-keyed", "- id: a\n- id: b\n", "- id: b\n- id: a\n"),
    ("whole-file-new", "", "a: 1\n"),
    ("unicode", "name: Grün\n", "name: Grün ä\n"),
    ("long-values", "a: " + "x" * 1500 + "\n", "a: " + "y" * 1500 + "\n"),
    (
        "many-items",
        "a: [" + ",".join(["1"] * 1200) + "]\n",
        "a: [" + ",".join(["2"] * 1200) + "]\n",
    ),
    (
        "deep",
        "a: " + "[" * 12 + "1" + "]" * 12 + "\n",
        "a: " + "[" * 12 + "2" + "]" * 12 + "\n",
    ),
    ("path-with-dot", "a.b: 1\n", "a.b: 2\n"),
]


def value(v: Any) -> Any:
    return {"missing": True} if v is MISSING else v


def slim(v: Any) -> Any:
    return diff._slim(v, [diff._SLIM_NODES])


def generate(ctx) -> None:
    cases = []
    for name, old_text, new_text in PAIRS:
        old = yaml.safe_load(old_text) if old_text else MISSING
        new = yaml.safe_load(new_text) if new_text else MISSING
        if old is MISSING or new is MISSING:
            changes = [diff.ValueChange((), old, new)]
        else:
            changes = diff.diff_values(old, new)
        cases.append(
            {
                "name": name,
                "old": old_text,
                "new": new_text,
                "changes": [
                    {
                        "path": list(c.path),
                        "kind": c.kind,
                        "label": c.label,
                        "old": value(c.old),
                        "new": value(c.new),
                        "old_slim": value(slim(c.old)) if c.old is not MISSING else None,
                        "new_slim": value(slim(c.new)) if c.new is not MISSING else None,
                    }
                    for c in changes
                ],
            }
        )
    keyed_cases = [
        {"text": t, "keyed": None if (k := keyed(yaml.safe_load(t))) is None else list(k)}
        for t in (
            "- id: a\n- id: b\n",
            "- id: 1\n- id: '1'\n",
            "- id: 1\n- id: 2\n",
            "[]",
            "{}",
            "- id: a\n- b\n",
            "- {id: a}\n- {id: a}\n",
            "- id:\n- id: x\n",
        )
    ]
    ctx.write(
        "diff/cases.json",
        ctx.dump_json(ctx.jsonable({"cases": cases, "keyed": keyed_cases})),
    )
