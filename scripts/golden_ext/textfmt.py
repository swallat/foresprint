# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the text helpers the calculation texts use (``report.fmt``,
``fmt_capacity``, ``pct``, ``git.md_code``, ``git.blank_controls``) in both languages, and the
note texts that depend on them."""

from __future__ import annotations

from datetime import date

from foresprint import formulas, i18n
from foresprint.calendar import day_label
from foresprint.capacity import AbsenceHistory
from foresprint.git import blank_controls, md_code
from foresprint.report import (
    absence_derived_hint,
    absence_derived_note,
    fmt,
    fmt_capacity,
    pct,
)

NUMBERS = [
    0,
    0.5,
    1.5,
    2.5,
    25.25,
    25.75,
    1234.5,
    1234567.891,
    0.049999999,
    -1.5,
    -0.0,
    67,
    0.8,
    0.123456,
    999999.5,
    30.4375,
    100,
]
TEXTS = [
    "",
    "plain",
    " lead",
    "trail ",
    "`",
    "a`b",
    "a``b`c",
    "``",
    "x\ny",
    "tab\there",
    "‮evil‬",
    "zero‍width",
    "emoji \U0001f468‍\U0001f469",
    "line sep",
    "para sep",
    "Jörg Müller",
    "\x00nul\x7f",
    "؜arabic",
    " ",
    "`tick` and ``double``",
]


def generate(ctx) -> None:
    out: dict = {"texts": [], "numbers": []}
    for text in TEXTS:
        out["texts"].append({"text": text, "md_code": md_code(text), "blank": blank_controls(text)})
    for lang in ("en", "de"):
        i18n.set_language(lang)
        rows = []
        for x in NUMBERS:
            row = {"value": x, "pct": pct(x), "none": fmt(None)}
            for digits in (0, 1, 2, 3, 4):
                row[f"fmt{digits}"] = fmt(x, digits)
                row[f"cap{digits}"] = fmt_capacity(x, digits)
            rows.append(row)
        history = AbsenceHistory(rate=0.1, sprints=["a"], rates=[0.1], derived=["2026.20"])
        history2 = AbsenceHistory(rate=0.1, sprints=["a"], rates=[0.1], derived=["2026.20", "x`y"])
        out["numbers"].append(
            {
                "lang": lang,
                "rows": rows,
                "day_label": day_label(date(2026, 10, 28)),
                "fte_note": formulas.fte_change_note(["Ben", "`Cem`"]),
                "notes": {
                    "one": absence_derived_note(history),
                    "one_detailed": absence_derived_note(history, detailed=True, window=4),
                    "two_plain": absence_derived_note(history2, code=False, window=6),
                    "two_detailed": absence_derived_note(history2, detailed=True, window=6),
                    "none": absence_derived_note(AbsenceHistory(None, [], [])),
                    "hint_one": absence_derived_hint(history),
                    "hint_two": absence_derived_hint(history2),
                    "hint_none": absence_derived_hint(None),
                },
            }
        )
    i18n.set_language("en")
    ctx.write("textfmt/cases.json", ctx.dump_json(ctx.jsonable(out)))
