# SPDX-License-Identifier: EUPL-1.2
"""Golden files: reference results of the Python core for the Go port.

The Go core (``go/``) must reproduce the Python core exactly. This script writes the reference
files that the Go tests compare against: the results of the Python core for the demo team
(``examples/teams/demo``) and for synthetic teams that cover the corners of the calculation.

    uv run python scripts/golden.py            # rewrite golden/ (inputs and expected results)
    uv run python scripts/golden.py --check    # fail if golden/ differs from what Python gives

``--check`` runs in CI: the references can never drift away from the Python core unnoticed.
Layout and the rules for changing a reference: ``golden/README.md``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tempfile
import warnings
from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

# Files are English whatever the language of the machine; set before foresprint is imported.
os.environ["FORESPRINT_LANG"] = "en"
os.environ["FORESPRINT_NO_BACKGROUND_FETCH"] = "1"
warnings.simplefilter("ignore", UserWarning)  # holidays: "available only from 2001 to 2035"

import holidays  # noqa: E402

from foresprint import calendar as cal  # noqa: E402
from foresprint import i18n, preplan  # noqa: E402
from foresprint.analysis import completion, horizon_forecast  # noqa: E402
from foresprint.capacity import (  # noqa: E402
    capacity_with_expected_absences,
    production_share,
    sprint_capacity,
)
from foresprint.forecast import build_forecast  # noqa: E402
from foresprint.model import (  # noqa: E402
    AbsenceState,
    BudgetBasis,
    Earmark,
    EstimateSource,
    ManualEstimate,
    Membership,
    Numbering,
    Person,
    Planning,
    PlanningUses,
    Preplan,
    Product,
    Project,
    Rule,
    Sprint,
    Team,
    Ticket,
    TrendMode,
)
from foresprint.storage import DataError, Repository, TeamData, clear_team_cache  # noqa: E402
from foresprint.ticket_import import assign_project  # noqa: E402
from foresprint.validate import check_team, check_team_files  # noqa: E402

i18n.set_language("en")

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"
EXAMPLES = ROOT / "examples" / "teams"
MARKER = "(none)"  # JSON key for a ``None`` dictionary key


# --- JSON -----------------------------------------------------------------------------------


def jsonable(obj: Any) -> Any:
    """Plain JSON structure of a result: dataclass fields in declaration order, enums by value,
    dates as ISO text, dictionaries with ``None`` keys under ``MARKER``. Properties are not
    included; the exporters add the ones that matter explicitly."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {(MARKER if k is None else str(jsonable(k))): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        items = sorted(obj) if isinstance(obj, set | frozenset) else obj
        return [jsonable(v) for v in items]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        raise ValueError(f"not a JSON number: {obj}")
    return obj


def dump_json(value: Any, compact: bool = False) -> str:
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


# --- Cases ----------------------------------------------------------------------------------


@dataclasses.dataclass
class Case:
    name: str
    root: str  # relative to the repository root
    team: str
    today: date
    description: str
    # Parameter sets of the Monte Carlo simulation: (remaining, share, runs, seed).
    simulations: list[tuple[float, float, int, int]] = dataclasses.field(default_factory=list)


def _sprints(team: Team, count: int, values: dict[str, list[Any]]) -> list[Sprint]:
    """``count`` consecutive sprints from the calendar; ``values`` maps a sprint field to one
    entry per sprint (``None`` = not recorded)."""
    sprints: list[Sprint] = []
    previous = None
    for i in range(count):
        previous = cal.following_sprint(team, previous)
        for name, series in values.items():
            if i < len(series) and series[i] is not None:
                setattr(previous, name, series[i])
        sprints.append(previous)
    return sprints


def _write_team(root: Path, team: Team, **parts: Any) -> None:
    repo = Repository(root)
    repo.save_team(team)
    if parts.get("people"):
        repo.save_people(team.key, parts["people"])
    if parts.get("products"):
        repo.save_products(team.key, parts["products"])
    for sprint in parts.get("sprints", []):
        repo.save_sprint(team.key, sprint)
    if parts.get("projects"):
        repo.save_projects(team.key, parts["projects"])
    if parts.get("tickets"):
        repo.save_tickets(
            team.key, parts["tickets"], datetime(2026, 10, 14, 8, 30), "golden-import.csv"
        )
    if parts.get("preplan"):
        repo.save_preplan(team.key, parts["preplan"])


def _base_team(key: str, **forecast: Any) -> Team:
    team = Team(key=key, name=f"Golden {key}")
    team.sprint.first_id = "2026.1"
    team.sprint.first_start = date(2026, 1, 7)
    team.forecast.reference_capacity = 40
    for name, value in forecast.items():
        setattr(team.forecast, name, value)
    return team


VELOCITY = [30, 34, 28, 36, None, 33, 38, None, 31, 35, 37]
COMMITMENT = [32, 35, 33, 36, 30, 34, 38, 33, 32, 36, 37, 36]
CAPACITY = [40, 44, 38, 42, 40, 36, 44, 42, None, 41, 40, 39]
SCOPE_CREEP = [0.1, None, 0.05, 0.2, 0.0, 0.15, None, 0.1, 0.05, 0.0, 0.1]


