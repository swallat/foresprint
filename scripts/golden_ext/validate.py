# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the data check (``foresprint.validate``) on deliberately damaged teams.

The base cases of ``golden.py`` have (almost) no findings. This extension takes the synthetic
teams ``people-days`` (people, sprints in the past), ``tickets-products`` (products, projects,
tickets, pre-planning, sprints around "today") and ``yaml-messy``, applies one damage to the
files of a copy and records what ``check_team`` and ``check_team_files`` report (or the load
error, if the damaged team does not load). Every ``t(...)`` message of ``validate.py`` is meant
to appear in at least one case (``tests`` of the Go port check that too).

Written to ``golden/inputs/validate/<case>/<team>/`` and ``golden/expected/validate/cases.json``.
The Go port is ``go/internal/validate``."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from foresprint import validate
from foresprint.model import Rule, rule_sources
from foresprint.storage import DataError, Repository, clear_team_cache

Files = dict[str, str]
Edit = Callable[[Files], None]

BASES = {
    "pd": ("people-days", date(2027, 1, 5)),
    "tp": ("tickets-products", date(2026, 7, 8)),
    "ym": ("yaml-messy", date(2026, 3, 1)),
}
SPRINT_PD = "sprints/2026.21.yaml"  # ended, has absences, velocity, commitment
SPRINT_TP = "sprints/2026.6.yaml"  # open or in the future relative to "today"
SPRINT_TP_PAST = "sprints/2026.2.yaml"


def dump(obj: Any) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=100)


def Y(path: str, fn: Callable[[Any], Any]) -> Edit:
    """Edit the YAML document of a file with ``fn``, which changes it in place."""

    def run(files: Files) -> None:
        obj = yaml.safe_load(files[path])
        fn(obj)
        files[path] = dump(obj)

    return run


def T(path: str, old: str, new: str) -> Edit:
    def run(files: Files) -> None:
        assert old in files[path], (path, old)
        files[path] = files[path].replace(old, new, 1)

    return run


def W(path: str, text: str) -> Edit:
    def run(files: Files) -> None:
        files[path] = text

    return run


def R(old: str, new_id: str) -> Edit:
    """Rename a sprint file and its id."""

    def run(files: Files) -> None:
        obj = yaml.safe_load(files.pop(old))
        obj["id"] = new_id
        files[f"sprints/{new_id}.yaml"] = dump(obj)

    return run


def D(path: str) -> Edit:
    def run(files: Files) -> None:
        del files[path]

    return run


def sprint_files(files: Files) -> list[str]:
    return sorted(p for p in files if p.startswith("sprints/"))


def S(path: str, **fields: Any) -> Edit:
    """Set top-level fields of a sprint file."""
    return Y(path, lambda d: d.update(fields))


def tm(**section: Any) -> Callable[[dict], None]:
    def run(d: dict) -> None:
        for dotted, value in section.items():
            *parents, last = dotted.split("__")
            node = d
            for p in parents:
                node = node.setdefault(p, {})
            node[last] = value

    return run


def TEAM(**section: Any) -> Edit:
    return Y("team.yaml", tm(**section))


CASES: list[tuple[str, str, list[Edit]]] = []


def case(name: str, base: str, *edits: Edit) -> None:
    CASES.append((name, base, list(edits)))


case("pristine-pd", "pd")
case("pristine-tp", "tp")
case("pristine-ym", "ym")

# --- team.yaml ------------------------------------------------------------------------------
case("ref-capacity-zero", "pd", TEAM(forecast__reference_capacity=0))
case("window-zero", "pd", TEAM(forecast__window=0))
case("roadmap-share-high", "pd", TEAM(forecast__roadmap_share=1.5))
case("roadmap-share-negative", "pd", TEAM(forecast__roadmap_share=-0.1))
case("overhead-share-one", "pd", TEAM(capacity__overhead_share=1))
case("country-unknown", "pd", TEAM(capacity__country="XX"))
case("region-wrong", "pd", TEAM(capacity__region="ZZ"))
case("workweek-unknown", "pd", TEAM(capacity__workweek="funday"))
case("absence-history-negative", "pd", TEAM(capacity__absence_history=-1))
case("overhead-days-negative", "pd", TEAM(capacity__overhead_days=-2))
case("length-days-zero", "pd", TEAM(sprint__length_days=0))
case(
    "no-sprints-no-first",
    "pd",
    *[D(p) for p in (f"sprints/2026.{n}.yaml" for n in range(14, 28))],
    Y("team.yaml", lambda d: d["sprint"].pop("first")),
)
case(
    "no-sprint-files",
    "pd",
    *[D(p) for p in (f"sprints/2026.{n}.yaml" for n in range(14, 28))],
)
case(
    "numbering-mismatch",
    "pd",
    TEAM(sprint__numbering="sequential"),
    R("sprints/2026.27.yaml", "S27"),
)
case(
    "numbering-mismatch-two-sprints",
    "pd",
    TEAM(sprint__numbering="sequential"),
    R("sprints/2026.27.yaml", "S27"),
    R("sprints/2026.26.yaml", "S26"),
)
case(
    "numbering-mismatch-first",
    "pd",
    *[D(p) for p in (f"sprints/2026.{n}.yaml" for n in range(14, 28))],
    TEAM(sprint__numbering="sequential", sprint__first__id="S1"),
)

