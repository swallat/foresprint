# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the calculation path (``foresprint.formulas``) for the Go port: the
steps, the plain and the structured explanation of every sprint of every case, in English."""

from __future__ import annotations

from foresprint import formulas
from foresprint.forecast import build_forecast


def generate(ctx) -> None:
    ctx.write(
        "formulas/general.json",
        ctx.dump_json({key: formulas.general(key) for key in formulas.GENERAL}),
    )
    for case in ctx.resolved:
        data = ctx.load(case)
        fc = build_forecast(data, case.today)
        entries = []
        for e in fc.entries:
            entries.append(
                {
                    "sprint": e.sprint.id,
                    "steps": ctx.jsonable(formulas.steps(fc, e, code=False, note=True)),
                    "steps_code_no_note": ctx.jsonable(
                        formulas.steps(fc, e, code=True, note=False)
                    ),
                    "plain": formulas.plain_explanation(fc, e, note=True),
                    "plain_no_note": formulas.plain_explanation(fc, e, note=False),
                    "structured": ctx.jsonable(formulas.structured_explanation(fc, e, note=True)),
                    "structured_no_note": ctx.jsonable(
                        formulas.structured_explanation(fc, e, note=False)
                    ),
                }
            )
        ctx.write(f"formulas/{case.name}.json", ctx.dump_json({"entries": entries}))