def build_trend(root: Path, mode: TrendMode) -> Case:
    """No people list: recorded capacities, trend capacity for the future, gaps in the series."""
    team = _base_team(f"trend-{mode.value}", trend_mode=mode, window=5, horizon=4)
    sprints = _sprints(
        team,
        12,
        {"velocity": VELOCITY, "commitment": COMMITMENT, "capacity": CAPACITY,
         "scope_creep": SCOPE_CREEP},
    )  # fmt: skip
    sprints[11].velocity = None
    sprints[11].scope_creep = None
    _write_team(root, team, sprints=sprints)
    return Case(
        team.key, f"golden/inputs/{team.key}", team.key, date(2026, 6, 24),
        f"Trend mode {mode.value}: gaps in velocity and capacity, no people list.",
        [(120, 0.8, 5000, 1)],
    )  # fmt: skip


def build_thin(root: Path) -> Case:
    team = _base_team("thin", trend_mode=TrendMode.LINEAR, window=6, horizon=3)
    sprints = _sprints(
        team, 5,
        {"velocity": [20, 24, 22, 26], "commitment": [22, 24, 24, 26, 25],
         "capacity": [38, 40, 36, 40, 40]},
    )  # fmt: skip
    _write_team(root, team, sprints=sprints)
    return Case(
        "thin", "golden/inputs/thin", "thin", date(2026, 3, 18),
        "Fewer sprints than the window: the thin-history rule and the flat fallback.",
        [(60, 0.5, 3000, 7)],
    )  # fmt: skip


def _people() -> list[Person]:
    def m(start: str, end: str | None = None, fte: float = 1.0) -> Membership:
        return Membership(date.fromisoformat(start), date.fromisoformat(end) if end else None, fte)

    return [
        Person("anna", "Anna", memberships=[m("2025-01-01")]),
        Person("ben", "Ben", memberships=[m("2025-01-01", "2026-08-31"), m("2026-09-01", None, 0.5)]),
        Person("cem", "Cem", region="BY", memberships=[m("2025-01-01")]),
        Person("dana", "Dana", country="US", region="CA", memberships=[m("2025-06-01")]),
        Person("eli", "Eli", country="CN", memberships=[m("2025-06-01", fte=0.8)]),
        Person("fadi", "Fadi", country="SA", memberships=[m("2026-01-01")]),
        Person("gina", "Gina", workweek="mon,tue,wed,thu", memberships=[m("2025-01-01")]),
        Person("hugo", "Hugo", workweek="sun-thu", memberships=[m("2025-01-01")]),
        Person("ines", "Ines", production_access=True, memberships=[m("2025-01-01", "2026-12-31")]),
        Person("jonas", "Jonas", production_access=True, memberships=[m("2026-09-15")]),
    ]  # fmt: skip


def build_people(root: Path, name: str, **capacity: Any) -> Case:
    """People with own regions, countries, workweeks and FTE changes; every absence state;
    sprints across the turn of the year."""
    team = _base_team(name, trend_mode=TrendMode.FLAT, window=5, horizon=4)
    team.sprint.first_id = "2026.14"
    team.sprint.first_start = date(2026, 7, 1)
    team.capacity.region = "NW"
    for key, value in capacity.items():
        setattr(team.capacity, key, value)
    sprints = _sprints(
        team,
        14,
        {"velocity": [28, 30, 27, 33, 31, 29, 35, 30, 28, 32, None, None],
         "commitment": [30, 31, 30, 34, 32, 30, 36, 31, 30, 33, 30, 29]},
    )  # fmt: skip
    # 0 absences entered; 1 confirmed without absences and 2 absences of one person (both are
    # stored as plain legacy files, the stored state is derived); 3 announced only; 4 unknown
    # (stored explicitly). Then the pattern repeats.
    for i, sprint in enumerate(sprints[:12]):
        kind = i % 5
        if kind == 0:
            sprint.absences = {"anna": 3, "ben": 1.5, "cem": 2}
            sprint.absence_state = AbsenceState.CONFIRMED
        elif kind == 1:
            sprint.absence_state = AbsenceState.CONFIRMED
        elif kind == 2:
            sprint.absences = {"dana": 1}
        elif kind == 3:
            sprint.expected_absences = {"anna": 2, "gina": 1}
            sprint.absence_state = AbsenceState.EXPECTED
        else:
            sprint.absence_state = AbsenceState.UNKNOWN
        if i in (3, 8):
            sprint.planning = Planning(carryover=4, backlog=26, corrections=[1.5])
    for sprint in sprints[12:]:
        sprint.expected_absences = {"cem": 3}
        sprint.absence_state = AbsenceState.EXPECTED
    _write_team(root, team, people=_people(), sprints=sprints)
    return Case(
        name, f"golden/inputs/{name}", name, date(2027, 1, 5),
        "People list: FTE changes, own countries, workweeks, holidays, all absence states, "
        "year change.",
        [(90, 0.6, 4000, 3)],
    )  # fmt: skip