# --- people.yaml ----------------------------------------------------------------------------
case("person-duplicate", "pd", Y("people.yaml", lambda d: d["people"].append(dict(d["people"][0]))))
case(
    "person-no-membership", "pd", Y("people.yaml", lambda d: d["people"][0].update(memberships=[]))
)
case(
    "fte-too-high",
    "pd",
    Y("people.yaml", lambda d: d["people"][0]["memberships"][0].update(fte=1.5)),
)
case(
    "fte-negative",
    "pd",
    Y("people.yaml", lambda d: d["people"][0]["memberships"][0].update(fte=-1)),
)
case(
    "membership-ends-before-start",
    "pd",
    Y("people.yaml", lambda d: d["people"][0]["memberships"][0].update(to=date(2024, 1, 1))),
)
case(
    "memberships-overlap",
    "pd",
    Y("people.yaml", lambda d: d["people"][1]["memberships"][1].update({"from": date(2026, 8, 1)})),
)
case(
    "memberships-open-then-more",
    "pd",
    Y(
        "people.yaml",
        lambda d: d["people"][0]["memberships"].append(
            {"from": date(2026, 6, 1), "to": None, "fte": 1}
        ),
    ),
)
case(
    "person-workweek-unknown", "pd", Y("people.yaml", lambda d: d["people"][0].update(workweek="x"))
)
case(
    "person-country-unknown", "pd", Y("people.yaml", lambda d: d["people"][0].update(country="XX"))
)
case(
    "person-region-wrong",
    "pd",
    Y("people.yaml", lambda d: d["people"][0].update(country="DE", region="ZZ")),
)
case(
    "person-region-wrong-team-country",
    "pd",
    Y("people.yaml", lambda d: d["people"][0].update(region="ZZ")),
)

# --- sprint files (people-days, in the past) ------------------------------------------------
case("sprint-end-before-start", "pd", S(SPRINT_PD, end=date(2026, 10, 1)))
case("sprint-overlap", "pd", S(SPRINT_PD, start=date(2026, 10, 1)))
case("sprint-gap", "pd", S(SPRINT_PD, start=date(2026, 10, 12), end=date(2026, 10, 26)))
case("expected-absences-unknown-person", "pd", S(SPRINT_PD, expected_absences={"nobody": 1}))
case("expected-absences-negative", "pd", S(SPRINT_PD, expected_absences={"anna": -1}))
case("absences-unknown-person", "pd", S(SPRINT_PD, absences={"nobody": 1}))
case("absences-negative", "pd", S(SPRINT_PD, absences={"anna": -1}))
case("absences-too-many", "pd", S(SPRINT_PD, absences={"anna": 11.5}))
case(
    "absences-not-member",
    "pd",
    S(SPRINT_PD, absences={"dana": 1}),
    Y(
        "people.yaml",
        lambda d: d["people"][3]["memberships"][0].update({"from": date(2026, 11, 1)}),
    ),
)
case("negative-not-done", "pd", S(SPRINT_PD, not_done=-1))
case("negative-additional-done", "pd", S(SPRINT_PD, additional_done=-1))
case("negative-production-planned", "pd", S(SPRINT_PD, production_planned=-1))
case("negative-production-done", "pd", S(SPRINT_PD, production_done=-1))
case("negative-capacity", "pd", S(SPRINT_PD, capacity=-1))
case("negative-commitment", "pd", S(SPRINT_PD, forecast_ist=-1))
case("negative-velocity", "pd", S(SPRINT_PD, velocity=-1))
case("negative-forecast-plan", "pd", S(SPRINT_PD, forecast_plan=-1))
case("production-above-commitment", "pd", S(SPRINT_PD, production_planned=40, forecast_ist=31))
case(
    "sum-mismatch", "pd", S(SPRINT_PD, forecast_ist=30, not_done=5, additional_done=1, velocity=30)
)
case("sum-matches", "pd", S(SPRINT_PD, forecast_ist=30, not_done=5, additional_done=1, velocity=26))
case("scope-creep-percentage", "pd", S(SPRINT_PD, scope_creep=15))
case("capacity-zero", "pd", S(SPRINT_PD, capacity=0))
case("velocity-double", "pd", S(SPRINT_PD, velocity=100, forecast_ist=31))
case("ended-no-velocity", "pd", S(SPRINT_PD, velocity=None))
case("ended-no-capacity-frozen", "pd", S(SPRINT_PD, capacity=None, velocity=30))

