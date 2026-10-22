# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the ticket import (``foresprint.ticket_import``) and the label write-back
(``foresprint.label_writeback``), below ``expected/ticketimport/``.

Every import scenario is a file ``import/<name>.json`` with all inputs (tracker settings,
projects, the tickets of the last import, the preplan, the raw tickets, ``today`` and a table of
the sprints the calendar knows with their end) and the result of ``plan_import``. The sprint
table stands in for the forecast: ``resolve_sprint`` and ``sprint_ended`` only ask which sprint
ids exist and when they end.

``functions.json`` has the small functions on their own (``is_refined``, ``assign_project``,
``resolve_sprint``, ``find_cycles``), ``labels.json`` the label write-back (plan and apply).
All data is invented.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from foresprint.calendar import following_sprint
from foresprint.forecast import build_forecast
from foresprint.label_writeback import apply_label_writes, plan_label_writes
from foresprint.model import (
    Earmark,
    EstimateSource,
    ManualEstimate,
    PlanningUses,
    Preplan,
    Project,
    Rule,
    Ticket,
    TrackerFields,
    TrackerSettings,
)
from foresprint.sources import RawTicket, SourceError
from foresprint.ticket_import import assign_project, is_refined, plan_import, resolve_sprint
from foresprint.validate import find_cycles

TODAY = date(2026, 10, 15)  # demo data: current sprint 2026.21, 2026.22 recorded


def leaf(source: str, *values: str, contains: bool = False) -> Rule:
    return Rule(source=source, values=list(values), contains=contains)


def tracker(**overrides: Any) -> TrackerSettings:
    values: dict[str, Any] = {
        "kind": "jira",
        "fields": TrackerFields(estimate="Story Points", remaining="Remaining", epic="Epic Link"),
        "refined_label": "Refined",
        "refined_also_if": Rule(
            op="any",
            children=[
                leaf("in_sprint", "true"),
                Rule(op="none", children=[leaf("status", "To Do")]),
            ],
        ),
        "sprint_names": {"Sprint 22": "2026.22", "Sprint 23": "2026.23"},
    }
    values.update(overrides)
    return TrackerSettings(**values)


def project(id: str, **match: list[str]) -> Project:
    rule = Rule(
        op="any",
        short=True,
        children=[Rule(source=source, values=values) for source, values in match.items()],
    )
    return Project(id=id, name=id, product="webshop", target=date(2027, 3, 31), match=rule)


def projects() -> list[Project]:
    return [
        project("payment", epic=["ABC-100"], label=["payment"]),
        project("migration", component=["Database"], label=["migration"]),
    ]


def raw(key: str = "ABC-1", **overrides: Any) -> RawTicket:
    values: dict[str, Any] = {
        "title": f"Title {key}",
        "status": "To Do",
        "issue_type": "Story",
        "estimate": 5.0,
    }
    values.update(overrides)
    return RawTicket(key=key, **values)


def old(key: str = "ABC-1", **overrides: Any) -> Ticket:
    values: dict[str, Any] = {"title": f"Title {key}", "estimate": 5.0, "status": "To Do"}
    values.update(overrides)
    return Ticket(key=key, **values)


def sprint_table(data: Any, fc: Any) -> dict[str, str]:
    """Id and end of every sprint ``lookup_sprint`` finds: recorded, in the forecast, and the
    next 52 from the calendar (recorded wins over the forecast over the calendar)."""
    table: dict[str, str] = {s.id: s.end.isoformat() for s in data.sprints}
    for entry in fc.entries:
        table.setdefault(entry.sprint.id, entry.sprint.end.isoformat())
    last = data.sprints[-1] if data.sprints else None
    for _ in range(52):
        last = following_sprint(data.team, last)
        table.setdefault(last.id, last.end.isoformat())
    return table