def _tracker_team(name: str, products: bool, **tracker: Any) -> Team:
    team = _base_team(name, trend_mode=TrendMode.FLAT, window=5, horizon=3)
    team.sprint.first_start = date(2026, 5, 6)
    team.features.tickets = True
    team.features.products = products
    team.features.po = products
    team.tracker.refined_label = "refined"
    team.tracker.rule_fields = {"team": "Team"}
    for key, value in tracker.items():
        setattr(team.tracker, key, value)
    return team


def _leaf(source: str, *values: str, contains: bool = False) -> Rule:
    return Rule(op="leaf", source=source, values=list(values), contains=contains)


def _any(*children: Rule) -> Rule:
    return Rule(op="any", children=list(children))


def _tk(key: str, estimate: float | None, **kw: Any) -> Ticket:
    source = kw.pop("source", EstimateSource.REFINED if estimate is not None else None)
    return Ticket(
        key=key, title=f"Ticket {key}", estimate=estimate,
        estimate_source=source or EstimateSource.NONE, **kw,
    )  # fmt: skip


def _assign(tickets: list[Ticket], projects: list[Project], team: Team) -> None:
    """Sets ``project`` and ``project_candidates`` as the import does."""
    for ticket in tickets:
        ticket.project, ticket.project_candidates = assign_project(
            ticket.facts(), projects, team.tracker.project_match_order
        )


def build_tickets_simple(root: Path) -> Case:
    """Ticket distribution without products: projects with target dates, dependencies,
    priorities, a fixed sprint, an earmark and manual estimates."""
    team = _tracker_team("tickets-simple", products=False)
    sprints = _sprints(
        team, 7,
        {"velocity": [30, 32, 28, 34, 30], "commitment": [30, 32, 30, 34, 31, 30],
         "capacity": [40, 40, 36, 40, 40, 40]},
    )  # fmt: skip
    projects = [
        Project("alpha", "Alpha", target=date(2026, 9, 30), priority=1, match=_any(_leaf("epic", "A-1"))),
        Project("beta", "Beta", target=date(2026, 8, 1), priority=2, match=_any(_leaf("label", "beta"))),
        Project("gamma", "Gamma", target=None, priority=3, budget_basis=BudgetBasis.PLAN,
                match=_any(_leaf("component", "api"))),
    ]  # fmt: skip
    tickets = [
        _tk("T-1", 5, epic="A-1", priority="High", rank="0|a"),
        _tk("T-2", 8, epic="A-1", priority="Medium", rank="0|b", depends_on=["T-1"]),
        _tk("T-3", 13, epic="A-1", priority="Low", rank="0|c"),
        _tk("T-4", 3, labels=["beta"], priority="Highest", rank="0|d"),
        _tk("T-5", 40, labels=["beta"], rank="0|e"),
        _tk("T-6", None, labels=["beta"], rank="0|f"),
        _tk("T-7", 5, components=["api"], rank="0|g", in_sprint="2026.9"),
        _tk("T-8", 2, components=["api"], rank="0|h", remaining=1),
        _tk("T-9", 5, source=EstimateSource.ROUGH, labels=["beta"], rank="0|i"),
        _tk("T-10", 5, epic="A-1", rank="0|j", depends_on=["T-11"]),
        _tk("T-11", 5, epic="A-1", rank="0|k", depends_on=["T-10"]),
        _tk("T-12", 4, epic="A-1", rank="0|l", depends_on=["T-13", "T-5"]),
        _tk("T-13", None, epic="A-1", rank="0|m"),
        _tk("T-14", 2, epic="Z-9", rank="0|n"),
        _tk("T-15", 3, epic="A-1", rank="0|o", done=True),
        # Filler that outlasts the horizon of 26 sprints.
        *(_tk(f"F-{i}", 8, components=["api"], rank=f"1|{i:02d}") for i in range(1, 61)),
    ]  # fmt: skip
    _assign(tickets, projects, team)
    pre = Preplan(
        earmarks=[Earmark("T-3", "2026.10", "pull forward")],
        estimates=[ManualEstimate("T-6", 6), ManualEstimate("T-13", 3, "from refinement")],
    )
    _write_team(root, team, sprints=sprints, projects=projects, tickets=tickets, preplan=pre)
    return Case(
        "tickets-simple", "golden/inputs/tickets-simple", "tickets-simple", date(2026, 7, 8),
        "Ticket distribution (no products): targets, priorities, dependencies and cycles, "
        "fixed sprint, earmark, manual estimates, too large, unestimated.",
    )  # fmt: skip