# --- sprint files (tickets-products, open and future) ---------------------------------------
case(
    "planning-differs",
    "tp",
    S(SPRINT_TP, forecast_ist=40, planning={"carryover": 10, "backlog": 20}),
)
case(
    "planning-corrections",
    "tp",
    S(
        SPRINT_TP,
        forecast_ist=30,
        planning={"carryover": 10, "backlog": 20, "corrections": [20, 15]},
    ),
)
case("planning-ok", "tp", S(SPRINT_TP, forecast_ist=30, planning={"carryover": 10, "backlog": 20}))
case(
    "sprint-products-unknown",
    "tp",
    S(SPRINT_TP, products={"ghost": {"planned": 5}}),
)
case(
    "sprint-products-inactive",
    "tp",
    S(SPRINT_TP, start=date(2026, 9, 1), end=date(2026, 9, 15), products={"old": {"planned": 5}}),
)
case(
    "sprint-products-negative",
    "tp",
    S(
        SPRINT_TP,
        products={
            "web": {
                "planned": -1,
                "done": -2,
                "preplanned": -3,
                "production_planned": -4,
                "production_done": -5,
            }
        },
    ),
)
case(
    "sprint-products-production-large",
    "tp",
    S(
        SPRINT_TP,
        products={"web": {"planned": 5, "production_planned": 9, "done": 3, "production_done": 4}},
    ),
)
case(
    "sprint-products-exceed-commitment",
    "tp",
    S(SPRINT_TP, forecast_ist=10, products={"web": {"planned": 8}, "app": {"planned": 7}}),
)
case(
    "sprint-products-exceed-velocity",
    "tp",
    S(SPRINT_TP_PAST, velocity=10, products={"web": {"done": 8}, "app": {"done": 7}}),
)

# --- products.yaml --------------------------------------------------------------------------
case(
    "product-duplicate",
    "tp",
    Y("products.yaml", lambda d: d["products"].append(dict(d["products"][0]))),
)
case("product-share-zero", "tp", Y("products.yaml", lambda d: d["products"][0].update(share=0)))
case("product-share-high", "tp", Y("products.yaml", lambda d: d["products"][0].update(share=1.5)))
case(
    "product-period-reversed",
    "tp",
    Y(
        "products.yaml",
        lambda d: d["products"][2].update({"from": date(2026, 9, 1), "to": date(2026, 8, 1)}),
    ),
)
case(
    "product-shares-over-100",
    "tp",
    Y("products.yaml", lambda d: d["products"][1].update(share=0.7)),
)
case(
    "product-shares-exactly-100",
    "tp",
    Y("products.yaml", lambda d: d["products"][1].update(share=0.5)),
)
case(
    "product-shares-all-fixed",
    "tp",
    Y("products.yaml", lambda d: [p.update(share=0.25) for p in d["products"]]),
)

# --- projects.yaml --------------------------------------------------------------------------
case(
    "project-duplicate",
    "tp",
    Y("projects.yaml", lambda d: d["projects"].append(dict(d["projects"][0]))),
)
case(
    "project-no-product", "tp", Y("projects.yaml", lambda d: d["projects"][0].update(product=None))
)
case(
    "project-unknown-product",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(product="zzz")),
)
case(
    "project-product-ended",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(product="old")),
    Y("products.yaml", lambda d: d["products"][2].update(to=date(2026, 6, 1))),
)
case("project-product-with-feature-off", "tp", TEAM(features__products=False))
case(
    "project-target-missing",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(target=None)),
)
case(
    "project-target-past",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(target=date(2026, 1, 1))),
)
case("project-no-match", "tp", Y("projects.yaml", lambda d: d["projects"][0].pop("match")))
case(
    "project-no-match-no-tickets",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].pop("match")),
    Y("tickets.yaml", lambda d: [t.update(project=None) for t in d["tickets"]] and None),
)
case(
    "project-rule-unknown-source",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(match={"any": [{"colour": ["red"]}]})),
)
case(
    "project-rule-empty-values",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(match={"any": [{"epic": []}]})),
)
case(
    "project-rule-empty-operator",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(match={"all": []})),
)
case(
    "project-rule-mixed-forms",
    "tp",
    Y(
        "projects.yaml",
        lambda d: d["projects"][0].update(match={"epic": ["A"], "all": [{"label": ["x"]}]}),
    ),
)
case(
    "project-rule-long-form",
    "tp",
    Y(
        "projects.yaml",
        lambda d: d["projects"][0].update(
            match={"all": [{"epic": ["A"]}, {"none": [{"label": ["x"]}]}]}
        ),
    ),
)
case(
    "product-rule-invalid",
    "tp",
    Y("products.yaml", lambda d: d["products"][0].update(match={"any": [{"colour": ["red"]}]})),
)