def generate(ctx: Any) -> None:
    demo = next(c for c in ctx.resolved if c.name == "demo")
    base = ctx.load(demo)
    scenarios = build_scenarios()
    names = []
    for name, sc in scenarios.items():
        names.append(name)
        data = copy.deepcopy(base)
        data.team.tracker = sc["tracker"]
        data.projects = sc.get("projects", projects())
        data.tickets = sc.get("tickets", [])
        data.tickets_source = sc.get("tickets_source")
        data.preplan = sc.get("preplan", Preplan())
        today = sc.get("today", TODAY)
        fc = build_forecast(data, today)
        source = sc.get("source")
        adopt = sc.get("adopt_labels", True)
        plan = plan_import(data, fc, sc["raws"], today, source, adopt)
        record = {
            "today": today,
            "tracker": sc["tracker"],
            "projects": data.projects,
            "tickets": data.tickets,
            "tickets_source": data.tickets_source,
            "preplan": data.preplan,
            "sprints": sprint_table(data, fc),
            "raws": sc["raws"],
            "source": source,
            "adopt_labels": adopt,
            "plan": {
                "tickets": plan.tickets,
                "preplan": plan.preplan,
                "preplan_changed": plan.preplan_changed,
                "changes": plan.changes,
                "warnings": plan.warnings,
                "source": plan.source,
                "unchanged": plan.unchanged(data),
            },
        }
        ctx.write(f"ticketimport/import/{name}.json", ctx.dump_json(ctx.jsonable(record)))
    ctx.write("ticketimport/import/index.json", ctx.dump_json(names))
    functions(ctx, base)
    labels(ctx)