def build_tickets_products(root: Path) -> Case:
    """Ticket distribution with products: shares, product periods, rules, project and product
    budgets, rough estimates in the conservative variant."""
    team = _tracker_team(
        "tickets-products", products=True, rough_factor=1.5, dependency_gap=0,
        priority_order=["Blocker", "High", "Normal"], planning_uses=PlanningUses.ESTIMATE,
    )  # fmt: skip
    team.features.production = True
    sprints = _sprints(
        team, 7,
        {"velocity": [31, 29, 35, 33, 30], "commitment": [32, 30, 34, 34, 31, 32],
         "capacity": [40, 38, 40, 42, 40, 40]},
    )  # fmt: skip
    products = [
        Product("web", "Web", po="Alex", share=0.5,
                match=_any(_leaf("component", "frontend"))),
        Product("app", "App", po="Alex", match=_any(_leaf("label", "mobile", contains=True))),
        Product("old", "Old", po="Bea", end=date(2026, 8, 20)),
        Product("new", "New", po="Bea", start=date(2026, 8, 5)),
    ]  # fmt: skip
    projects = [
        Project("shop", "Shop relaunch", product="web", target=date(2026, 10, 31), priority=1,
                match=_any(_leaf("epic", "SHOP"))),
        Project("pay", "Payment", product="web", target=date(2026, 8, 20), priority=2,
                match=_any(_leaf("epic", "PAY"), _leaf("label", "payment"))),
        Project("ios", "iOS", product="app", target=date(2026, 12, 15), priority=1,
                match=_any(_leaf("epic", "IOS"))),
        Project("legacy", "Legacy", product="old", target=date(2026, 12, 1), priority=9,
                match=_any(_leaf("epic", "LEGACY"))),
        Project("migr", "Migration", product="new", target=None, priority=5,
                budget_basis=BudgetBasis.PLAN, match=_any(_leaf("team", "platform"))),
    ]  # fmt: skip
    tickets = [
        _tk("W-1", 5, epic="SHOP", priority="Blocker", rank="0|a"),
        _tk("W-2", 8, epic="SHOP", priority="High", rank="0|b", depends_on=["W-1"]),
        _tk("W-3", 13, epic="SHOP", rank="0|c", source=EstimateSource.ROUGH),
        _tk("W-4", 3, epic="PAY", priority="High", rank="0|d"),
        _tk("W-5", 5, labels=["payment"], rank="0|e"),
        _tk("W-6", 2, components=["frontend"], rank="0|f"),
        _tk("W-7", 5, labels=["mobile-ios"], rank="0|g"),
        _tk("W-8", 21, epic="IOS", rank="0|h", refined_unclear=True, source=EstimateSource.ROUGH),
        _tk("W-9", 3, extra={"team": ["platform"]}, rank="0|i", priority="Normal"),
        _tk("W-10", 4, extra={"team": ["platform"]}, rank="0|j", depends_on=["W-9", "W-6"]),
        _tk("W-11", 5, epic="UNKNOWN", rank="0|k"),
        _tk("W-12", 5, epic="SHOP", rank="0|l", in_sprint="2026.10"),
        _tk("W-13", None, epic="IOS", rank="0|m"),
        _tk("W-14", 5, epic="SHOP", labels=["payment"], rank="0|n"),
        _tk("W-15", 1, epic="IOS", rank="0|o", priority="Blocker"),
        *(_tk(f"L-{i}", 2, epic="LEGACY", rank=f"1|{i}") for i in range(1, 7)),
    ]  # fmt: skip
    _assign(tickets, projects, team)
    pre = Preplan(
        earmarks=[Earmark("W-4", "2026.9"), Earmark("W-7", "2027.9", "far away")],
        estimates=[ManualEstimate("W-13", 8)],
    )
    _write_team(
        root, team, sprints=sprints, products=products, projects=projects, tickets=tickets,
        preplan=pre,
    )  # fmt: skip
    return Case(
        "tickets-products", "golden/inputs/tickets-products", "tickets-products",
        date(2026, 7, 8),
        "Ticket distribution with products: shares, periods, product rules, budget bases, "
        "rough factor, contradicting projects, far earmark.",
    )  # fmt: skip


# Hand-written files in the shapes people really produce: comments, quoting, order, 5 vs 5.0.
MESSY: dict[str, str] = {
    "team.yaml": """\
# my team   (comment that the tool will not keep)
name:   "Messy Team"
sprint:
    length_days: 14
    first: {id: "2026.1", start: 2026-01-07}
forecast: {reference_capacity: 50.0, window: 5, trend_mode: linear}
capacity:
  country: "de"
  overhead_share: 0.10
  region: BY
unit: SP
""",
    "people.yaml": """\
people:
  - {id: zoe, name: "Zoë Äpfel", memberships: [{from: 2025-01-01, fte: 1.0}]}
  - id: li
    name: 'O''Neil: the "second"'
    memberships:
      - from: 2025-03-01
        to: 2026-06-30
        fte: .5
""",
    "sprints/2026.1.yaml": """\
id: "2026.1"
start: 2026-01-07
end: 2026-01-21
commitment: 30.0
velocity: 28
capacity: 41.50
note: "A long note that has to wrap because it is longer than one hundred characters, which is the width the dumper uses."
""",
    "sprints/2026.2.yaml": """\
id: "2026.2"
start: 2026-01-21
end: 2026-02-04
velocity: 1.0e+1
commitment: 12
capacity: 40
scope_creep: 0.05
absences: {zoe: 2.0}
""",
}