# --- tickets.yaml ---------------------------------------------------------------------------
case(
    "ticket-duplicate-key",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"].append(dict(d["tickets"][0]))),
)
case(
    "ticket-estimate-negative",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"][0].update(estimate=-1)),
)
case(
    "ticket-remaining-negative",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"][0].update(remaining=-1)),
)
case(
    "ticket-unknown-project",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"][0].update(project="nope")),
)
case(
    "ticket-unknown-sprint",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"][0].update(in_sprint="1999.1")),
)
case(
    "ticket-known-future-sprint",
    "tp",
    Y("tickets.yaml", lambda d: d["tickets"][0].update(in_sprint="2026.12")),
)
case(
    "ticket-cycle",
    "tp",
    Y(
        "tickets.yaml",
        lambda d: (
            d["tickets"][0].update(depends_on=["W-2"]),
            d["tickets"][1].update(depends_on=["W-1"]),
        ),
    ),
)
case(
    "ticket-cycle-three-and-self",
    "tp",
    Y(
        "tickets.yaml",
        lambda d: (
            d["tickets"][0].update(depends_on=["W-2"]),
            d["tickets"][1].update(depends_on=["W-3"]),
            d["tickets"][2].update(depends_on=["W-1"]),
            d["tickets"][3].update(depends_on=["W-4", "OUTSIDE"]),
        ),
    ),
)

# --- preplan.yaml ---------------------------------------------------------------------------
case(
    "earmark-twice", "tp", Y("preplan.yaml", lambda d: d["earmarks"].append(dict(d["earmarks"][0])))
)
case(
    "earmark-unknown-ticket",
    "tp",
    Y("preplan.yaml", lambda d: d["earmarks"].append({"ticket": "ZZ-1", "sprint": "2026.9"})),
)
case(
    "earmark-unknown-sprint",
    "tp",
    Y("preplan.yaml", lambda d: d["earmarks"].append({"ticket": "W-5", "sprint": "1999.1"})),
)
case(
    "earmark-past-sprint",
    "tp",
    Y("preplan.yaml", lambda d: d["earmarks"].append({"ticket": "W-5", "sprint": "2026.1"})),
)
case(
    "estimate-twice",
    "tp",
    Y("preplan.yaml", lambda d: d["estimates"].append(dict(d["estimates"][0]))),
)
case(
    "estimate-unknown-ticket",
    "tp",
    Y("preplan.yaml", lambda d: d["estimates"].append({"ticket": "ZZ-1", "estimate": 3})),
)
case(
    "estimate-missing",
    "tp",
    Y("preplan.yaml", lambda d: d["estimates"].append({"ticket": "W-5", "estimate": None})),
)
case(
    "estimate-negative",
    "tp",
    Y("preplan.yaml", lambda d: d["estimates"].append({"ticket": "W-5", "estimate": -3})),
)

# --- tracker settings -----------------------------------------------------------------------
case("tracker-kind-unknown", "tp", TEAM(tracker__kind="bugzilla"))
case("tracker-jira-empty", "tp", TEAM(tracker__kind="jira"))
case(
    "tracker-jira-ok",
    "tp",
    TEAM(
        tracker__kind="jira",
        tracker__base_url="https://jira.example.org",
        tracker__query="project = X",
        tracker__fields={"estimate": "Story Points"},
    ),
)
case(
    "tracker-jira-http",
    "tp",
    TEAM(
        tracker__kind="jira",
        tracker__base_url="http://jira.example.org",
        tracker__query="project = X",
    ),
)
case(
    "tracker-jira-url-invalid",
    "tp",
    TEAM(tracker__kind="jira", tracker__base_url="ftp://x", tracker__query="q"),
)
case(
    "tracker-jira-url-credentials",
    "tp",
    TEAM(
        tracker__kind="jira",
        tracker__base_url="https://user:pw@jira.example.org",
        tracker__query="q",
    ),
)
case(
    "tracker-jira-url-extra",
    "tp",
    TEAM(
        tracker__kind="jira", tracker__base_url="https://jira.example.org/?a=1", tracker__query="q"
    ),
)
case("tracker-dependency-gap", "tp", TEAM(tracker__dependency_gap=2))
case("tracker-rough-factor", "tp", TEAM(tracker__rough_factor=0))
case("tracker-link-type-empty", "tp", TEAM(tracker__link_type=""))
case("tracker-match-order-unknown", "tp", TEAM(tracker__project_match_order=["epic", "colour"]))
case("tracker-match-order-twice", "tp", TEAM(tracker__project_match_order=["epic", "epic"]))
case("tracker-rule-field-name", "tp", TEAM(tracker__rule_fields={"Bad Name": "x"}))
case("tracker-rule-field-fixed", "tp", TEAM(tracker__rule_fields={"epic": "Epic"}))
case("tracker-rule-field-keyword", "tp", TEAM(tracker__rule_fields={"and": "x"}))
case("tracker-rule-field-contains", "tp", TEAM(tracker__rule_fields={"x_contains": "x"}))
case("tracker-rule-field-empty", "tp", TEAM(tracker__rule_fields={"team": " "}))
case(
    "tracker-refined-also-if-invalid",
    "tp",
    TEAM(tracker__refined_also_if={"any": [{"colour": ["red"]}]}),
)
case(
    "tracker-rule-field-in-rule",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(match={"any": [{"team": ["red"]}]})),
)
case(
    "tracker-raw-unreadable-feature-off",
    "tp",
    TEAM(features__tickets=False, tracker__kind=["not", "a", "text"], tracker__fields="oops"),
)
case("tracker-secret-in-file", "tp", TEAM(tracker__token="abc"))
case(
    "tickets-feature-off-with-damage",
    "tp",
    TEAM(features__tickets=False),
    Y("tickets.yaml", lambda d: d["tickets"][0].update(estimate=-1)),
)