def build_scenarios() -> dict[str, dict[str, Any]]:
    s: dict[str, dict[str, Any]] = {}

    s["fresh-mixed"] = {
        "tracker": tracker(),
        "raws": [
            raw("A-1", labels=["Refined", "payment"], epic="ABC-100", remaining=3.0),
            raw("A-2", labels=["Refined"], estimate=None),
            raw("A-3", status="In Progress", sprint_name="Sprint 22", labels=["x"]),
            raw("A-4", sprint_name="Sprint 99", components=["Database"]),
            raw("A-5", resolved=True, status="Done", labels=["payment"], sprint_name="Sprint 22"),
            raw("A-6", labels=["payment", "migration"], epic="ABC-100"),
            raw("A-7", epic="ABC-777", labels=["payment"]),
            raw("A-8", estimate=None, remaining=None, status="Ready"),
            raw("A-9", sprint_name="2026.21", status="In Progress"),
            raw("A-10", blocked_by=["A-11"], labels=["payment"]),
            raw("A-11", blocked_by=["A-10"], labels=["payment"]),
            raw("A-1", title="Duplicate wins", labels=["payment"]),
        ],
        "source": "export.csv",
    }
    s["closed-sprint-carry-over"] = {
        "tracker": tracker(),
        "raws": [
            raw("B-1", sprint_name="2026.20", status="In Progress", remaining=2.0),
            raw("B-2", sprint_name="Sprint 22", status="In Progress", remaining=2.0),
            raw("B-3", sprint_name="2026.21", status="To Do"),
        ],
        "today": date(2026, 11, 2),
    }
    s["planning-uses-estimate"] = {
        "tracker": tracker(planning_uses=PlanningUses.ESTIMATE),
        "raws": [
            raw("C-1", estimate=8.0, remaining=2.0, labels=["Refined"]),
            raw("C-2", remaining=1.0),
        ],
    }
    s["without-refined-label-or-rule"] = {
        "tracker": tracker(refined_label=None, refined_also_if=None),
        "raws": [raw("D-1", labels=["Refined"]), raw("D-2", status="Ready")],
    }
    s["match-order"] = {
        "tracker": tracker(project_match_order=["label", "epic", "component"]),
        "raws": [
            raw("E-1", labels=["payment"], epic="ABC-100", components=["Database"]),
            raw("E-2", labels=["migration"], epic="ABC-100"),
            raw("E-3", components=["Database"], labels=["payment"]),
        ],
    }
    s["rules-with-extra-fields"] = {
        "tracker": tracker(rule_fields={"team": "Team"}),
        "projects": [
            Project(
                id="alpha", name="Alpha", match=Rule(op="leaf", source="team", values=["Alpha"])
            ),
            Project(
                id="beta",
                name="Beta",
                match=Rule(
                    op="all",
                    children=[leaf("team", "Beta"), leaf("label", "urgent", contains=True)],
                ),
            ),
            Project(id="idle", name="No rule"),
        ],
        "raws": [
            raw("F-1", extra={"team": ["Alpha"]}),
            raw("F-2", extra={"team": ["Beta"]}, labels=["very-urgent-fix"]),
            raw("F-3", extra={"team": ["Beta"]}),
            raw("F-4", priority="High", status="Open"),
        ],
    }

    previous = [
        old("G-1", estimate=5.0, remaining=3.0),
        old("G-2", estimate=3.0),
        old("G-3", estimate=2.0),
        old("G-4", estimate=2.0, in_sprint="2026.22", sprint_name="Sprint 22"),
        old("G-5", estimate=1.0, labels=["planned_for_2026.24"]),
        old("G-6", estimate=1.0),
        old("G-7", estimate=1.0),
        old("G-8", estimate=1.0, done=True),
    ]
    earmarks = Preplan(
        earmarks=[
            Earmark("G-1", "2026.23"),
            Earmark("G-2", "2026.24", note="keep"),
            Earmark("G-3", "2026.20"),  # sprint is over
            Earmark("G-4", "2026.24"),  # real sprint wins
            Earmark("G-5", "2026.25"),
            Earmark("G-6", "2026.21"),  # missing, current sprint
            Earmark("G-7", "2026.19"),  # missing, over
            Earmark("G-9", "2026.19"),  # not in any import, over
            Earmark("G-10", "2026.25"),  # not in any import, future
        ],
        estimates=[ManualEstimate("G-6", 4.0), ManualEstimate("G-11", 2.0)],
    )
    s["reconcile"] = {
        "tracker": tracker(),
        "tickets": previous,
        "tickets_source": "export.csv",
        "preplan": earmarks,
        "source": "export.csv",
        "raws": [
            raw("G-1", estimate=5.0, remaining=2.0),  # remaining changed
            raw("G-2", estimate=4.0, remaining=None),  # estimate changed
            raw("G-3", estimate=2.0),
            raw("G-4", estimate=2.0, sprint_name="Sprint 22"),
            raw("G-5", estimate=1.0, resolved=True),  # now done: earmark goes
            raw("G-8", estimate=1.0, resolved=True),  # was done already
            raw("G-12", estimate=1.0),  # new
        ],
    }
    s["reconcile-unchanged"] = {
        "tracker": tracker(),
        "tickets": [old("H-1", project="payment", estimate_source=EstimateSource.ROUGH)],
        "tickets_source": "export.csv",
        "source": "export.csv",
        "raws": [raw("H-1", labels=["payment"], epic="ABC-100")],
    }
    s["reconcile-source-changes"] = {
        "tracker": tracker(),
        "tickets": [old("H-1", project="payment", estimate_source=EstimateSource.ROUGH)],
        "tickets_source": "export.csv",
        "source": "jira jira.example.org",
        "raws": [raw("H-1", labels=["payment"], epic="ABC-100")],
    }
    s["earmark-and-estimate-of-missing-tickets"] = {
        "tracker": tracker(),
        "tickets": [old("I-1"), old("I-2"), old("I-3")],
        "preplan": Preplan(
            earmarks=[Earmark("I-1", "2026.24")], estimates=[ManualEstimate("I-2", 3.0)]
        ),
        "raws": [raw("I-3")],
    }

    label_tracker = tracker(write_labels=True)
    s["labels-adopted"] = {
        "tracker": label_tracker,
        "tickets": [old("L-5", labels=["planned_for_2026.23"])],
        "raws": [
            raw("L-1", labels=["planned_for_2026.23"]),
            raw("L-2", labels=["planned_for_2026.23", "planned_for_2026.24"]),
            raw("L-3", labels=["planned_for_2026.20"]),
            raw("L-4", labels=["planned_for_2026.99"]),
            raw("L-5", labels=["planned_for_2026.23"]),  # known label: no news
            raw("L-6", labels=["planned_for_2026.23"], resolved=True),
            raw("L-7", labels=["planned_for_2026.23"], sprint_name="Sprint 22"),
            raw("L-8", labels=["planned_for_2026.21"]),  # current sprint is open
            raw("L-9", labels=["planned_for_2026.24", "planned_for_2026.24"]),
        ],
    }
    s["labels-earmark-wins"] = {
        "tracker": label_tracker,
        "preplan": Preplan(earmarks=[Earmark("M-1", "2026.24")]),
        "raws": [raw("M-1", labels=["planned_for_2026.23"])],
    }
    s["labels-ignored-without-setting"] = {
        "tracker": tracker(),
        "raws": [raw("N-1", labels=["planned_for_2026.23"])],
    }
    s["labels-not-adopted-when-asked"] = {
        "tracker": label_tracker,
        "adopt_labels": False,
        "raws": [raw("N-1", labels=["planned_for_2026.23"])],
    }
    s["empty-import"] = {
        "tracker": tracker(),
        "tickets": [old("O-1")],
        "preplan": Preplan(earmarks=[Earmark("O-1", "2026.19")]),
        "raws": [],
    }
    return s