def build_messy(root: Path) -> Case:
    base = root / "messy"
    for rel, text in MESSY.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return Case(
        "yaml-messy", "golden/inputs/yaml-messy", "messy", date(2026, 3, 1),
        "Hand-written files (comments, quoting, flow style, 5 vs 5.0): the YAML round trip.",
    )  # fmt: skip


def demo_case() -> Case:
    return Case(
        "demo", "examples/teams", "demo", date(2026, 10, 15),
        "The demo team of the examples folder.", [(60, 0.4, 10000, 1), (150, 0.8, 2000, 42)],
    )  # fmt: skip


# --- Exporters ------------------------------------------------------------------------------


def load(case: Case) -> TeamData:
    clear_team_cache()
    return Repository(ROOT / case.root).load(case.team)


def export_forecast(data: TeamData, today: date) -> dict[str, Any]:
    fc = build_forecast(data, today)
    return {
        "today": today,
        "entries": [
            {
                "sprint": e.sprint,
                "recorded": e.recorded,
                "capacity_digits": e.capacity_digits,
                "result": e.result,
            }
            for e in fc.entries
        ],
        "absences": fc.absences,
    }


def export_capacity(data: TeamData, today: date) -> dict[str, Any] | None:
    """The capacity breakdown of every sprint in the forecast (people teams only)."""
    if not data.people:
        return None
    fc = build_forecast(data, today)
    rate = fc.absences.rate if fc.absences and fc.absences.rate is not None else 0.0
    out = []
    for e in fc.entries:
        sprint = e.sprint
        breakdown = sprint_capacity(data.team, data.people, sprint)
        with_rate = sprint_capacity(data.team, data.people, sprint, 0.1)
        out.append(
            {
                "sprint": sprint.id,
                "breakdown": breakdown,
                "rounded": breakdown.rounded,
                "approximated": [p.person.id for p in breakdown.approximated],
                "with_rate_0_1": with_rate,
                "history_rate": rate,
                "expected_absences": capacity_with_expected_absences(
                    data.team, data.people, sprint
                ),
                "production_share": production_share(data.team, data.people, sprint),
            }
        )
    return {"sprints": out}


def _range_extras(r: preplan.ProjectRange) -> dict[str, Any]:
    return {**jsonable(r), "light_range": list(r.light_range), "uniform": r.uniform,
            "on_track": r.on_track}  # fmt: skip


def export_preplan(data: TeamData, today: date) -> dict[str, Any] | None:
    if not data.team.features.tickets:
        return None
    variants = preplan.distribute_variants(data, today)
    out: dict[str, Any] = {
        "samples": variants.samples,
        "available": variants.available,
        "variants": {v.value: d for v, d in variants.items()},
    }
    out["project_ranges"] = {
        p.id: _range_extras(preplan.project_range(variants, p.id)) for p in data.projects
    }
    ranges = {}
    for t in data.tickets:
        r = preplan.ticket_range(variants, t.key)
        ranges[t.key] = None if r is None else {**jsonable(r), "fixed": r.fixed}
    out["ticket_ranges"] = ranges
    rows = preplan.handover_rows(data, variants.median)
    out["handover"] = [
        {
            **jsonable(r),
            "action": r.action(False),
            "action_overwrite": r.action(True),
            "writes": r.writes(False),
            "writes_overwrite": r.writes(True),
        }
        for r in rows
    ]
    out["sprint_sums"] = {
        v.value: {
            s: preplan.sprint_sums(d, s, data) for s in d.sprints
        }
        for v, d in variants.items()
    }  # fmt: skip
    return out


def export_completion(
    data: TeamData, today: date, sims: list[tuple[float, float, int, int]]
) -> list[dict[str, Any]] | None:
    if not sims:
        return None
    out = []
    for remaining, share, runs, seed in sims:
        result = completion(data, today, remaining, share, runs=runs, seed=seed)
        out.append(
            {
                "params": {"remaining": remaining, "share": share, "runs": runs, "seed": seed},
                "result": result,
            }
        )
    return out


def export_check(case_dir: Path, data: TeamData, today: date) -> dict[str, Any]:
    """The findings of the data check (texts in English)."""
    return {
        "team": check_team(data, today),
        "files": check_team_files(case_dir, data.team.features.tickets),
    }


def export_horizon(data: TeamData, today: date) -> dict[str, Any]:
    from foresprint.analysis import (
        average_focus_factor,
        band,
        buffer_hint,
        focus_factor,
        horizon_entries,
        normalized_history,
        sample_count,
    )

    fc = horizon_forecast(data, today)
    return {
        "normalized_history": normalized_history(fc),
        "sample_count": sample_count(fc),
        "average_focus_factor": average_focus_factor(fc),
        "buffer_hint": buffer_hint(fc),
        "bands": {e.sprint.id: band(fc, e) for e in fc.entries if e.sprint.start > today},
        "focus": {e.sprint.id: focus_factor(e) for e in fc.entries},
        "horizon": [
            {"sprint": h.sprint.id, "capacity": h.capacity, "trend": h.trend}
            for h in horizon_entries(fc)
        ],
    }