# --- files that do not load -----------------------------------------------------------------
case("load-team-missing", "pd", D("team.yaml"))
case("load-people-broken", "pd", W("people.yaml", "people: [oops\n"))
case("load-sprint-missing-field", "pd", Y(SPRINT_PD, lambda d: d.pop("end")))
case("load-sprint-float-id", "pd", W(SPRINT_PD, "id: 2026.2\nstart: 2026-10-07\nend: 2026-10-21\n"))
case("load-first-id-float", "pd", T("team.yaml", "id: '2026.14'", "id: 2026.14"))
case("load-team-not-a-mapping", "pd", W("team.yaml", "- a\n- b\n"))
case("load-bad-date", "pd", T(SPRINT_PD, "start: 2026-10-07", "start: yesterday"))
case("load-bad-number", "pd", T(SPRINT_PD, "velocity: 30", "velocity: lots"))
case(
    "load-conflict-markers",
    "pd",
    T("team.yaml", "unit: PT", "<<<<<<< HEAD\nunit: PT\n=======\nunit: SP\n>>>>>>> other"),
)

# --- silent assumptions in the YAML text (check_yaml_text) ----------------------------------
case(
    "yaml-duplicate-key",
    "pd",
    T("team.yaml", "unit: PT", "unit: PT\nunit: PT"),
)
case(
    "yaml-duplicate-key-nested",
    "pd",
    T("team.yaml", "  window: 5", "  window: 5\n  window: 6"),
)
case(
    "yaml-duplicate-in-flow",
    "pd",
    T(SPRINT_PD, "absences:\n  dana: 1", "absences: {dana: 1, dana: 2}"),
)
case(
    "yaml-empty-number-fte",
    "pd",
    T("people.yaml", "    fte: 1\n  - from: 2026-09-01", "    fte:\n  - from: 2026-09-01"),
)
case("yaml-empty-absence", "pd", T(SPRINT_PD, "  dana: 1", "  dana:"))
case("yaml-empty-quoted", "pd", T(SPRINT_PD, "  dana: 1", "  dana: ''"))
case("yaml-empty-intentional", "pd", T(SPRINT_PD, "capacity: null", "capacity:"))
case(
    "yaml-empty-planning",
    "tp",
    S(SPRINT_TP, planning={"carryover": None, "backlog": None, "corrections": [None, 2]}),
)
case(
    "yaml-empty-project-priority",
    "tp",
    Y("projects.yaml", lambda d: d["projects"][0].update(priority=None)),
)
case(
    "yaml-empty-prognosis",
    "tp",
    S(SPRINT_TP, prognoses=[{"at": "2026-07-01 10:00:00", "preplanned": {}}]),
)
case(
    "yaml-duplicate-in-tickets",
    "tp",
    T("tickets.yaml", "  title: Ticket W-1", "  title: Ticket W-1\n  title: Ticket W-1b"),
)
case(
    "yaml-merge-key",
    "pd",
    T("team.yaml", "capacity:\n", "base: &b\n  window: 7\ncapacity:\n  <<: *b\n"),
)
case(
    "yaml-anchors-and-duplicates",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\nabsences:\n  dana: 1\n  dana: 2\n"
        "velocity: 30\ncapacity: 40\nforecast_ist: 31\nforecast_ist: 32\n",
    ),
)
case(
    "yaml-key-types",
    "pd",
    T("team.yaml", "unit: PT", "unit: PT\n1: a\n'1': b\ntrue: c\n"),
)
case(
    "yaml-tab-and-crlf",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\r\nstart: 2026-10-07\r\nend: 2026-10-21\r\nvelocity: 30\r\nvelocity: 31\r\n",
    ),
)
case(
    "yaml-duplicate-many-lines",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\n"
        "velocity: 30\nvelocity: 31\nvelocity: 32\nvelocity: 33\n",
    ),
)
case(
    "yaml-many-notes",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\n"
        + "".join(f"k{i}: 1\nk{i}: 2\n" for i in range(60)),
    ),
)
case(
    "yaml-many-lines",
    "pd",
    W(SPRINT_PD, "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\n" + "velocity: 1\n" * 13),
)
case(
    "yaml-anchor-bomb",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\nx:\n"
        "  - &a0 [0, 0, 0, 0, 0, 0, 0, 0, 0]\n"
        + "".join(
            f"  - &a{i} [{', '.join(f'*a{i - 1}' for _ in range(9))}]\n" for i in range(1, 7)
        ),
    ),
)
case(
    "yaml-too-large",
    "pd",
    W(
        SPRINT_PD,
        "id: '2026.21'\nstart: 2026-10-07\nend: 2026-10-21\nx: [" + ",".join(["0"] * 50100) + "]\n",
    ),
)
case("yaml-parse-error", "pd", T("team.yaml", "unit: PT", "unit: [PT"))