def functions(ctx: Any, base: Any) -> None:
    refined = []
    trackers = {
        "label-and-rule": tracker(),
        "label-only": tracker(refined_also_if=None),
        "rule-only": tracker(refined_label=None),
        "none": tracker(refined_label=None, refined_also_if=None),
        "other-label": tracker(refined_label="Ready", refined_also_if=None),
    }
    facts_list: list[dict[str, list[str]]] = [
        {},
        {"label": ["Refined"]},
        {"label": ["Refined", "x"], "status": ["To Do"]},
        {"label": ["x"], "status": ["In Progress"]},
        {"label": ["x"], "status": ["To Do"], "in_sprint": ["false"]},
        {"label": ["x"], "status": ["To Do"], "in_sprint": ["true", "2026.22"]},
        {"label": ["refined"]},
        {"status": ["Ready"], "in_sprint": ["false"]},
    ]
    for tname, tr in trackers.items():
        for facts in facts_list:
            for estimate in (None, 0.0, 5.0):
                refined.append(
                    {
                        "tracker": tname,
                        "facts": facts,
                        "estimate": estimate,
                        "ok": list(is_refined(facts, estimate, tr)),
                    }
                )
    orders = [["epic", "component", "label"], ["label", "epic"], [], ["component"]]
    plist = [
        *projects(),
        project("dupe", epic=["ABC-100"]),
        Project(id="norule", name="No rule"),
        Project(id="contains", name="C", match=leaf("label", "pay", contains=True)),
    ]
    assignments = []
    fact_sets: list[dict[str, list[str]]] = [
        {},
        {"epic": ["ABC-100"]},
        {"epic": ["ABC-100"], "label": ["payment"]},
        {"label": ["payment"]},
        {"label": ["migration"], "component": ["Database"]},
        {"label": ["migration", "payment"]},
        {"component": ["Database"], "epic": ["ABC-100"]},
        {"label": ["prepayment"]},
        {"epic": ["ZZZ"]},
    ]
    for order in orders:
        for subset_name, subset in (("all", plist), ("first-two", plist[:2]), ("none", [])):
            for facts in fact_sets:
                found, candidates = assign_project(facts, subset, order)
                assignments.append(
                    {
                        "order": order,
                        "projects": subset_name,
                        "facts": facts,
                        "ok": [found, candidates],
                    }
                )
    # resolve_sprint needs data and a forecast: use the demo team
    data = copy.deepcopy(base)
    data.team.tracker = tracker()
    fc = build_forecast(data, TODAY)
    names = [
        None,
        "",
        "2026.21",
        "2026.22",
        "2026.30",
        "2027.99",
        "Sprint 22",
        "Sprint 23",
        "Sprint 99",
        "sprint 22",
    ]
    resolved = [{"name": n, "ok": resolve_sprint(n, data, fc)} for n in names]
    cycles_in: list[list[tuple[str, list[str]]]] = [
        [],
        [("A", [])],
        [("A", ["A"])],
        [("A", ["B"]), ("B", ["A"])],
        [("B", ["C"]), ("C", ["A"]), ("A", ["B"])],
        [("A", ["B", "X"]), ("B", [])],
        [("A", ["B"]), ("B", ["C"]), ("C", ["B", "A"]), ("D", ["A"])],
        [("X", ["Y"]), ("Y", ["X"]), ("P", ["Q"]), ("Q", ["P"])],
        [("A", ["B"]), ("B", ["A", "C"]), ("C", ["B"])],
    ]
    cycles = []
    for spec in cycles_in:
        tickets = [Ticket(key=k, depends_on=list(d)) for k, d in spec]
        cycles.append({"tickets": [[k, d] for k, d in spec], "ok": find_cycles(tickets)})
    ctx.write(
        "ticketimport/functions.json",
        ctx.dump_json(
            ctx.jsonable(
                {
                    "trackers": {
                        n: {"label": t.refined_label, "rule": t.refined_also_if}
                        for n, t in trackers.items()
                    },
                    "is_refined": refined,
                    "projects": plist,
                    "assign_project": assignments,
                    "sprints": sprint_table(data, fc),
                    "resolve_sprint": resolved,
                    "find_cycles": cycles,
                }
            )
        ),
    )