def yaml_roundtrip(case: Case, out: dict[str, str]) -> dict[str, Any]:
    """Loads the team and saves every file again into a copy of the folder. Files whose bytes
    change are written to ``yaml/<case>/<file>``; the manifest lists all files."""
    src = ROOT / case.root / case.team
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / case.team
        shutil.copytree(src, copy)
        clear_team_cache()
        repo = Repository(Path(tmp))
        data = repo.load(case.team)
        repo.save_team(data.team)
        if (copy / "people.yaml").is_file():
            repo.save_people(case.team, data.people)
        if (copy / "products.yaml").is_file():
            repo.save_products(case.team, data.products)
        if (copy / "projects.yaml").is_file():
            repo.save_projects(case.team, data.projects)
        if (copy / "tickets.yaml").is_file():
            repo.save_tickets(case.team, data.tickets, data.tickets_imported, data.tickets_source)
        if (copy / "preplan.yaml").is_file():
            repo.save_preplan(case.team, data.preplan)
        for sprint in data.sprints:
            repo.save_sprint(case.team, sprint)
        files = []
        for path in sorted(src.rglob("*.yaml")):
            rel = path.relative_to(src).as_posix()
            before, after = path.read_bytes(), (copy / rel).read_bytes()
            entry = {"file": rel, "identical": before == after}
            if before != after:
                out[f"yaml/{case.name}/{rel}"] = after.decode("utf-8")
            files.append(entry)
    return {"case": case.name, "files": files}


# --- Calendar -------------------------------------------------------------------------------

SAMPLE_YEARS = (2001, 2012, 2025, 2026, 2027, 2028, 2050)
SAMPLE_CALENDARS: list[tuple[str, str | None]] = [
    ("DE", None), *(("DE", r) for r in ("BW", "BY", "BE", "NW", "SN", "TH", "HH")),
    ("AT", None), ("AT", "9"), ("CH", None), ("CH", "ZH"), ("FR", None), ("ES", "CT"),
    ("IT", None), ("GB", None), ("GB", "SCT"), ("NL", None), ("PL", None), ("SE", None),
    ("US", None), ("US", "CA"), ("US", "TX"), ("CA", "ON"), ("CA", "QC"), ("AU", "NSW"),
    ("JP", None), ("CN", None), ("KR", None), ("SA", None), ("IL", None), ("IN", None),
    ("BR", None), ("ZZ", None), ("DE", "XX"),
]  # fmt: skip


def _calendar_text(country: str, region: str | None, language: str, years: Any) -> str:
    try:
        h = holidays.country_holidays(
            country.upper(), subdiv=region, years=years, language=language
        )
    except NotImplementedError:
        h = {}
    return "".join(f"{d.isoformat()}\t{n}\n" for d, n in sorted(h.items()))


def export_holidays_sample() -> dict[str, Any]:
    out = {}
    for country, region in SAMPLE_CALENDARS:
        key = f"{country}/{region or ''}"
        entry: dict[str, Any] = {"country": country, "region": region, "years": {}}
        for year in SAMPLE_YEARS:
            entry["years"][str(year)] = {
                lang: {
                    d.isoformat(): n
                    for d, n in sorted(cal._holiday_calendar(country, region, year, lang).items())
                }
                for lang in ("de", "en")
            }
            entry["years"][str(year)]["is_holiday"] = [
                d.isoformat()
                for d in (date(year, 1, 1) + timedelta(days=i) for i in range(366))
                if d.year == year and cal.is_holiday(d, region, country)
            ]
        out[key] = entry
    return out


def export_holidays_digest() -> dict[str, Any]:
    """SHA-256 of the complete list of every country and region, 2001-2050, per language."""
    supported = holidays.list_supported_countries(include_aliases=False)
    out: dict[str, Any] = {"first_year": 2001, "last_year": 2050, "digests": {}}
    for country in sorted(supported):
        for region in [None, *supported[country]]:
            row = {}
            for lang in ("de", "en"):
                text = _calendar_text(
                    country, region, "en_US" if lang == "en" else "de", range(2001, 2051)
                )
                row[lang] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
            out["digests"][f"{country}/{region or ''}"] = row
    out["aliases"] = {
        a: holidays.country_holidays(a).country
        for a in sorted(holidays.list_supported_countries())
        if a not in supported
    }
    return out


def export_countries() -> dict[str, Any]:
    names = cal.countries()
    return {
        code: {
            "name": name,
            "subdivisions": cal.subdivisions(code),
            "weekend": sorted(cal.country_weekend(code)),
        }
        for code, name in names.items()
    }