# --- direct cases: YAML text, rules, cycles ------------------------------------------------------

YAML_TEXTS: list[tuple[str, str]] = [
    ("empty", ""),
    ("comment-only", "# nothing\n"),
    ("scalar-document", "just text\n"),
    ("plain", "a: 1\nb:\n  - c: 2\n    d: 3\n"),
    ("duplicate", "a: 1\nb: 2\na: 3\n"),
    ("duplicate-three", "a: 1\na: 2\na: 3\n"),
    ("duplicate-nested", "x:\n  a: 1\n  a: 2\ny:\n  - k: 1\n    k: 2\n"),
    ("duplicate-flow", "x: {a: 1, a: 2, b: 3, b: 4}\n"),
    ("duplicate-flow-multiline", "x: {a: 1,\n  a: 2}\n"),
    ("duplicate-in-sequence-of-maps", "- a: 1\n  a: 2\n- b: 1\n  b: 2\n"),
    ("duplicate-twelve", "a: 0\n" * 12),
    ("duplicate-fifty-five-notes", "".join(f"k{i}: 1\nk{i}: 2\n" for i in range(55))),
    ("keys-int-and-string", "1: a\n'1': b\n"),
    ("keys-int-and-float", "1: a\n1.0: b\n"),
    ("keys-int-and-bool", "1: a\ntrue: b\n"),
    ("keys-bool-spellings", "yes: a\nTrue: b\non: c\n"),
    ("keys-null-spellings", "null: a\n~: b\nNull: c\n"),
    ("keys-number-spellings", "16: a\n0x10: b\n0o20: c\n020: d\n1_6: e\n"),
    ("keys-exponent", "1e3: a\n1000.0: b\n1.0e+3: c\n"),
    ("keys-timestamp", "2026-01-01: a\n2026-01-01: b\n2026-1-1: c\n"),
    ("keys-explicit-tags", "!!str 1: a\n'1': b\n1: c\n"),
    ("keys-complex", "? [a, b]\n: 1\n? [a, b]\n: 2\n"),
    ("keys-mapping-key", "? {a: 1}\n: 1\n? {a: 1}\n: 2\n"),
    ("keys-unicode", "grün: 1\ngrün: 2\n日本: 1\n"),
    ("keys-control-characters", '"a\\x07b": 1\n"a\\x07b": 2\n"c\\nd": 1\n"c\\nd": 2\n'),
    ("keys-bidi", '"a\\u202eb": 1\n"a\\u202eb": 2\n'),
    ("products-str-keyed", "products:\n  1: {planned: 1}\n  '1': {planned: 2}\n"),
    ("products-int-float", "products:\n  1: {planned: 1}\n  1.0: {planned: 2}\n"),
    ("absences-str-keyed", "absences:\n  1: 1\n  '1': 2\n  true: 3\n  True: 4\n"),
    ("expected-absences-str-keyed", "expected_absences:\n  7: 1\n  '7': 2\n"),
    (
        "prognoses-preplanned-str-keyed",
        "prognoses:\n- at: x\n  preplanned:\n    1: 1\n    '1': 2\n",
    ),
    ("sprint-names-str-keyed", "tracker:\n  sprint_names:\n    10: a\n    '10': b\n"),
    ("not-str-keyed-elsewhere", "other:\n  1: 1\n  '1': 2\n"),
    ("merge-simple", "base: &b {a: 1}\nx:\n  <<: *b\n  a: 2\n"),
    ("merge-duplicate-explicit", "base: &b {a: 1}\nx:\n  <<: *b\n  c: 1\n  c: 2\n"),
    (
        "merge-two-merges",
        "a: &a {k: 1, only_a: 1}\nb: &b {k: 2, only_b: 1}\nx:\n  <<: *a\n  <<: *b\n",
    ),
    ("merge-list", "a: &a {k: 1, only_a: 1}\nb: &b {k: 2, only_b: 1}\nx:\n  <<: [*a, *b]\n"),
    ("merge-nested", "a: &a {k: 1}\nb: &b\n  <<: *a\n  j: 1\nx:\n  <<: *b\n"),
    ("merge-inherited-empty", "base: &b {fte: }\npeople:\n- memberships:\n  - <<: *b\n"),
    ("merge-cycle", "a: &a\n  <<: *a\n  k: 1\n"),
    ("merge-non-mapping", "a: &a [1, 2]\nx:\n  <<: *a\n"),
    ("anchor-reuse", "a: &a {fte: }\nmemberships: [*a]\n"),
    ("anchor-reuse-people", "x: &m {fte: }\npeople:\n- memberships: [*m]\n- memberships: [*m]\n"),
    ("anchor-duplicate-reported-once", "d: &d {k: 1, k: 2}\nx: *d\ny: *d\n"),
    ("alias-to-parent", "a: &x\n  b: *x\n"),
    ("empty-fte", "people:\n- id: a\n  memberships:\n  - from: 2025-01-01\n    to:\n    fte:\n"),
    (
        "empty-fte-spellings",
        "people:\n- memberships:\n  - fte: ~\n  - fte: null\n  - fte: ''\n"
        '  - fte: ""\n  - fte: Null\n'
        "  - fte: NULL\n  - fte: 0\n  - fte: '0'\n  - fte: ' '\n",
    ),
    ("empty-planning", "planning:\n  carryover:\n  backlog: ~\n  corrections:\n  - \n  - 1\n  -\n"),
    ("empty-planning-flow", "planning: {carryover: , backlog: , corrections: [, 1]}\n"),
    ("empty-planning-not-a-number-field", "planning:\n  note:\n"),
    ("empty-absences", "absences:\n  anna:\n  ben: 1\n  cem: ''\n"),
    ("empty-expected-absences", "expected_absences:\n  anna:\n"),
    ("empty-preplanned", "prognoses:\n- at: x\n  preplanned:\n    web:\n    app: 1\n"),
    ("empty-priority", "projects:\n- id: a\n  priority:\n- id: b\n  priority: 1\n"),
    (
        "empty-intentional-fields",
        "to:\ncapacity:\nforecast_ist:\nregion:\nmatch:\nnote:\nproducts:\n",
    ),
    ("empty-wrong-depth", "people:\n- fte:\n  memberships:\n    fte:\n"),
    ("empty-with-tag", "absences:\n  anna: !!null\n  ben: !!str\n"),
    ("empty-in-merged", "base: &b {anna: }\nabsences:\n  <<: *b\n"),
    ("multi-document", "a: 1\n---\nb: 2\n"),
    ("invalid", "a: [1\n"),
    ("tab-indent", "a:\n\tb: 1\n"),
    ("crlf", "a: 1\r\na: 2\r\n"),
    ("bom", "\ufeffa: 1\na: 2\n"),
    ("long-key-path", "a:\n  b:\n    c:\n      d:\n        e: 1\n        e: 2\n"),
    ("path-with-sequence-index", "a:\n- - x: 1\n    x: 2\n"),
    ("path-key-with-dot", "a.b:\n  c: 1\n  c: 2\n"),
    ("path-key-int", "a:\n  1:\n    k: 1\n    k: 2\n"),
    ("deep-nesting-ok", "a: " + "[" * 200 + "]" * 200 + "\nb: 1\nb: 2\n"),
]


