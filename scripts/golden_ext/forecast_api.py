# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the lookups around the forecast (``foresprint.forecast``,
``foresprint.analysis``, ``foresprint.calendar``) for the Go port: current, upcoming and
history entries, the default sprint per purpose, sprint lookups, the Planning inputs, freezing the
plan, the buffer hint and the error texts of the calendar."""

from __future__ import annotations

import copy
from datetime import date

from foresprint import analysis, forecast
from foresprint import calendar as cal
from foresprint.forecast import build_forecast
from foresprint.model import Numbering, Planning, Sprint, Team
from foresprint.storage import DataError


def _ids(entries) -> list[str]:
    return [e.sprint.id for e in entries]


def _error(call) -> str | None:
    try:
        call()
    except DataError as e:
        return str(e)
    return None


def generate(ctx) -> None:
    for case in ctx.resolved:
        data = ctx.load(case)
        fc = build_forecast(data, case.today)
        today = case.today
        last = fc.entries[-1].sprint
        probes = [e.sprint.id for e in fc.entries[:: max(1, len(fc.entries) // 6)]]
        probes += [last.id, "no-such-sprint", "2099.1"]
        out: dict = {
            "current": fc.current.sprint.id if fc.current else None,
            "upcoming": _ids(fc.upcoming()),
            "history": _ids(fc.history()),
            "history_0": _ids(fc.history(0)),
            "history_3": _ids(fc.history(3)),
            "defaults": {
                p: (e.sprint.id if (e := fc.default_entry(p)) else None)
                for p in ("current", "planning", "next", "review")
            },
            "find": {
                s: (r.id if (r := forecast.find_sprint(data, s, 8)) else None) for s in probes
            },
            "lookup": {
                s: (r.id if (r := forecast.lookup_sprint(fc, s, 8)) else None) for s in probes
            },
            "absences_known": {e.sprint.id: forecast.absences_known(e.sprint) for e in fc.entries},
            "available_count": analysis.available_count(fc),
            "few_samples": analysis.few_samples(fc),
            "sample_count": analysis.sample_count(fc),
            "buffer": {
                "sufficient_data": analysis.buffer_hint(fc).sufficient_data,
                "buffer_too_small": analysis.buffer_hint(fc).buffer_too_small,
            },
            "freeze": [],
            "refreeze": [],
        }
        for e in fc.entries:
            for preset in (None, 9.9):
                for refreeze in (False, True):
                    sprint = copy.deepcopy(e.sprint)
                    sprint.forecast_plan = preset
                    forecast.freeze_plan(sprint, e, today, refreeze)
                    out["freeze"].append(
                        {
                            "sprint": sprint.id,
                            "preset": preset,
                            "refreeze": refreeze,
                            "result": sprint.forecast_plan,
                        }
                    )
                sprint = copy.deepcopy(e.sprint)
                sprint.forecast_plan = preset
                offer = forecast.refreeze_offer(sprint, e)
                out["refreeze"].append(
                    {"sprint": sprint.id, "preset": preset, "offer": list(offer) if offer else None}
                )
        out["horizon_forecast_entries"] = len(analysis.horizon_forecast(data, today, 6).entries)
        ctx.write(f"forecast_api/{case.name}.json", ctx.dump_json(ctx.jsonable(out)))

    plannings = [
        (None, Planning(5, 10, [1.0])),
        (20.0, Planning(5, 10, [])),
        (None, Planning(0, 0, [])),
        (None, None),
        (None, Planning(0, 0, [2.0])),
        (12.0, None),
        (None, Planning(0, 7.5, [])),
    ]
    applied = []
    for commitment, planning in plannings:
        sprint = Sprint(id="x", start=date(2026, 1, 1), end=date(2026, 1, 15))
        prefilled = forecast.apply_planning(sprint, commitment, copy.deepcopy(planning))
        applied.append(
            {
                "commitment": commitment,
                "planning": planning,
                "prefilled": prefilled,
                "sprint_commitment": sprint.commitment,
                "sprint_planning": sprint.planning,
            }
        )

    team = Team(key="no-first", name="x")
    errors = {
        "no_first_sprint": _error(lambda: cal.following_sprint(team, None)),
        "sequential_22b": _error(
            lambda: cal.next_id("22b", date(2026, 3, 1), Numbering.SEQUENTIAL)
        ),
        "sequential_x": _error(lambda: cal.next_id("x", date(2026, 3, 1), Numbering.SEQUENTIAL)),
        "yearly_counter": _error(lambda: cal.next_id("2026.x", date(2026, 3, 1), Numbering.YEARLY)),
        "yearly_form": cal.expected_id_form(Numbering.YEARLY),
        "sequential_form": cal.expected_id_form(Numbering.SEQUENTIAL),
    }
    ctx.write(
        "forecast_api/misc.json",
        ctx.dump_json(ctx.jsonable({"apply_planning": applied, "errors": errors})),
    )
