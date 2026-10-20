# SPDX-License-Identifier: EUPL-1.2
"""Rule language of the assignment (spec 6.4): short form, any/all/none, nesting, reading and
writing, invalid rules in the check."""

from datetime import date
from pathlib import Path

import pytest

from sprintforecast.model import RULE_SOURCES, Project, Rule, Ticket
from sprintforecast.storage import Repository, _rule_from, _rule_to
from sprintforecast.validate import Level, check_team, rule_problems

TODAY = date(2026, 10, 15)


def facts(**values: list[str] | str) -> dict[str, list[str]]:
    return {k: [v] if isinstance(v, str) else v for k, v in values.items()}


def parse(raw: dict) -> Rule:
    rule = _rule_from(raw, "projects.yaml: p: match")
    assert rule is not None
    return rule


# --- Evaluation -----------------------------------------------------------------------------


def test_short_form_is_an_or_of_leaves():
    rule = parse({"epic": ["ABC-100", "ABC-101"], "label": ["payment"]})
    assert rule.op == "any" and rule.short
    assert rule.matches(facts(epic="ABC-101"))
    assert rule.matches(facts(label=["other", "payment"]))
    assert not rule.matches(facts(epic="ABC-999", label=["other"]))
    assert not rule.matches({})
    assert rule.leaf_sources() == {"epic", "label"}
    assert rule.matched_sources(facts(epic="ABC-100", label=["payment"])) == {"epic", "label"}
    assert rule.matched_sources(facts(label=["payment"])) == {"label"}


def test_long_form_any_all_none():
    any_rule = parse({"any": [{"epic": ["A"]}, {"status": ["Ready"]}]})
    assert any_rule.matches(facts(status="Ready")) and not any_rule.matches(facts(status="x"))
    all_rule = parse({"all": [{"epic": ["A"]}, {"status": ["Ready"]}]})
    assert all_rule.matches(facts(epic="A", status="Ready"))
    assert not all_rule.matches(facts(epic="A"))
    none_rule = parse({"none": [{"label": ["maintenance", "hotfix"]}]})
    assert none_rule.matches(facts(label=["payment"])) and none_rule.matches({})
    assert not none_rule.matches(facts(label=["hotfix"]))
    assert none_rule.matched_sources(facts(label=["payment"])) == set()


def test_nesting_as_in_the_specification():
    rule = parse(
        {
            "all": [
                {"component": ["Database"]},
                {"none": [{"label": ["maintenance", "hotfix"]}]},
                {"any": [{"epic": ["ABC-200"]}, {"status": ["Ready"]}]},
            ]
        }
    )
    assert rule.op == "all" and not rule.short
    assert rule.matches(facts(component="Database", epic="ABC-200"))
    assert rule.matches(facts(component="Database", status="Ready", label=["x"]))
    assert not rule.matches(facts(component="Database", epic="ABC-200", label=["hotfix"]))
    assert not rule.matches(facts(component="Frontend", epic="ABC-200"))
    assert not rule.matches(facts(component="Database"))
    assert rule.leaf_sources() == {"component", "label", "epic", "status"}
    assert rule.matched_sources(facts(component="Database", status="Ready")) == {
        "component",
        "status",
    }


def test_ticket_facts_feed_the_rules():
    ticket = Ticket(
        key="ABC-1",
        status="In Progress",
        issue_type="Story",
        in_sprint="2026.22",
        epic="ABC-100",
        labels=["payment"],
        components=["Checkout", "Database"],
    )
    assert ticket.facts() == {
        "epic": ["ABC-100"],
        "component": ["Checkout", "Database"],
        "label": ["payment"],
        "status": ["In Progress"],
        "issue_type": ["Story"],
        "in_sprint": ["true", "2026.22"],
    }
    assert parse({"in_sprint": [True]}).matches(ticket.facts())
    assert parse({"in_sprint": ["2026.22"]}).matches(ticket.facts())
    assert parse({"in_sprint": [False]}).matches(Ticket(key="ABC-2").facts())
    assert not parse({"in_sprint": [True]}).matches(Ticket(key="ABC-2").facts())
    # The spec's `status_not: [To Do]` is written as none: [{status: [...]}].
    refined = parse({"any": [{"in_sprint": [True]}, {"none": [{"status": ["To Do"]}]}]})
    assert refined.matches(ticket.facts())
    assert not refined.matches(Ticket(key="ABC-3", status="To Do").facts())
    assert refined.matches(Ticket(key="ABC-4", status="Ready").facts())


