# SPDX-License-Identifier: EUPL-1.2
"""Ticket import: refined state (6.3), project assignment (6.4), sprint resolution and the
reconciliation with the last import and the earmarks (6.5); preview and apply."""

from datetime import date, datetime
from pathlib import Path

import pytest

from sprintforecast.forecast import Forecast, build_forecast
from sprintforecast.model import (
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
from sprintforecast.sources import RawTicket
from sprintforecast.storage import Repository, TeamData
from sprintforecast.ticket_import import (
    KINDS,
    UNCLEAR_NO_ESTIMATE,
    UNCLEAR_RULE,
    TicketChange,
    apply_import,
    assign_project,
    convert,
    is_refined,
    plan_import,
    resolve_sprint,
)

TEAM = "demo"
# Demo data: current sprint 2026.21 (14.10.–28.10.), 2026.22 recorded, horizon 3.
TODAY = date(2026, 10, 15)


def tracker() -> TrackerSettings:
    return TrackerSettings(
        fields=TrackerFields(estimate="Story Points", remaining="Remaining", epic="Epic Link"),
        refined_label="Refined",
        refined_also_if=Rule(
            op="any",
            children=[
                Rule(source="in_sprint", values=["true"]),
                Rule(op="none", children=[Rule(source="status", values=["To Do"])]),
            ],
        ),
        sprint_names={"Sprint 22": "2026.22", "Sprint 23": "2026.23"},
    )


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


def raw(key: str = "ABC-1", **overrides) -> RawTicket:
    values = {"title": f"Title {key}", "status": "To Do", "issue_type": "Story", "estimate": 5.0}
    values.update(overrides)
    return RawTicket(key=key, **values)


def facts(**values: list[str] | str) -> dict[str, list[str]]:
    return {k: [v] if isinstance(v, str) else v for k, v in values.items()}


@pytest.fixture
def data(data_dir: Path) -> TeamData:
    repo = Repository(data_dir)
    loaded = repo.load(TEAM)
    loaded.team.features.tickets = True
    loaded.team.tracker = tracker()
    repo.save_team(loaded.team)
    loaded.projects = projects()
    return loaded


@pytest.fixture
def fc(data: TeamData) -> Forecast:
    return build_forecast(data, TODAY)


def kinds(changes: list[TicketChange]) -> list[tuple[str, str]]:
    return [(c.kind, c.key) for c in changes]


# --- Refined or not (6.3) --------------------------------------------------------------------


def test_label_with_estimate_is_refined():
    assert is_refined(facts(label=["payment", "Refined"]), 5, tracker()) == (True, False)


def test_label_without_estimate_is_unclear_and_not_refined():
    assert is_refined(facts(label=["Refined"]), None, tracker()) == (False, True)


def test_rule_without_label_is_refined_but_unclear():
    tr = tracker()
    assert is_refined(facts(in_sprint=["true", "2026.22"], status="To Do"), 3, tr) == (True, True)
    assert is_refined(facts(in_sprint=["false"], status="Ready"), 3, tr) == (True, True)
    assert is_refined(facts(in_sprint=["false"], status="To Do"), 3, tr) == (False, False)


def test_without_configuration_nothing_is_refined():
    tr = TrackerSettings()
    assert is_refined(facts(label=["Refined"], status="Ready"), 3, tr) == (False, False)
    tr.refined_also_if = Rule(source="status", values=["Ready"])
    assert is_refined(facts(label=["Refined"], status="Ready"), 3, tr) == (True, True)


# --- Project assignment (6.4) ----------------------------------------------------------------


def test_single_match_wins():
    assert assign_project(facts(epic="ABC-100"), projects(), ["epic", "component", "label"]) == (
        "payment",
        [],
    )
    assert assign_project(facts(epic="ABC-999"), projects(), ["epic"]) == (None, [])


def test_order_decides_between_sources():
    f = facts(epic="ABC-100", component=["Database"])
    assert assign_project(f, projects(), ["epic", "component", "label"]) == ("payment", [])
    assert assign_project(f, projects(), ["component", "epic"]) == ("migration", [])


def test_same_best_source_is_a_contradiction():
    both = [project("a", label=["x"]), project("b", label=["x"]), project("c", epic=["E"])]
    assert assign_project(facts(label=["x"]), both, ["epic", "label"]) == (None, ["a", "b"])
    # A match via the earlier source resolves it.
    assert assign_project(facts(label=["x"], epic="E"), both, ["epic", "label"]) == ("c", [])
    # Two via epic, one via label: the two contradict each other, the label does not count.
    three = [project("a", epic=["E"]), project("b", epic=["E"]), project("c", label=["x"])]
    assert assign_project(facts(label=["x"], epic="E"), three, ["epic", "label"]) == (
        None,
        ["a", "b"],
    )


def test_sources_outside_the_order_rank_last():
    ps = [project("status", status=["Ready"]), project("label", label=["x"])]
    assert assign_project(facts(status="Ready", label=["x"]), ps, ["label"]) == ("label", [])
    assert assign_project(facts(status="Ready"), ps, ["label"]) == ("status", [])


def test_projects_without_rule_and_pure_exclusions():
    ps = [
        Project(id="none", name="n", product="webshop", target=date(2027, 1, 1)),
        Project(
            id="rest",
            name="r",
            product="webshop",
            target=date(2027, 1, 1),
            match=Rule(op="none", children=[Rule(source="label", values=["x"])]),
        ),
    ]
    assert assign_project(facts(label=["y"]), ps, ["label"]) == ("rest", [])
    assert assign_project(facts(label=["x"]), ps, ["label"]) == (None, [])


# --- Sprint resolution -----------------------------------------------------------------------


def test_resolve_sprint_exact_id_mapping_or_none(data: TeamData, fc: Forecast):
    assert resolve_sprint("2026.22", data, fc) == "2026.22"  # recorded
    assert resolve_sprint("2026.23", data, fc) == "2026.23"  # only in the forecast
    # Calendar beyond the horizon; the numbering restarts after 2026.26 (26 sprints a year).
    assert resolve_sprint("2027.3", data, fc) == "2027.3"
    assert resolve_sprint("2026.30", data, fc) is None  # no such sprint in the calendar
    assert resolve_sprint("2026.20", data, fc) == "2026.20"  # past
    assert resolve_sprint("Sprint 22", data, fc) == "2026.22"  # tracker.sprint_names
    assert resolve_sprint("Sprint 99", data, fc) is None
    assert resolve_sprint(None, data, fc) is None and resolve_sprint("", data, fc) is None


# --- convert ---------------------------------------------------------------------------------


def test_convert_fills_every_field(data: TeamData, fc: Forecast):
    ticket = convert(
        raw(
            "ABC-1",
            remaining=3.5,
            sprint_name="Sprint 22",
            rank="0|i0001:",
            epic="ABC-100",
            labels=["payment", "Refined"],
            components=["Checkout"],
            blocked_by=["ABC-2"],
        ),
        data,
        fc,
        data.projects,
    )
    assert ticket == Ticket(
        key="ABC-1",
        title="Title ABC-1",
        status="To Do",
        issue_type="Story",
        estimate=5,
        remaining=3.5,
        estimate_source=EstimateSource.REFINED,
        in_sprint="2026.22",
        sprint_name="Sprint 22",
        rank="0|i0001:",
        epic="ABC-100",
        labels=["payment", "Refined"],
        components=["Checkout"],
        depends_on=["ABC-2"],
        project="payment",
    )


def test_convert_estimate_sources(data: TeamData, fc: Forecast):
    def source(**overrides) -> tuple[EstimateSource, bool]:
        tk = convert(raw(**overrides), data, fc, data.projects)
        return tk.estimate_source, tk.refined_unclear

    assert source(labels=["Refined"]) == (EstimateSource.REFINED, False)
    assert source() == (EstimateSource.ROUGH, False)
    assert source(estimate=None) == (EstimateSource.NONE, False)
    assert source(status="Ready") == (EstimateSource.ROUGH, True)
    assert source(sprint_name="Sprint 22") == (EstimateSource.ROUGH, True)
    assert source(labels=["Refined"], estimate=None) == (EstimateSource.NONE, True)


def test_convert_keeps_unresolved_sprint_name_and_done(data: TeamData, fc: Forecast):
    tk = convert(raw(sprint_name="Sprint 99", resolved=True), data, fc, data.projects)
    assert tk.in_sprint is None and tk.sprint_name == "Sprint 99" and tk.done
    tk = convert(raw(labels=["payment", "migration"]), data, fc, data.projects)
    assert tk.project is None and tk.project_candidates == ["payment", "migration"]


# --- Reconciliation (6.5) --------------------------------------------------------------------


def test_first_import_lists_new_tickets_but_not_done_ones(data: TeamData, fc: Forecast):
    plan = plan_import(data, fc, [raw("ABC-1", epic="ABC-100"), raw("ABC-2", resolved=True)], TODAY)
    assert kinds(plan.changes) == [("new", "ABC-1"), ("done", "ABC-2")]
    assert [tk.key for tk in plan.tickets] == ["ABC-1", "ABC-2"]
    assert plan.preplan_changed is False and plan.warnings == []


def test_changed_numbers_are_listed_with_old_and_new(data: TeamData, fc: Forecast):
    data.tickets = [Ticket(key="ABC-1", title="old", estimate=5, remaining=4, project="payment")]
    plan = plan_import(data, fc, [raw("ABC-1", epic="ABC-100", estimate=8, remaining=None)], TODAY)
    assert plan.of_kind("changed") == [
        TicketChange("changed", "ABC-1", "Title ABC-1", 5, 8, note="estimate"),
        TicketChange("changed", "ABC-1", "Title ABC-1", 4, None, note="remaining"),
    ]
    assert kinds(plan.changes) == [("changed", "ABC-1"), ("changed", "ABC-1")]
    # Unchanged numbers: no entry.
    plan = plan_import(data, fc, [raw("ABC-1", epic="ABC-100", estimate=5, remaining=4)], TODAY)
    assert plan.changes == []


def test_done_ticket_drops_its_earmark(data: TeamData, fc: Forecast):
    data.tickets = [Ticket(key="ABC-1", estimate=5, project="payment")]
    data.preplan = Preplan(earmarks=[Earmark("ABC-1", "2026.23"), Earmark("ABC-2", "2026.23")])
    plan = plan_import(data, fc, [raw("ABC-1", epic="ABC-100", resolved=True)], TODAY)
    assert kinds(plan.changes) == [("done", "ABC-1"), ("earmark_dropped", "ABC-1")]
    assert plan.of_kind("earmark_dropped") == [
        TicketChange("earmark_dropped", "ABC-1", "Title ABC-1", old="2026.23", new=None)
    ]
    assert plan.preplan.earmarks == [Earmark("ABC-2", "2026.23")] and plan.preplan_changed
    assert data.preplan.earmarks[0].ticket == "ABC-1"  # the input stays untouched
    assert plan.tickets[0].done
    # Already done last time: no new "done" entry.
    data.tickets[0].done = True
    data.preplan = Preplan()
    assert plan_import(data, fc, [raw("ABC-1", epic="ABC-100", resolved=True)], TODAY).changes == []


def test_missing_ticket_is_removed_and_its_earmark_stays_with_a_warning(
    data: TeamData, fc: Forecast
):
    data.tickets = [
        Ticket(key="ABC-1", title="gone", estimate=5, project="payment"),
        Ticket(key="ABC-2", title="also gone", estimate=5, project="payment"),
        Ticket(key="ABC-3", title="stays", estimate=5, project="payment"),
    ]
    data.preplan = Preplan(
        earmarks=[Earmark("ABC-1", "2026.23")], estimates=[ManualEstimate("ABC-2", 3)]
    )
    plan = plan_import(data, fc, [raw("ABC-3", epic="ABC-100")], TODAY)
    assert kinds(plan.changes) == [("missing", "ABC-1"), ("missing", "ABC-2")]
    assert plan.of_kind("missing")[0] == TicketChange("missing", "ABC-1", "gone", note="2026.23")
    assert [tk.key for tk in plan.tickets] == ["ABC-3"]
    assert plan.preplan == data.preplan and not plan.preplan_changed
    assert plan.warnings == [
        "Ticket ABC-1 ist nicht mehr im Import; die Vormerkung für Sprint 2026.23 bleibt bestehen",
        "Ticket ABC-2 ist nicht mehr im Import; die eigene Schätzung bleibt bestehen",
    ]


def test_real_current_or_future_sprint_wins_over_a_deviating_earmark(data: TeamData, fc: Forecast):
    data.tickets = [Ticket(key=k, estimate=5, project="payment") for k in ("A-1", "A-2", "A-3")]
    data.preplan = Preplan(
        earmarks=[Earmark("A-1", "2026.23"), Earmark("A-2", "2026.22"), Earmark("A-3", "2026.23")]
    )
    raws = [
        raw("A-1", epic="ABC-100", sprint_name="Sprint 22"),  # future: earmark 2026.23 dropped
        raw("A-2", epic="ABC-100", sprint_name="2026.22"),  # same sprint: earmark stays
        raw("A-3", epic="ABC-100", sprint_name="2026.20"),  # past sprint: earmark stays
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert plan.of_kind("earmark_dropped") == [
        TicketChange("earmark_dropped", "A-1", "Title A-1", "2026.23", "2026.22")
    ]
    assert plan.preplan.earmarks == [Earmark("A-2", "2026.22"), Earmark("A-3", "2026.23")]
    assert plan.preplan_changed
    # The current sprint counts as well.
    data.preplan = Preplan(earmarks=[Earmark("A-1", "2026.23")])
    plan = plan_import(data, fc, [raw("A-1", epic="ABC-100", sprint_name="2026.21")], TODAY)
    assert kinds(plan.of_kind("earmark_dropped")) == [("earmark_dropped", "A-1")]


def test_unassigned_and_contradictions(data: TeamData, fc: Forecast):
    raws = [
        raw("A-1", epic="ABC-999"),
        raw("A-2", labels=["payment", "migration"]),  # two projects via the same source
        raw("A-3", components=["Database"], labels=["payment"]),  # the component outranks the label
        raw("A-4", epic="ABC-100"),
        raw("A-5", resolved=True),  # done: not listed
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert plan.of_kind("unassigned") == [
        TicketChange("unassigned", "A-1", "Title A-1", new=[]),
        TicketChange("unassigned", "A-2", "Title A-2", new=["payment", "migration"]),
    ]
    assert plan.tickets[1].project_candidates == ["payment", "migration"]
    assert plan.tickets[2].project == "migration"


def test_unknown_epics_once_each_with_their_tickets(data: TeamData, fc: Forecast):
    raws = [
        raw("A-1", epic="ABC-999"),
        raw("A-2", epic="ABC-999"),
        raw("A-3", epic="ABC-100"),  # known from a rule
        raw("A-4", epic="ABC-777"),
        raw("A-5", epic="ABC-888", resolved=True),  # done: not listed
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert plan.of_kind("unknown_epic") == [
        TicketChange("unknown_epic", "ABC-999", new=["A-1", "A-2"]),
        TicketChange("unknown_epic", "ABC-777", new=["A-4"]),
    ]


def test_refined_unclear_with_reason(data: TeamData, fc: Forecast):
    raws = [
        raw("A-1", epic="ABC-100", status="Ready"),
        raw("A-2", epic="ABC-100", labels=["Refined"], estimate=None),
        raw("A-3", epic="ABC-100", labels=["Refined"]),
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert plan.of_kind("refined_unclear") == [
        TicketChange("refined_unclear", "A-1", "Title A-1", note=UNCLEAR_RULE),
        TicketChange("refined_unclear", "A-2", "Title A-2", note=UNCLEAR_NO_ESTIMATE),
    ]


def test_unresolved_sprint_names_are_listed_but_not_for_done_tickets(data: TeamData, fc: Forecast):
    raws = [
        raw("A-1", epic="ABC-100", sprint_name="Sprint 99"),
        raw("A-2", epic="ABC-100", sprint_name="Sprint 98", resolved=True),
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert plan.of_kind("sprint_unresolved") == [
        TicketChange("sprint_unresolved", "A-1", "Title A-1", note="Sprint 99")
    ]
    assert plan.tickets[0].in_sprint is None and plan.tickets[0].sprint_name == "Sprint 99"


def test_duplicates_and_cycles_give_warnings(data: TeamData, fc: Forecast):
    raws = [
        raw("A-1", epic="ABC-100", estimate=1, blocked_by=["A-2"]),
        raw("A-2", epic="ABC-100", blocked_by=["A-1"]),
        raw("A-1", epic="ABC-100", estimate=2, blocked_by=["A-2"]),
    ]
    plan = plan_import(data, fc, raws, TODAY)
    assert [tk.key for tk in plan.tickets] == ["A-1", "A-2"] and plan.tickets[0].estimate == 2
    assert plan.warnings == [
        "Ticket A-1 kommt mehrfach vor; der letzte Eintrag gilt",
        "Abhängigkeiten im Kreis: A-1 → A-2 → A-1",
    ]


def test_changes_are_grouped_by_kind_in_display_order(data: TeamData, fc: Forecast):
    data.tickets = [Ticket(key="OLD", title="old", estimate=1, project="payment")]
    raws = [
        raw("A-1", sprint_name="Sprint 99", status="Ready", epic="ABC-999"),
        raw("A-2", epic="ABC-100"),
    ]
    plan = plan_import(data, fc, raws, TODAY)
    order = [KINDS.index(c.kind) for c in plan.changes]
    assert order == sorted(order)
    assert kinds(plan.changes) == [
        ("new", "A-1"),
        ("new", "A-2"),
        ("missing", "OLD"),
        ("unassigned", "A-1"),
        ("unknown_epic", "ABC-999"),
        ("refined_unclear", "A-1"),
        ("sprint_unresolved", "A-1"),
    ]


# --- Apply -----------------------------------------------------------------------------------


def test_apply_writes_tickets_and_preplan_only_when_changed(data_dir: Path, data: TeamData):
    repo = Repository(data_dir)
    repo.save_projects(TEAM, data.projects)
    data.preplan = Preplan(earmarks=[Earmark("A-2", "2026.23", note="later")])
    repo.save_preplan(TEAM, data.preplan)
    fc = build_forecast(data, TODAY)
    raws = [raw("A-1", epic="ABC-100", labels=["Refined"], sprint_name="Sprint 22"), raw("A-2")]
    plan = plan_import(data, fc, raws, TODAY, source="export.csv")
    assert not plan.preplan_changed
    now = datetime(2026, 10, 15, 9, 30)
    paths = apply_import(repo, TEAM, plan, now)
    assert [p.name for p in paths] == ["tickets.yaml"]
    loaded = repo.load(TEAM)
    assert loaded.tickets == plan.tickets
    assert loaded.tickets_imported == now and loaded.tickets_source == "export.csv"
    assert loaded.preplan == data.preplan
    text = (data_dir / TEAM / "tickets.yaml").read_text(encoding="utf-8")
    assert "imported: 2026-10-15 09:30:00\nsource: export.csv\n" in text

    # Second import: A-2 is done now, the earmark goes.
    plan = plan_import(loaded, fc, [raws[0], raw("A-2", resolved=True)], TODAY, "export.csv")
    assert plan.preplan_changed
    paths = apply_import(repo, TEAM, plan, now)
    assert [p.name for p in paths] == ["tickets.yaml", "preplan.yaml"]
    assert repo.load(TEAM).preplan == Preplan()


# --- Review fixes ----------------------------------------------------------------------------


def test_closed_sprint_of_an_open_ticket_is_not_its_sprint(data: TeamData, fc: Forecast):
    """Jira keeps closed sprints in the Sprint field of carried-over tickets."""
    data.team.tracker.sprint_names["Sprint 20"] = "2026.20"
    raws = [
        raw("A-1", epic="ABC-100", sprint_name="2026.20"),
        raw("A-2", epic="ABC-100", sprint_name="Sprint 20"),
        raw("A-3", epic="ABC-100", sprint_name="2026.21"),  # the current sprint still counts
    ]
    plan = plan_import(data, fc, raws, TODAY)
    closed, mapped, current = plan.tickets
    for tk in (closed, mapped):
        assert tk.in_sprint is None
        assert tk.facts()["in_sprint"] == ["false"]
        # not refined via ``in_sprint: [true]``
        assert (tk.estimate_source, tk.refined_unclear) == (EstimateSource.ROUGH, False)
    assert closed.sprint_name == "2026.20" and mapped.sprint_name == "Sprint 20"
    assert current.in_sprint == "2026.21" and current.refined_unclear
    # The name is known, so it is not reported as unrecognised.
    assert plan.of_kind("sprint_unresolved") == []


def test_estimate_source_follows_the_size_by_planning_uses(data: TeamData, fc: Forecast):
    def source(planning: PlanningUses, **overrides) -> tuple[EstimateSource, bool]:
        data.team.tracker.planning_uses = planning
        tk = convert(raw(estimate=None, remaining=3, **overrides), data, fc, data.projects)
        return tk.estimate_source, tk.refined_unclear

    # Only ``remaining`` is filled: that is the size the distribution calculates with.
    assert source(PlanningUses.REMAINING) == (EstimateSource.ROUGH, False)
    assert source(PlanningUses.REMAINING, labels=["Refined"]) == (EstimateSource.REFINED, False)
    # By estimate there is nothing to calculate with: the label alone is unclear.
    assert source(PlanningUses.ESTIMATE) == (EstimateSource.NONE, False)
    assert source(PlanningUses.ESTIMATE, labels=["Refined"]) == (EstimateSource.NONE, True)
    # The reason shown in the preview follows the size as well.
    data.team.tracker.planning_uses = PlanningUses.REMAINING
    plan = plan_import(data, fc, [raw("A-1", estimate=None, remaining=2, status="Ready")], TODAY)
    assert plan.of_kind("refined_unclear")[0].note == UNCLEAR_RULE


def test_unchanged_import_is_detected(data_dir: Path, data: TeamData, fc: Forecast):
    repo = Repository(data_dir)
    repo.save_projects(TEAM, data.projects)
    raws = [raw("A-1", epic="ABC-100", rank="0|a")]
    apply_import(repo, TEAM, plan_import(data, fc, raws, TODAY, "x.csv"))
    loaded = repo.load(TEAM)
    assert plan_import(loaded, fc, raws, TODAY, "x.csv").unchanged(loaded)
    # A change the preview does not list (rank) still counts as a change.
    moved = plan_import(loaded, fc, [raw("A-1", epic="ABC-100", rank="0|b")], TODAY, "x.csv")
    assert moved.changes == [] and not moved.unchanged(loaded)
    assert not plan_import(loaded, fc, [], TODAY, "x.csv").unchanged(loaded)
