# SPDX-License-Identifier: EUPL-1.2
"""German golden references of the calculation texts, for the Go port. The Go tests translate
with the complete catalog of ``internal/i18n``."""

from __future__ import annotations

from datetime import date

from foresprint import calendar as cal
from foresprint import engine, formulas, i18n
from foresprint.capacity import AbsenceHistory
from foresprint.forecast import build_forecast
from foresprint.model import Numbering, Team
from foresprint.report import absence_derived_hint, absence_derived_note
from foresprint.storage import DataError

GERMAN_CASES = ("demo", "people-days", "thin", "trend-classic")


def generate(ctx) -> None:
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
    finally:
        i18n.set_language("en")
