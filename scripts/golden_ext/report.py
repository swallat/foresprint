# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the Markdown report (``foresprint.report``): ``render`` for every case
and a few history lengths, plus the small helpers with their corners (number formats, notes).

Written to ``golden/expected/report/``. The Go port is ``go/internal/report``."""

from __future__ import annotations

from foresprint import report
from foresprint.forecast import build_forecast

NUMBERS = [None, 0, 0.0, -0.0, 1, 1.5, 2.5, 0.05, 0.005, 0.045, 1.005, 12345.678, -3.25, 1e-9, 1e15]
SAMPLES = [(1, 3, 5), (2, 5, 5), (0, 5, 5), (4, 5, 12), (5, 5, 5), (3, 8, 2)]


def generate(ctx) -> None:
    for case in ctx.resolved:
        data = ctx.load(case)
        fc = build_forecast(data, case.today)
        for history in (10, 3, 0):
            ctx.write(f"report/{case.name}-h{history}.md", report.render(fc, history))
    ctx.write(
        "report/helpers.json",
        ctx.dump_json(
            ctx.jsonable(
                {
                    "fmt": [
                        {"value": v, "digits": d, "suffix": s, "text": report.fmt(v, d, s)}
                        for v in NUMBERS
                        for d, s in ((0, ""), (1, ""), (2, ""), (1, " PT"))
                    ],
                    "fmt_capacity": [
                        {"value": v, "digits": d, "text": report.fmt_capacity(v, d)}
                        for v in NUMBERS
                        for d in (0, 1, 2)
                    ],
                    "pct": [{"value": v, "text": report.pct(v)} for v in NUMBERS],
                    "window_hint": [
                        {
                            "window": w,
                            "samples": s,
                            "available": a,
                            "simulation": sim,
                            "text": report.window_hint(w, s, a, sim),
                        }
                        for s, w, a in SAMPLES
                        for sim in (False, True)
                    ],
                    "completion_note": [
                        {"samples": n, "text": report.completion_note(n)} for n in range(0, 9)
                    ],
                    "absence_derived_remedy": [
                        {"window": w, "text": report.absence_derived_remedy(w)} for w in (1, 4, 5)
                    ],
                    "absence_derived_cli_remedy": [
                        {"window": w, "text": report.absence_derived_cli_remedy(w, "team-a")}
                        for w in (1, 4, 5)
                    ],
                    "sprint_text": [
                        {"id": i, "text": report.sprint_text(i)} for i in ("2026.1", "7", "x y")
                    ],
                }
            )
        ),
    )