# --- Reading and writing --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        {"epic": ["ABC-100", "ABC-101"], "label": ["payment"]},
        {"any": [{"epic": ["A"]}, {"status": ["Ready"]}]},
        {
            "all": [
                {"component": ["Database"]},
                {"none": [{"label": ["maintenance", "hotfix"]}]},
                {"any": [{"epic": ["ABC-200"]}, {"status": ["Ready"]}]},
            ]
        },
        {"any": [{"in_sprint": [True]}, {"none": [{"status": ["To Do"]}]}]},
        {"in_sprint": [False, "2026.22"]},
        # Kept as written so that the validation can name the problems.
        {"epic": [], "lable": ["x"]},
        {"all": []},
        {"epic": ["A"], "any": [{"label": ["x"]}]},
    ],
)
def test_rules_round_trip(raw: dict):
    assert _rule_to(parse(raw)) == raw


def test_scalars_and_empty_rules():
    assert _rule_from(None, "x") is None
    assert _rule_from({}, "x") is None
    # A single source is the leaf itself; several sources are OR-combined (short form).
    assert parse({"epic": "ABC-1"}) == Rule(source="epic", values=["ABC-1"])
    assert parse({"epic": None}) == Rule(source="epic", values=[])
    assert parse({"in_sprint": [True]}) == Rule(source="in_sprint", values=["true"])
    assert parse({"any": [{}]}) == Rule(op="any", children=[Rule(op="any", short=True)])
    assert _rule_to(Rule(op="any", children=[Rule(source="epic", values=["A"])])) == {
        "any": [{"epic": ["A"]}]
    }


# --- Invalid rules --------------------------------------------------------------------------


def test_rule_problems():
    assert rule_problems(parse({"epic": ["A"]})) == []
    assert rule_problems(parse({"all": [{"epic": ["A"]}, {"none": [{"label": ["x"]}]}]})) == []
    assert rule_problems(parse({"epic": []})) == ["'epic' ohne Werte (leere Liste)"]
    assert rule_problems(parse({"lable": ["x"]})) == [
        f"unbekannte Quelle 'lable' (erlaubt: {', '.join(RULE_SOURCES)})"
    ]
    assert rule_problems(parse({"all": []})) == ["'all' ohne Bedingungen"]
    assert rule_problems(parse({"any": [{}]})) == ["keine Bedingung"]
    mixed = rule_problems(parse({"epic": ["A"], "any": [{"label": ["x"]}]}))
    assert mixed == [
        "Kurz- und Langform gemischt: any, all und none stehen je allein, nicht neben Quellen "
        "oder nebeneinander"
    ]
    assert rule_problems(parse({"any": [{"epic": ["A"]}], "all": [{"label": ["x"]}]})) == mixed
    # Nested problems are found too.
    assert rule_problems(parse({"all": [{"epic": ["A"]}, {"none": [{"label": []}]}]})) == [
        "'label' ohne Werte (leere Liste)"
    ]


def test_invalid_rules_are_reported_by_the_check(data_dir: Path):
    data = Repository(data_dir).load("demo")
    data.team.features.tickets = True
    data.team.tracker.refined_also_if = parse({"status_not": ["To Do"]})
    data.projects = [
        Project(
            id="p",
            name="P",
            product="webshop",
            target=date(2027, 1, 1),
            match=parse({"epic": [], "any": [{"label": ["x"]}]}),
        )
    ]
    errors = [i for i in check_team(data, TODAY) if i.level is Level.ERROR]
    messages = {(i.where, i.message) for i in errors}
    assert (
        "team.yaml",
        "tracker.refined_also_if: unbekannte Quelle 'status_not' (erlaubt: "
        f"{', '.join(RULE_SOURCES)})",
    ) in messages
    assert ("projects.yaml: p", "match: 'epic' ohne Werte (leere Liste)") in messages
    assert any(
        where == "projects.yaml: p" and msg.startswith("match: Kurz- und Langform gemischt")
        for where, msg in messages
    )
    assert len(errors) == 3


def test_contains_leaf_round_trips_through_yaml():
    from sprintforecast.storage import _rule_from, _rule_to

    rule = _rule_from({"label_contains": ["pay"]}, "x")
    assert rule is not None and rule.contains and rule.source == "label"
    assert rule.matches({"label": ["Payment"]})
    assert _rule_to(rule) == {"label_contains": ["pay"]}


def test_insert_helper_conditions():
    from sprintforecast.web.rule_editor import append_condition, condition_text

    assert condition_text("label", "=", ["a", "b"]) == "label IN (a, b)"
    assert condition_text("label", "!=", ["a"]) == "label != a"
    assert condition_text("label", "~", ["pay"]) == "label ~ pay"
    assert append_condition("", "epic = A", "AND") == "epic = A"
    assert append_condition("epic = A OR epic = B", "label = x", "AND") == (
        "(epic = A OR epic = B) AND label = x"
    )