class _Recorder:
    """A stand-in for the Jira source: records the calls and fails on request."""

    def __init__(self, fail_at: int | None = None) -> None:
        self.calls: list[list[Any]] = []
        self.fail_at = fail_at

    def set_labels(self, key: str, add: list[str], remove: list[str]) -> None:
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise SourceError("Jira refuses the write (403)")
        self.calls.append([key, add, remove])


def labels(ctx: Any) -> None:
    def tk(key: str, **kw: Any) -> Ticket:
        return old(key, **kw)

    cases: dict[str, tuple[list[Ticket], Preplan]] = {
        "earmark-adds-label": ([tk("A-1")], Preplan(earmarks=[Earmark("A-1", "2026.23")])),
        "label-present": (
            [tk("A-1", labels=["planned_for_2026.23"])],
            Preplan(earmarks=[Earmark("A-1", "2026.23")]),
        ),
        "earmark-changed": (
            [tk("A-1", labels=["planned_for_2026.22", "keep"])],
            Preplan(earmarks=[Earmark("A-1", "2026.24")]),
        ),
        "earmark-released": ([tk("A-1", labels=["planned_for_2026.22"])], Preplan()),
        "real-sprint-wins": (
            [tk("A-1", in_sprint="2026.22", labels=["planned_for_2026.23"])],
            Preplan(earmarks=[Earmark("A-1", "2026.23")]),
        ),
        "done-left-alone": (
            [tk("A-1", done=True, labels=["planned_for_2026.23"])],
            Preplan(earmarks=[Earmark("A-1", "2026.24")]),
        ),
        "space-in-sprint-id": ([tk("A-1")], Preplan(earmarks=[Earmark("A-1", "2026 23")])),
        "nothing-to-do": ([tk("A-1"), tk("A-2", labels=["x"])], Preplan()),
        "several-labels": (
            [tk("A-1", labels=["planned_for_a", "planned_for_b", "planned_for_a", "other"])],
            Preplan(earmarks=[Earmark("A-1", "b")]),
        ),
        "many": (
            [tk("A-1"), tk("A-2", labels=["planned_for_x"]), tk("A-3"), tk("A-4")],
            Preplan(earmarks=[Earmark("A-1", "p"), Earmark("A-3", "q"), Earmark("A-4", "r s")]),
        ),
    }
    plans = []
    for name, (tickets, preplan) in cases.items():
        plan = plan_label_writes(tickets, preplan)
        applies = []
        for fail_at in (None, 0, 1):
            recorder = _Recorder(fail_at)
            try:
                done: Any = apply_label_writes(recorder, plan)
                result = {"ok": done}
            except SourceError as e:
                result = {"error": str(e)}
            applies.append({"fail_at": fail_at, "calls": recorder.calls, **result})
        plans.append(
            {"name": name, "tickets": tickets, "preplan": preplan, "plan": plan, "apply": applies}
        )
    ctx.write("ticketimport/labels.json", ctx.dump_json(ctx.jsonable(plans)))