def export_workdays() -> dict[str, Any]:
    spans = [
        (date(2026, 1, 1), date(2026, 1, 15)), (date(2026, 12, 21), date(2027, 1, 11)),
        (date(2027, 2, 26), date(2027, 3, 2)), (date(2026, 10, 7), date(2026, 10, 7)),
        (date(2028, 2, 20), date(2028, 3, 5)),
    ]  # fmt: skip
    weekends = {
        "default": sorted(cal.DEFAULT_WEEKEND),
        **{name: sorted(w) for name, w in cal.WORKWEEKS.items()},
        "4-day": sorted(cal.weekend_from_workweek("mon,tue,wed,thu") or []),
        "sa": sorted(cal.country_weekend("SA")),
    }
    out: dict[str, Any] = {
        "workdays": [
            {"start": s, "end": e, "weekend": name, "days": cal.workdays(s, e, frozenset(w))}
            for s, e in spans
            for name, w in weekends.items()
        ],
        "workweek_values": {},
        "team_weekend": {},
        "labels": {},
    }
    for value in (None, "", "auto", "mon-fri", "sun-thu", "mon-sat", "mon,tue,wed,thu",
                  "tue;wed;thu", "mon wed fri", "xyz", "mon,foo"):  # fmt: skip
        try:
            r = cal.weekend_from_workweek(value)
            out["workweek_values"][repr(value)] = None if r is None else sorted(r)
        except ValueError:
            out["workweek_values"][repr(value)] = "error"
    for country in ("DE", "SA", "IL", "IN", "US", "CN", "XX"):
        for workweek in ("auto", "sun-thu", "mon,tue,wed,thu", "bogus"):
            team = Team(key="x", name="x")
            team.capacity.country = country
            team.capacity.workweek = workweek
            out["team_weekend"][f"{country}/{workweek}"] = sorted(cal.team_weekend(team))
            out["labels"][f"{country}/{workweek}"] = cal.workweek_label(team)
    return out


def export_sprint_calendar() -> dict[str, Any]:
    out: dict[str, Any] = {"series": [], "next_id": [], "fits": []}
    for numbering, first_id, first_start, length in (
        (Numbering.YEARLY, "2026.20", date(2026, 11, 4), 14),
        (Numbering.YEARLY, "2026.1", date(2026, 12, 2), 21),
        (Numbering.SEQUENTIAL, "21", date(2026, 3, 2), 7),
        (Numbering.YEARLY, "2026.5", date(2025, 12, 17), 14),
    ):
        team = Team(key="t", name="t")
        team.sprint.numbering = numbering
        team.sprint.length_days = length
        team.sprint.first_id = first_id
        team.sprint.first_start = first_start
        series, previous = [], None
        for _ in range(12):
            previous = cal.following_sprint(team, previous)
            series.append(previous)
        out["series"].append({"numbering": numbering, "length_days": length, "sprints": series})
    for previous_id, start, numbering in (
        ("2026.26", date(2027, 1, 6), Numbering.YEARLY),
        ("2026.26", date(2026, 12, 30), Numbering.YEARLY),
        ("22b", date(2026, 3, 1), Numbering.YEARLY),
        ("22b", date(2026, 3, 1), Numbering.SEQUENTIAL),
        ("22.0", date(2026, 3, 1), Numbering.SEQUENTIAL),
        ("7", date(2026, 3, 1), Numbering.YEARLY),
        ("2025.9", date(2026, 1, 10), Numbering.YEARLY),
        ("", date(2026, 1, 10), Numbering.YEARLY),
    ):
        try:
            result: Any = cal.next_id(previous_id, start, numbering)
        except DataError:
            result = None  # error (the message is not part of the reference)
        out["next_id"].append(
            {"previous": previous_id, "start": start, "numbering": numbering, "id": result}
        )
        out["fits"].append(
            {"previous": previous_id, "start": start, "numbering": numbering,
             "fits": cal.id_fits_numbering(previous_id, start, numbering)}
        )  # fmt: skip
    return out


# --- Random numbers -------------------------------------------------------------------------


def export_rng() -> dict[str, Any]:
    """The streams of ``random.Random(seed)`` that the Monte Carlo simulation depends on."""
    import random

    out = []
    seeds = [0, 1, 2, 7, 42, 12345, 2**31 - 1, 2**32, 2**32 + 5, 2**64 - 1, 2**100 + 12345, -17]
    for seed in seeds:
        rng = random.Random(seed)
        random_values = [rng.random() for _ in range(40)]
        bits = {}
        for k in (1, 3, 7, 8, 16, 31, 32, 33, 52, 63, 64, 65, 100):
            rng = random.Random(seed)
            bits[str(k)] = [str(rng.getrandbits(k)) for _ in range(12)]
        below = {}
        for n in (1, 2, 3, 4, 5, 6, 7, 10, 26, 100, 1000, 2**31, 2**33 + 1):
            rng = random.Random(seed)
            below[str(n)] = [rng._randbelow(n) for _ in range(30)]
        rng = random.Random(seed)
        choices = [rng.choice([3.5, 1.25, 9.0, 4.75, 6.0]) for _ in range(30)]
        out.append(
            {
                "seed": str(seed),
                "random": random_values,
                "getrandbits": bits,
                "randbelow": {k: v for k, v in below.items()},
                "choice_indexes": choices,
            }
        )
    return {"streams": out}