def YAML_TEXT_CASES() -> list[dict[str, Any]]:
    return [
        {"name": n, "text": t, "issues": validate.check_yaml_text(t, "x.yaml")}
        for n, t in YAML_TEXTS
    ]


def _rule(
    op: str = "leaf",
    source: str | None = None,
    values: list[str] | None = None,
    children: list[Rule] | None = None,
    short: bool = False,
    contains: bool = False,
) -> Rule:
    return Rule(
        op=op,
        source=source,
        values=values or [],
        children=children or [],
        short=short,
        contains=contains,
    )


def _leaf(source: str, *values: str) -> Rule:
    return _rule(source=source, values=list(values))


RULES: list[tuple[str, Rule]] = [
    ("leaf-ok", _leaf("epic", "A")),
    ("leaf-unknown-source", _leaf("colour", "red")),
    ("leaf-no-values", _rule(source="epic")),
    ("leaf-unknown-and-empty", _rule(source="colour")),
    ("leaf-source-none", _rule(source=None, values=["x"])),
    ("all-ok", _rule("all", children=[_leaf("epic", "A"), _leaf("label", "b")])),
    ("all-empty", _rule("all")),
    ("none-empty", _rule("none")),
    ("any-empty", _rule("any")),
    ("short-empty", _rule("any", short=True)),
    ("short-ok", _rule("any", short=True, children=[_leaf("epic", "A"), _leaf("label", "b")])),
    (
        "short-mixed",
        _rule(
            "any",
            short=True,
            children=[_leaf("epic", "A"), _rule("all", children=[_leaf("label", "b")])],
        ),
    ),
    (
        "nested",
        _rule(
            "all",
            children=[_rule("none", children=[_leaf("colour", "r"), _rule("any")]), _leaf("epic")],
        ),
    ),
    (
        "short-inside-long",
        _rule("all", children=[_rule("any", short=True, children=[_leaf("epic", "A")])]),
    ),
    ("configured-source", _leaf("customer", "Acme")),
]

