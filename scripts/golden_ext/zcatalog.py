# SPDX-License-Identifier: EUPL-1.2
"""German golden references of the calculation texts, and the part of the German catalog they
use (``catalog/de.json``: English source text to German text), for the Go port.

The catalog is recorded, not copied: every text the calculation texts ask the catalog for while
this module runs through all cases is kept. The Go test translates with exactly this part, so a
source text that differs by one character between Python and Go shows up as an untranslated
text. The complete catalog belongs to the step "texts" of the port."""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from foresprint import calendar as cal
from foresprint import engine, formulas, i18n, locale_de
from foresprint.capacity import AbsenceHistory
from foresprint.forecast import build_forecast
from foresprint.model import Numbering, Team
from foresprint.report import absence_derived_hint, absence_derived_note
from foresprint.storage import DataError

GERMAN_CASES = ("demo", "people-days", "thin", "trend-classic")


class _Recorder(dict):
    used: ClassVar[set[str]] = set()

    def get(self, key, default=None):
        _Recorder.used.add(key)
        return super().get(key, default)


def generate(ctx) -> None:
    original = locale_de.DE
    locale_de.DE = _Recorder(original)
    i18n.set_language("de")
    try:
        for case in ctx.resolved:
            data = ctx.load(case)
            fc = build_forecast(data, case.today)
            entries = []
            for e in fc.entries:
                entry = {
                    "sprint": e.sprint.id,
                    "steps": ctx.jsonable(formulas.steps(fc, e, code=False, note=True)),
                    "plain": formulas.plain_explanation(fc, e, note=True),
                    "structured": ctx.jsonable(formulas.structured_explanation(fc, e, note=True)),
                }
                entries.append(entry)
            if case.name in GERMAN_CASES:
                ctx.write(f"formulas-de/{case.name}.json", ctx.dump_json({"entries": entries}))
        for key in formulas.GENERAL:
            formulas.general(key)
        ctx.write(
            "formulas-de/general.json",
            ctx.dump_json({key: formulas.general(key) for key in formulas.GENERAL}),
        )
        # Texts of the helpers and the calendar.
        history = AbsenceHistory(rate=0.1, sprints=["a"], rates=[0.1], derived=["2026.20"])
        history2 = AbsenceHistory(rate=0.1, sprints=["a"], rates=[0.1], derived=["2026.20", "x"])
        for h in (history, history2):
            absence_derived_hint(h)
            absence_derived_note(h, detailed=True, window=4)
            absence_derived_note(h, code=False)
        formulas.fte_change_note(["Ben"])
        errors = {}
        for name, call in {
            "no_first": lambda: cal.following_sprint(Team(key="t", name="t"), None),
            "sequential": lambda: cal.next_id("22b", date(2026, 3, 1), Numbering.SEQUENTIAL),
            "yearly": lambda: cal.next_id("x", date(2026, 3, 1), Numbering.SEQUENTIAL),
        }.items():
            try:
                call()
            except DataError as ex:
                errors[name] = str(ex)
        try:
            engine.parse_trend_mode("quadratic")
        except ValueError as ex:
            errors["trend_mode"] = str(ex)
        errors["yearly_form"] = cal.expected_id_form(Numbering.YEARLY)
        errors["sequential_form"] = cal.expected_id_form(Numbering.SEQUENTIAL)
        errors["day_label"] = cal.day_label(date(2026, 10, 28))
        ctx.write("formulas-de/calendar.json", ctx.dump_json(errors))
        used = {k: original[k] for k in sorted(_Recorder.used) if k in original}
        ctx.write("catalog/de.json", ctx.dump_json(used))
    finally:
        locale_de.DE = original
        i18n.set_language("en")