# --- Everything -----------------------------------------------------------------------------

BUILDERS: list[tuple[str, Callable[[Path], Case]]] = [
    ("trend-flat", lambda r: build_trend(r, TrendMode.FLAT)),
    ("trend-linear", lambda r: build_trend(r, TrendMode.LINEAR)),
    ("trend-classic", lambda r: build_trend(r, TrendMode.CLASSIC)),
    ("thin", build_thin),
    ("people-days", lambda r: build_people(r, "people-days", overhead_days=1.0)),
    ("people-share", lambda r: build_people(r, "people-share", overhead_share=0.12,
                                            absence_history=0, rounding=0)),
    ("tickets-simple", build_tickets_simple),
    ("tickets-products", build_tickets_products),
    ("yaml-messy", build_messy),
]  # fmt: skip


@dataclasses.dataclass
class Context:
    """What an extension (``scripts/golden_ext/*.py``) gets: the cases (``resolved`` has the
    folders as absolute paths), a ``write(relative path below golden/expected, text)`` and
    the helpers of this script (``jsonable``, ``dump_json``, ``load``)."""

    out: Path
    expected: Path
    cases: list[Case]
    resolved: list[Case]
    write: Callable[[str, str], None]
    jsonable: Callable[[Any], Any] = jsonable
    dump_json: Callable[..., str] = dump_json
    load: Callable[[Case], TeamData] = load


def run_extensions(context: Context) -> None:
    """Every ``scripts/golden_ext/<name>.py`` (not starting with ``_``) with a ``generate(ctx)``
    function adds its own references, so that the porting threads of different modules do not
    edit the same file."""
    import importlib.util

    folder = Path(__file__).resolve().parent / "golden_ext"
    for path in sorted(folder.glob("[!_]*.py")):
        spec = importlib.util.spec_from_file_location(f"golden_ext_{path.stem}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(context)


def generate(out: Path) -> None:
    """Writes the complete golden tree (``inputs/`` and ``expected/``) below ``out``."""
    inputs = out / "inputs"
    cases = [demo_case()]
    for name, build in BUILDERS:
        cases.append(build(inputs / name))
    expected = out / "expected"

    def write(rel: str, text: str) -> None:
        path = expected / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def resolve(case: Case) -> Case:
        root = (
            out / case.root.removeprefix("golden/")
            if case.root.startswith("golden/")
            else ROOT / case.root
        )
        return dataclasses.replace(case, root=str(root))

    manifest = []
    for case in cases:
        real = resolve(case)
        manifest.append(
            {
                "name": case.name, "root": case.root, "team": case.team,
                "today": case.today, "description": case.description,
                "yaml": f"yaml/{case.name}.json",
            }
        )  # fmt: skip
        data = load(real)
        files: dict[str, Any] = {
            "forecast": export_forecast(data, case.today),
            "capacity": export_capacity(data, case.today),
            "horizon": export_horizon(data, case.today),
            "check": export_check(Path(real.root) / real.team, data, case.today),
            "preplan": export_preplan(data, case.today),
            "completion": export_completion(data, case.today, case.simulations),
        }
        for kind, value in files.items():
            if value is not None:
                write(f"cases/{case.name}/{kind}.json", dump_json(jsonable(value)))
        texts: dict[str, str] = {}
        write(f"yaml/{case.name}.json", dump_json(yaml_roundtrip(real, texts)))
        for rel, text in texts.items():
            write(rel, text)
    run_extensions(Context(out, expected, cases, [resolve(c) for c in cases], write))
    write("manifest.json", dump_json(jsonable({"cases": manifest})))
    write("rng/streams.json", dump_json(export_rng()))
    write("calendar/countries.json", dump_json(export_countries(), compact=True))
    write("calendar/workdays.json", dump_json(jsonable(export_workdays())))
    write("calendar/sprints.json", dump_json(jsonable(export_sprint_calendar())))
    write("calendar/holidays-sample.json", dump_json(export_holidays_sample(), compact=True))
    write("calendar/holidays-digest.json", dump_json(export_holidays_digest()))


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*"))
            if p.is_file()}  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="compare only, write nothing")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "golden"
        generate(fresh)
        if args.check:
            have = {k: v for k, v in tree(GOLDEN).items() if k.startswith(("inputs/", "expected/"))}
            want = tree(fresh)
            problems = sorted(
                [f"missing: {k}" for k in want.keys() - have.keys()]
                + [f"obsolete: {k}" for k in have.keys() - want.keys()]
                + [f"differs: {k}" for k in want.keys() & have.keys() if want[k] != have[k]]
            )
            for line in problems:
                print(line, file=sys.stderr)
            if problems:
                print("golden/ is outdated: run scripts/golden.py", file=sys.stderr)
                return 1
            return 0
        for part in ("inputs", "expected"):
            shutil.rmtree(GOLDEN / part, ignore_errors=True)
            shutil.copytree(fresh / part, GOLDEN / part)
    print(f"golden/: {len(tree(GOLDEN / 'expected'))} reference files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