CYCLES: list[tuple[str, dict[str, list[str]]]] = [
    ("none", {"A": [], "B": ["A"]}),
    ("self", {"A": ["A"]}),
    ("two", {"A": ["B"], "B": ["A"]}),
    ("three-rotated", {"C": ["A"], "A": ["B"], "B": ["C"]}),
    ("two-cycles", {"A": ["B"], "B": ["A"], "X": ["Y"], "Y": ["Z"], "Z": ["X"]}),
    ("shared-node", {"A": ["B", "C"], "B": ["A"], "C": ["A"]}),
    ("outside-key", {"A": ["OUT"], "B": ["A", "OUT2"]}),
    ("figure-eight", {"A": ["B"], "B": ["A", "C"], "C": ["B"]}),
    ("tail-into-cycle", {"T": ["A"], "A": ["B"], "B": ["A"]}),
    ("diamond", {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}),
    ("long-chain-cycle", {str(i): [str((i + 1) % 30)] for i in range(30)}),
    ("keys-order", {"b": ["a"], "a": ["b"], "z": []}),
]


def RULE_CASES() -> dict[str, Any]:
    from foresprint.model import Ticket

    sources = rule_sources({"customer": "Customer"})
    return {
        "sources": list(sources),
        "problems": [
            {
                "name": n,
                "tree": r,
                "problems": validate.rule_problems(r),
                "with_configured": validate.rule_problems(r, sources),
            }
            for n, r in RULES
        ],
        "cycles": [
            {
                "name": n,
                "depends_on": g,
                "cycles": validate.find_cycles([Ticket(key=k, depends_on=v) for k, v in g.items()]),
            }
            for n, g in CYCLES
        ],
    }


def read_tree(folder: Path) -> Files:
    files: Files = {}
    for path in sorted(folder.rglob("*.yaml")):
        files[path.relative_to(folder).as_posix()] = path.read_text(encoding="utf-8")
    return files


def generate(ctx) -> None:
    """Per case only the files that differ from the base team are stored (``overrides``,
    below ``golden/inputs/validate/<case>/``) and the ones removed (``deleted``); a test builds
    the team folder from the base folder and these."""
    by_name = {c.name: c for c in ctx.resolved}
    out = []
    for name, base, edits in CASES:
        case_name, today = BASES[base]
        source = by_name[case_name]
        original = read_tree(Path(source.root) / source.team)
        files = dict(original)
        for edit in edits:
            edit(files)
        changed = {p: t for p, t in files.items() if original.get(p) != t}
        deleted = sorted(set(original) - set(files))
        target = ctx.out / "inputs" / "validate" / name
        for path, text in changed.items():
            dest = target / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8", newline="")
        entry: dict[str, Any] = {
            "name": name,
            "base": case_name,
            "team": source.team,
            "today": today,
            "overrides": sorted(changed),
            "deleted": deleted,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "t"
            folder = root / source.team
            for path, text in files.items():
                dest = folder / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8", newline="")
            clear_team_cache()
            try:
                data = Repository(root).load(source.team)
            except DataError as err:
                message = str(err).replace(str(root), "<data>")
                entry["load_error"] = message
                entry["issues"] = [validate.Issue(validate.Level.ERROR, source.team, message)]
            else:
                entry["issues"] = validate.check_team(data, today) + validate.check_team_files(
                    folder, data.team.features.tickets
                )
        out.append(entry)
    ctx.write(
        "validate/cases.json",
        ctx.dump_json(
            ctx.jsonable({"cases": out, "yaml_text": YAML_TEXT_CASES(), "rules": RULE_CASES()})
        ),
    )
