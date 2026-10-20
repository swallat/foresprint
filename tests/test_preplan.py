# SPDX-License-Identifier: EUPL-1.2
"""Ticket pre-planning: distribution over future sprints, project traffic light and
refinement list (docs/design/ticket-planning.md, section 5)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from sprintforecast import preplan
from sprintforecast.model import (
    BudgetBasis,
    Earmark,
    EstimateSource,
    ManualEstimate,
    Membership,
    Person,
    PlanningUses,
    Preplan,
    Product,
    Project,
    Sprint,
    Team,
    Ticket,
)
from sprintforecast.preplan import Budget, Distribution, distribute, order_tickets
from sprintforecast.storage import TeamData

TODAY = date(2026, 10, 15)
# The current sprint (without velocity) starts on 7 Oct; five closed sprints precede it.
CURRENT_START = date(2026, 10, 7)
LENGTH = 14


def team_data(
    velocities: tuple[float, ...] = (10,) * 5,
    capacities: tuple[float, ...] | None = None,
    products: list[Product] | None = None,
    **tracker: object,
) -> TeamData:
    """Five closed sprints (reference 40, capacity 40, velocity 10 -> Forecast PLAN 10 per
    future sprint, plannable share 80 % -> budget 8) plus the current sprint."""
    team = Team(key="t", name="T")
    team.forecast.reference_capacity = 40
    team.forecast.window = 5
    team.features.tickets = True
    team.features.products = products is not None
    for name, value in tracker.items():
        setattr(team.tracker, name, value)
    sprints = []
    for i, v in enumerate(velocities):
        start = CURRENT_START - timedelta(days=LENGTH * (len(velocities) - i))
        cap = 40.0 if capacities is None else capacities[i]
        sprints.append(
            Sprint(f"2026.{i + 1}", start, start + timedelta(days=LENGTH), capacity=cap,
                   velocity=v, commitment=v)
        )  # fmt: skip
    n = len(velocities) + 1
    sprints.append(Sprint(f"2026.{n}", CURRENT_START, CURRENT_START + timedelta(days=LENGTH)))
    return TeamData(team=team, sprints=sprints, products=products or [])


def project(
    pid: str, target: date | None = date(2027, 6, 30), priority: int = 0, **kw: object
) -> Project:
    return Project(id=pid, name=pid, target=target, priority=priority, **kw)


def ticket(
    key: str,
    estimate: float | None = 5,
    project: str | None = "p",
    source: EstimateSource = EstimateSource.REFINED,
    **kw: object,
) -> Ticket:
    return Ticket(key=key, estimate=estimate, estimate_source=source, project=project, **kw)


def future(dist: Distribution, data: TeamData) -> list[Sprint]:
    """The future sprints of the horizon (to check target date and deadline)."""
    from sprintforecast.analysis import horizon_entries, horizon_forecast

    return [h.sprint for h in horizon_entries(horizon_forecast(data, TODAY))]


def sprint_of(dist: Distribution, key: str) -> str | None:
    return dist.placement(key).sprint


def reason_of(dist: Distribution, key: str) -> str:
    return dist.placement(key).reason


# --- Budget --------------------------------------------------------------------------------


def test_budget_is_share_of_the_forecast_plan():
    data = team_data()
    dist = distribute(data, TODAY)
    assert len(dist.sprints) == 26 and dist.sprints[0] == "2026.7"
    first = dist.budget("2026.7", None)
    assert (first.plan, first.roadmap, first.base) == (10.0, pytest.approx(8.0), pytest.approx(8.0))
    assert first.free == pytest.approx(8.0) and first.production_available is None
    assert first.limit(BudgetBasis.PLAN) == 10.0 and first.free_for(BudgetBasis.PLAN) == 10.0
    # With budget_basis plan the whole Forecast PLAN counts.
    dist = distribute(team_data(budget_basis=BudgetBasis.PLAN), TODAY)
    assert dist.budget("2026.7", None).base == 10.0


def test_horizon_beyond_the_people_list_uses_the_average_capacity():
    """Without a people list the capacity of future sprints is only a trend; like
    analysis.completion, the average capacity of the last sprints counts instead."""
    # normalized velocity constant 10 (velocity = capacity / 4), average capacity 36 -> PLAN 9
    data = team_data(velocities=(5, 10, 10, 10, 10), capacities=(20, 40, 40, 40, 40))
    dist = distribute(data, TODAY)
    assert all(b.plan == pytest.approx(9.0) for b in dist.budgets)
    assert all(b.base == pytest.approx(7.2) for b in dist.budgets)
    # With a people list the capacity comes from the calendar and differs per sprint.
    data.people = [Person(id="a", name="A", memberships=[Membership(start=date(2026, 1, 1))])]
    dist = distribute(data, TODAY)
    from sprintforecast.analysis import horizon_entries, horizon_forecast

    entries = horizon_entries(horizon_forecast(data, TODAY))
    assert not any(h.trend for h in entries)
    assert dist.budget("2026.7", None).plan == entries[0].entry.result.plan


# --- Order and placement ------------------------------------------------------------


def test_projects_by_priority_then_target_and_tickets_by_rank():
    data = team_data()
    data.projects = [
        project("late", date(2027, 6, 30), priority=3),
        project("early-2", date(2027, 3, 31), priority=2),
        project("early-1", date(2027, 3, 31), priority=1),
        project("open", None, priority=3),
    ]
    data.tickets = [
        ticket("L-1", project="late"),
        ticket("O-1", project="open"),
        ticket("E2-1", project="early-2"),
        ticket("E1-b", project="early-1", rank="0|b"),
        ticket("E1-a", project="early-1", rank="0|a"),
        ticket("E1-z", project="early-1", rank=None),
        ticket("X-1", project=None),
    ]
    ordered, leftover = order_tickets(data)
    assert [tk.key for tk in ordered] == ["E1-a", "E1-b", "E1-z", "E2-1", "L-1", "O-1", "X-1"]
    assert leftover == []
    dist = distribute(data, TODAY)
    s = dist.sprints
    assert [sprint_of(dist, k) for k in ("E1-a", "E1-b", "E1-z", "E2-1", "L-1", "O-1")] == [
        s[0], s[1], s[2], s[3], s[4], s[5],
    ]  # fmt: skip
    # Without the products feature a ticket without project uses the one product's budget,
    # after the projects of equal priority.
    assert dist.placement("X-1").reason == "placed" and sprint_of(dist, "X-1") == s[6]
    assert [p.project for p in dist.projects] == ["early-1", "early-2", "late", "open"]


def test_tickets_spill_into_the_next_sprint_when_the_budget_is_used():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("A", 3), ticket("B", 3), ticket("C", 3), ticket("D", 2)]
    dist = distribute(data, TODAY)
    s = dist.sprints
    # 3 + 3 = 6 fit into budget 8, the third ticket no longer does, but the small fourth does.
    assert [sprint_of(dist, k) for k in "ABCD"] == [s[0], s[0], s[1], s[0]]
    assert dist.budget(s[0], None).placed == pytest.approx(8.0)
    assert dist.budget(s[0], None).free == pytest.approx(0.0)
    assert dist.budget(s[1], None).free == pytest.approx(5.0)
    assert all(p.reason == "placed" for p in dist.placements)


@pytest.mark.parametrize("gap, expected", [(1, 1), (0, 0)])
def test_dependency_gap(gap: int, expected: int):
    data = team_data(dependency_gap=gap)
    data.projects = [project("p")]
    data.tickets = [ticket("B", 2, depends_on=["A"]), ticket("A", 2)]
    dist = distribute(data, TODAY)
    assert [tk.key for tk in order_tickets(data)[0]] == ["A", "B"]
    assert sprint_of(dist, "A") == dist.sprints[0]
    assert sprint_of(dist, "B") == dist.sprints[expected]


def test_dependency_on_a_ticket_in_the_current_sprint_or_done():
    data = team_data()
    data.projects = [project("p")]
    current = data.sprints[-1].id
    data.tickets = [
        ticket("A", 2, in_sprint=current),
        ticket("B", 2, depends_on=["A"]),
        ticket("C", 2, done=True),
        ticket("D", 2, depends_on=["C", "unknown"]),
    ]
    dist = distribute(data, TODAY)
    # The current sprint lies before the horizon: B may go into the first future sprint.
    assert dist.placement("A").reason == "fixed_sprint" and sprint_of(dist, "A") == current
    assert sprint_of(dist, "B") == dist.sprints[0]
    assert dist.placement("C") is None  # done tickets are skipped
    assert sprint_of(dist, "D") == dist.sprints[0]
    assert [p.ticket for p in dist.placements] == ["A", "B", "D"]


def test_ticket_larger_than_every_sprint_budget():
    data = team_data()
    data.projects = [project("p"), project("whole", budget_basis=BudgetBasis.PLAN)]
    data.tickets = [ticket("big", 9), ticket("fits", 9, project="whole"), ticket("small", 1)]
    # Projects are ordered by target, priority and id: "p" (small) comes before "whole" (fits).
    dist = distribute(data, TODAY)
    assert reason_of(dist, "big") == "too_large" and sprint_of(dist, "big") is None
    # The project with the whole Forecast PLAN as its basis (10) may place 9.
    assert reason_of(dist, "fits") == "placed" and sprint_of(dist, "fits") == dist.sprints[0]
    # "small" was placed first (1 of 8); "fits" still fits into the remaining 9 of 10.
    assert sprint_of(dist, "small") == dist.sprints[0]
    first = dist.budget(dist.sprints[0], None)
    assert first.free_for(BudgetBasis.PLAN) == pytest.approx(0.0)
    assert first.free == pytest.approx(-2.0)  # by the team basis (8) the sprint is overfull
    assert dist.status("p").light == "missed" and dist.status("p").not_distributable == 1


def test_unestimated_ticket_and_manual_estimate():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [
        ticket("none", None, source=EstimateSource.NONE),
        ticket("manual", None, source=EstimateSource.NONE),
        ticket("after", 2, depends_on=["none"]),
    ]
    data.preplan = Preplan(estimates=[ManualEstimate(ticket="manual", estimate=4)])
    dist = distribute(data, TODAY)
    assert reason_of(dist, "none") == "unestimated" and dist.placement("none").size is None
    manual = dist.placement("manual")
    assert (manual.reason, manual.size, manual.source) == ("placed", 4, EstimateSource.MANUAL)
    # Dependency not distributed -> blocked.
    assert reason_of(dist, "after") == "blocked"
    assert [p.ticket for p in dist.not_distributable()] == ["none", "after"]


def test_dependency_cycle():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [
        ticket("A", 2, depends_on=["B"]),
        ticket("B", 2, depends_on=["A"]),
        ticket("C", 2, depends_on=["A"]),
        ticket("D", 2),
    ]
    dist = distribute(data, TODAY)
    assert dist.cycles == [["A", "B"]]
    assert reason_of(dist, "A") == reason_of(dist, "B") == "cycle"
    assert reason_of(dist, "C") == "blocked"
    assert sprint_of(dist, "D") == dist.sprints[0]
    assert dist.status("p").light == "missed" and dist.status("p").not_distributable == 3


def test_fixed_points_consume_the_budget():
    data = team_data()
    data.projects = [project("p")]
    s1, s2 = "2026.8", "2026.9"
    data.tickets = [
        ticket("jira", 6, in_sprint=s1, depends_on=["free-1"]),
        ticket("mark", 20, rank="0|a"),
        ticket("both", 1, in_sprint=s2),
        ticket("free-1", 5, rank="0|b"),
        ticket("free-2", 5, rank="0|c"),
    ]
    data.preplan = Preplan(
        earmarks=[Earmark(ticket="mark", sprint=s2), Earmark(ticket="both", sprint=s1)]
    )
    dist = distribute(data, TODAY)
    assert (sprint_of(dist, "jira"), reason_of(dist, "jira")) == (s1, "fixed_sprint")
    assert (sprint_of(dist, "mark"), reason_of(dist, "mark")) == (s2, "earmark")
    # The real sprint takes precedence over the earmark.
    assert (sprint_of(dist, "both"), reason_of(dist, "both")) == (s2, "fixed_sprint")
    assert dist.budget(s1, None).fixed == 6 and dist.budget(s1, None).free == pytest.approx(2)
    # Overfull because of the earmark: reported, not redistributed.
    assert dist.budget(s2, None).fixed == 21 and dist.budget(s2, None).free == pytest.approx(-13)
    # Distributed tickets yield: 5 in 2026.7, the next 5 only fit into 2026.10.
    assert sprint_of(dist, "free-1") == "2026.7"
    assert sprint_of(dist, "free-2") == "2026.10"
    assert dist.budget("2026.10", None).placed == 5


def test_fixed_point_outside_the_horizon_consumes_nothing():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("old", 6, in_sprint="2026.6"), ticket("far", 6)]
    data.preplan = Preplan(earmarks=[Earmark(ticket="far", sprint="2099.1")])
    dist = distribute(data, TODAY)
    assert sprint_of(dist, "old") == "2026.6" and sprint_of(dist, "far") == "2099.1"
    assert all(b.fixed == 0 for b in dist.budgets)


def test_planning_uses_remaining_or_estimate():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("A", 5, remaining=2), ticket("B", 5)]
    dist = distribute(data, TODAY)
    assert dist.placement("A").size == 2 and dist.placement("B").size == 5
    assert sprint_of(dist, "A") == sprint_of(dist, "B") == dist.sprints[0]
    data.team.tracker.planning_uses = PlanningUses.ESTIMATE
    dist = distribute(data, TODAY)
    assert dist.placement("A").size == 5
    assert sprint_of(dist, "B") == dist.sprints[1]


def test_rough_estimates_are_not_inflated_by_the_rough_factor():
    """``tracker.rough_factor`` belongs to the conservative variant (step 4); the distribution
    of step 1 calculates with the numbers as they are."""
    data = team_data(rough_factor=1.5)
    data.projects = [project("p")]
    data.tickets = [
        ticket("rough", 4, source=EstimateSource.ROUGH, rank="0|a"),
        ticket("fine", 4, rank="0|b"),
    ]
    dist = distribute(data, TODAY)
    assert dist.placement("rough").size == 4 and dist.placement("fine").size == 4
    # 4 + 4 fit into the budget of 8 together (with the factor 1.5 they would not).
    assert sprint_of(dist, "rough") == sprint_of(dist, "fine") == dist.sprints[0]
    data.team.tracker.rough_factor = 3.0
    assert distribute(data, TODAY).placement("rough").size == 4


# --- Project traffic light ----------------------------------------------------------------


def test_traffic_lights():
    data = team_data()
    sprints = future(distribute(data, TODAY), data)
    last_day = [s.end - timedelta(days=1) for s in sprints]
    data.projects = [
        project("on-track", last_day[3]),  # target sprint s[3], last ticket in s[2]
        project("tight", last_day[1]),  # target sprint s[1], last ticket in s[1]
        project("missed", last_day[0]),  # target sprint s[0], last ticket in s[1]
        project("not-dist", last_day[5]),  # one ticket unestimated
        project("empty", last_day[5]),  # no open tickets
        project("no-target", None),
        project("past", TODAY - timedelta(days=3)),  # no target sprint in the horizon
        project("far", last_day[-1] + timedelta(days=400)),  # target date beyond the horizon
    ]
    data.tickets = [
        ticket("A", 2, project="on-track"),
        ticket("B", 1, project="tight"),
        ticket("C1", 7, project="missed"),
        ticket("C2", 7, project="missed"),
        ticket("D1", 1, project="not-dist"),
        ticket("D2", None, project="not-dist", source=EstimateSource.NONE),
        ticket("E", 1, project="empty", done=True),
        ticket("F", 1, project="no-target"),
        ticket("G", 1, project="past"),
        ticket("H", 1, project="far"),
    ]
    dist = distribute(data, TODAY)
    status = {s.project: s for s in dist.projects}
    s = dist.sprints
    # Projects are distributed by target date: past (1), missed (7 + 7), tight (1), on-track.
    assert [sprint_of(dist, k) for k in ("G", "C1", "C2", "B", "A")] == [
        s[0],
        s[0],
        s[1],
        s[1],
        s[2],
    ]
    assert (status["on-track"].light, status["on-track"].target_sprint) == ("on_track", s[3])
    assert (status["on-track"].last_sprint, status["on-track"].open_tickets) == (s[2], 1)
    assert (status["tight"].light, status["tight"].target_sprint) == ("tight", s[1])
    assert status["tight"].last_sprint == s[1]
    assert (status["missed"].light, status["missed"].target_sprint) == ("missed", s[0])
    assert status["not-dist"].light == "missed" and status["not-dist"].not_distributable == 1
    assert status["empty"].light == "empty" and status["empty"].open_tickets == 0
    assert status["no-target"].light == "on_track" and status["no-target"].target_sprint is None
    assert status["past"].light == "missed" and status["past"].target_sprint is None
    assert status["far"].light == "on_track" and status["far"].target_sprint is None
    assert {preplan.LIGHTS[st.light] for st in dist.projects} <= set(preplan.LIGHTS.values())


def test_project_without_target_is_missed_when_a_ticket_is_not_distributable():
    data = team_data()
    data.projects = [project("p", None)]
    data.tickets = [ticket("A", 50)]
    dist = distribute(data, TODAY)
    assert dist.status("p").light == "missed" and reason_of(dist, "A") == "too_large"


# --- Refinement list -----------------------------------------------------------------------


def test_refinement_list_per_sprint_with_deadline():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [
        ticket("fine", 2),
        ticket("rough", 2, source=EstimateSource.ROUGH, rank="0|a"),
        ticket("unclear", 2, source=EstimateSource.ROUGH, refined_unclear=True, rank="0|b"),
        ticket("manual", None, source=EstimateSource.NONE, rank="0|c"),
        ticket("fixed", 2, source=EstimateSource.ROUGH, in_sprint="2026.9"),
        ticket("none", None, source=EstimateSource.NONE),
    ]
    # Rough 2 + 2 and the manual 5 do not fit into one budget of 8 together.
    data.preplan = Preplan(estimates=[ManualEstimate(ticket="manual", estimate=5)])
    dist = distribute(data, TODAY)
    sprints = {s.id: s for s in future(dist, data)}
    assert [(r.ticket, r.sprint, r.source, r.unclear) for r in dist.refinement] == [
        ("rough", "2026.7", EstimateSource.ROUGH, False),
        ("unclear", "2026.7", EstimateSource.ROUGH, True),
        ("manual", "2026.8", EstimateSource.MANUAL, False),
        ("fixed", "2026.9", EstimateSource.ROUGH, False),
    ]
    assert all(r.deadline == sprints[r.sprint].start for r in dist.refinement)
    assert dist.refinement[0].deadline == date(2026, 10, 21)
    assert dist.unclear == ["unclear"]


# --- Products -------------------------------------------------------------------------------


def test_products_split_the_budget_and_tickets_only_use_their_product():
    products = [
        Product(id="shop", name="Shop", share=0.25),
        Product(id="app", name="App"),
        Product(id="old", name="Old", end=date(2026, 11, 10)),
    ]
    data = team_data(products=products)
    data.projects = [
        project("s", product="shop"),
        project("a", product="app"),
        project("o", product="old"),
    ]
    data.tickets = [
        ticket("S-1", 2, project="s"),
        ticket("S-2", 1, project="s"),
        ticket("A-1", 3, project="a"),
        ticket("O-1", 2, project="o"),
        ticket("O-2", 2, project="o"),
    ]
    dist = distribute(data, TODAY)
    s = dist.sprints
    first = {b.product: b for b in dist.budgets if b.sprint == s[0]}
    # Sprint 2026.7 (21 Oct - 4 Nov): three active products; shop 25 %, the rest 37.5 % of 8 each.
    assert first["shop"].base == pytest.approx(2.0)
    assert first["app"].base == first["old"].base == pytest.approx(3.0)
    assert first["app"].production_available is None
    # From 2026.9 (18 Nov) "old" has ended: only two products left, no budget for "old".
    assert dist.budget(s[2], "old") is None
    assert dist.budget(s[2], "app").base == pytest.approx(6.0)
    assert sprint_of(dist, "S-1") == s[0] and sprint_of(dist, "S-2") == s[1]
    assert sprint_of(dist, "A-1") == s[0]
    assert sprint_of(dist, "O-1") == s[0] and sprint_of(dist, "O-2") == s[1]
    assert first["shop"].free == pytest.approx(0.0) and first["app"].free == pytest.approx(0.0)
    # Too large is measured against the product's largest budget in the horizon.
    data.tickets.append(ticket("O-3", 4, project="o"))
    assert reason_of(distribute(data, TODAY), "O-3") == "too_large"


def test_production_available_is_reported_not_added():
    data = team_data()
    data.team.features.production = True
    data.people = [
        Person(id="a", name="A", memberships=[Membership(start=date(2026, 1, 1))]),
        Person(id="b", name="B", production_access=True,
               memberships=[Membership(start=date(2026, 1, 1))]),
    ]  # fmt: skip
    dist = distribute(data, TODAY)
    first = dist.budget(dist.sprints[0], None)
    assert first.production_available == pytest.approx(first.plan * 0.5)
    assert first.base == pytest.approx(first.plan * 0.8)


def test_without_products_feature_every_ticket_shares_one_budget():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("A", 5), ticket("B", 5, project="unknown", in_sprint="2026.7")]
    dist = distribute(data, TODAY)
    assert [b.product for b in dist.budgets][:1] == [None]
    assert dist.budget("2026.7", None).fixed == 5  # the tracker's sprint always counts
    assert sprint_of(dist, "A") == "2026.8"
    assert reason_of(dist, "B") == "fixed_sprint"


# --- Randomised test ----------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_random_distributions_respect_dependencies_and_budgets(seed: int):
    rng = random.Random(seed)
    products = None
    if rng.random() < 0.5:
        products = [Product(id="x", name="X"), Product(id="y", name="Y", share=0.3)]
    gap = rng.choice([0, 1])
    data = team_data(products=products, dependency_gap=gap)
    ids = ["x", "y"] if products else [None]
    data.projects = [
        project(
            f"p{i}",
            rng.choice([None, TODAY + timedelta(days=rng.randint(1, 400))]),
            priority=rng.randint(0, 2),
            product=rng.choice(ids),
            budget_basis=rng.choice([None, BudgetBasis.PLAN]),
        )
        for i in range(3)
    ]
    keys = [f"T-{i}" for i in range(rng.randint(5, 25))]
    tickets = []
    for i, key in enumerate(keys):
        # Dependencies only point backwards (acyclic); a few cycles are added further down.
        deps = [k for k in keys[:i] if rng.random() < 0.15]
        tickets.append(
            Ticket(
                key=key,
                estimate=rng.choice([None, 1, 2, 3, 5, 8, 13]),
                remaining=rng.choice([None, None, 1, 2]),
                estimate_source=rng.choice(list(EstimateSource)),
                refined_unclear=rng.random() < 0.1,
                in_sprint=rng.choice([None] * 6 + ["2026.6", "2026.8", "2026.9"]),
                rank=rng.choice([None, f"0|{rng.randint(0, 99):02d}"]),
                depends_on=deps,
                project=rng.choice(["p0", "p1", "p2", None]),
                done=rng.random() < 0.1,
            )
        )
    if rng.random() < 0.3:
        tickets.append(Ticket(key="C-1", estimate=1, depends_on=["C-2"], project="p0"))
        tickets.append(Ticket(key="C-2", estimate=1, depends_on=["C-1"], project="p0"))
    data.tickets = tickets
    data.preplan = Preplan(
        earmarks=[
            Earmark(ticket=k, sprint=rng.choice(["2026.7", "2026.10", "2027.1"]))
            for k in keys
            if rng.random() < 0.1
        ],
        estimates=[ManualEstimate(ticket=k, estimate=2) for k in keys if rng.random() < 0.1],
    )
    dist = distribute(data, TODAY)

    index = {s: i for i, s in enumerate(dist.sprints)}
    by_key = {p.ticket: p for p in dist.placements}
    open_keys = {tk.key for tk in tickets if not tk.done}
    assert set(by_key) == open_keys  # every open ticket exactly once
    for tk in tickets:
        if tk.done:
            continue
        p = by_key[tk.key]
        assert (p.sprint is None) == (not p.distributable)
        if p.reason != "placed":
            continue
        assert tk.in_sprint is None and data.preplan.earmark_for(tk.key) is None
        assert p.size is not None
        for dep in tk.depends_on:
            if dep not in open_keys:
                continue
            dep_place = by_key[dep]
            assert dep_place.sprint is not None
            assert index[p.sprint] >= index.get(dep_place.sprint, -1) + gap
    for b in dist.budgets:
        own = [
            by_key[tk.key]
            for tk in tickets
            if not tk.done
            and by_key[tk.key].sprint == b.sprint
            and by_key[tk.key].reason == "placed"
            and by_key[tk.key].product == b.product
        ]
        assert b.placed == pytest.approx(sum(p.size for p in own))
        # Distributed tickets never exceed the budget; fixed points may (reported).
        assert b.placed <= b.plan - b.fixed + 1e-9 or b.placed == 0
        placed_by_team_basis = [
            p for p in own
            if (
                (pr := data.project(p.project) if p.project else None) is None
                or (pr.budget_basis or data.team.tracker.budget_basis)
                is data.team.tracker.budget_basis
            )
        ]  # fmt: skip
        if len(placed_by_team_basis) == len(own):
            assert b.free >= -b.fixed - 1e-9 or b.placed == 0
    # Traffic light and refinement list exist for every project and sprint respectively.
    assert {s.project for s in dist.projects} == {p.id for p in data.projects}
    assert all(r.sprint in index for r in dist.refinement)
    assert all(preplan.REASONS[p.reason] for p in dist.placements)


def test_budget_dataclass_defaults():
    b = Budget(sprint="s", product=None, base=8, plan=10, roadmap=8)
    assert (b.fixed, b.placed, b.free, b.production_available) == (0, 0, 8, None)


# --- Review fixes ----------------------------------------------------------------------------


def test_stored_sprint_that_is_over_does_not_count_as_fixed():
    """tickets.yaml outlives the import: a sprint that has ended since is ignored, so the
    earmark or the normal distribution applies and the ticket consumes budget."""
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [
        ticket("A", 6, in_sprint="2026.3", rank="0|a"),
        ticket("B", 6, in_sprint="2026.3", rank="0|b"),
        ticket("C", 6, in_sprint="2026.3", rank="0|c"),
    ]
    data.preplan = Preplan(earmarks=[Earmark(ticket="C", sprint="2026.9")])
    dist = distribute(data, TODAY)
    s = dist.sprints
    assert [reason_of(dist, k) for k in "ABC"] == ["placed", "placed", "earmark"]
    # Budget 8 per sprint: 6 + 6 do not share a sprint.
    assert [sprint_of(dist, k) for k in "ABC"] == [s[0], s[1], "2026.9"]
    assert dist.budget(s[0], None).placed == 6 and dist.budget("2026.9", None).fixed == 6


def test_a_ticket_in_the_current_sprint_is_still_fixed():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("A", 6, in_sprint="2026.6")]
    dist = distribute(data, TODAY)
    assert (sprint_of(dist, "A"), reason_of(dist, "A")) == ("2026.6", "fixed_sprint")


def test_project_with_target_inside_the_current_sprint():
    data = team_data()
    current = Sprint("2026.6", CURRENT_START, CURRENT_START + timedelta(days=LENGTH))
    inside = TODAY + timedelta(days=2)
    assert current.start <= inside < current.end - timedelta(days=1)
    data.projects = [
        project("now", inside),
        project("later", inside, priority=1),
        project("over", TODAY - timedelta(days=3), priority=2),
    ]
    data.tickets = [
        ticket("A", 3, project="now", in_sprint="2026.6"),
        ticket("B", 3, project="later"),
        ticket("C", 3, project="over", in_sprint="2026.6"),
    ]
    status = {st.project: st for st in distribute(data, TODAY).projects}
    # All work in the current sprint: tight, with the current sprint as target sprint.
    assert (status["now"].light, status["now"].target_sprint) == ("tight", "2026.6")
    # Something lands after the current sprint: missed.
    assert (status["later"].light, status["later"].target_sprint) == ("missed", "2026.6")
    # A target date that is already over stays missed, without target sprint.
    assert (status["over"].light, status["over"].target_sprint) == ("missed", None)
    # Target after the current sprint: work in it is on track.
    data.projects = [project("now", date(2026, 12, 31))]
    data.tickets = [ticket("A", 3, project="now", in_sprint="2026.6")]
    assert distribute(data, TODAY).status("now").light == "on_track"


@pytest.mark.parametrize("sprint", ["2099.1", "2028.3"])
def test_dependency_beyond_the_horizon_blocks_its_dependents(sprint: str):
    """An earmark after the horizon (or in an unknown sprint) is later than everything: the
    dependent ticket cannot be placed before it."""
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [
        ticket("dep", 2, rank="0|a"),
        ticket("after", 2, rank="0|b", depends_on=["dep"]),
    ]
    data.preplan = Preplan(earmarks=[Earmark(ticket="dep", sprint=sprint)])
    dist = distribute(data, TODAY)
    assert sprint_of(dist, "dep") == sprint
    assert sprint_of(dist, "after") is None and reason_of(dist, "after") == "beyond_horizon"
    assert dist.status("p").light == "missed"


def test_ticket_earmarked_after_the_horizon_is_later_than_the_target():
    data = team_data()
    data.projects = [project("p", date(2027, 1, 31))]
    data.tickets = [ticket("far", 2)]
    data.preplan = Preplan(earmarks=[Earmark(ticket="far", sprint="2099.1")])
    dist = distribute(data, TODAY)
    assert "2099.1" in dist.later and dist.status("p").light == "missed"
    # A dependency before the horizon (current sprint) does not hold anything back.
    data.tickets = [ticket("dep", 2, in_sprint="2026.6"), ticket("A", 2, depends_on=["dep"])]
    data.preplan = Preplan()
    assert sprint_of(distribute(data, TODAY), "A") == "2026.7"


def test_no_forecast_is_no_budget_not_too_large():
    data = team_data(velocities=())
    data.projects = [project("p")]
    data.tickets = [ticket("A", 3), ticket("Z", 0)]
    dist = distribute(data, TODAY)
    assert dist.no_forecast
    assert reason_of(dist, "A") == "no_budget"
    assert preplan.REASONS["no_budget"] == "no budget"


def test_project_without_budget_cell_is_no_budget():
    # Products on, project without product: no budget cell at all.
    data = team_data(products=[Product(id="shop", name="Shop")])
    data.projects = [project("a", product="unknown")]
    data.tickets = [ticket("A", 3, project="a")]
    dist = distribute(data, TODAY)
    assert not dist.no_forecast and reason_of(dist, "A") == "no_budget"
    # Products off but the project names one: the implicit product has the budget.
    data = team_data()
    data.projects = [project("a", product="shop")]
    data.tickets = [ticket("A", 3, project="a")]
    assert reason_of(distribute(data, TODAY), "A") == "placed"


def test_too_large_only_above_a_positive_budget():
    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("big", 50), ticket("ok", 5)]
    dist = distribute(data, TODAY)
    assert reason_of(dist, "big") == "too_large" and not dist.no_forecast
    assert reason_of(dist, "ok") == "placed"


def test_earmark_of_a_sprint_that_is_over_is_ignored():
    """An open ticket cannot be put into the past: the normal distribution applies."""
    data = team_data()
    data.projects = [project("p", date(2026, 12, 31))]
    data.tickets = [ticket("A", 5)]
    data.preplan = Preplan(earmarks=[Earmark(ticket="A", sprint="2026.5")])
    dist = distribute(data, TODAY)
    assert (sprint_of(dist, "A"), reason_of(dist, "A")) == (dist.sprints[0], "placed")
    assert dist.budget(dist.sprints[0], None).placed == 5
    # An earmark of the current sprint still counts.
    data.preplan = Preplan(earmarks=[Earmark(ticket="A", sprint="2026.6")])
    assert reason_of(distribute(data, TODAY), "A") == "earmark"


def test_sprint_after_the_horizon_is_compared_with_the_target_date():
    from sprintforecast.forecast import find_sprint

    data = team_data()
    data.projects = [project("p")]
    data.tickets = [ticket("far", 2)]
    data.preplan = Preplan(earmarks=[Earmark(ticket="far", sprint="2028.3")])
    sprint = find_sprint(data, "2028.3", 52)
    assert sprint is not None
    last_day = sprint.end - timedelta(days=1)
    assert distribute(data, TODAY).later == {"2028.3": last_day}

    def light(target: date) -> str:
        data.projects = [project("p", target)]
        return distribute(data, TODAY).status("p").light

    assert light(last_day - timedelta(days=1)) == "missed"  # the sprint ends after the target
    assert light(last_day) == "tight"  # it is the target sprint
    assert light(last_day + timedelta(days=100)) == "on_track"  # the target is later still
    # A sprint the calendar does not know stays missed.
    data.preplan = Preplan(earmarks=[Earmark(ticket="far", sprint="2099.1")])
    assert light(date(2099, 12, 31)) == "missed"


# --- Product rules: tickets without a project -----------------------------------------------


def product_data() -> TeamData:
    from sprintforecast.model import Rule

    data = team_data(products=[Product("shop", "Shop"), Product("platform", "Platform")])
    data.products[0].match = Rule(source="label", values=["shop"])
    data.products[1].match = Rule(source="label", values=["plat"])
    data.projects = [project("pay", product="shop")]
    return data


def test_ticket_without_project_uses_the_budget_of_its_product_by_rule():
    data = product_data()
    data.tickets = [
        ticket("A", 3, project=None, labels=["plat"]),
        ticket("B", 3, project=None, labels=[]),
        ticket("C", 3, project="pay"),
    ]
    dist = distribute(data, TODAY)
    assert dist.placement("A").product == "platform" and dist.placement("A").reason == "placed"
    assert dist.placement("C").product == "shop"
    assert dist.placement("B").reason == "no_product" and sprint_of(dist, "B") is None
    first = dist.sprints[0]
    assert dist.budget(first, "platform").placed > 0 and dist.budget(first, "shop").placed > 0


def test_project_wins_over_a_contradicting_product_rule():
    data = product_data()
    tk = ticket("A", 3, project="pay", labels=["plat"])
    data.tickets = [tk]
    assert preplan.ticket_product(tk, data) == ("shop", [])
    assert preplan.product_conflict(tk, data) == "platform"
    assert preplan.product_conflict(ticket("B", project="pay", labels=["shop"]), data) is None


def test_two_product_rules_via_the_same_source_contradict():
    data = product_data()
    tk = ticket("A", 3, project=None, labels=["shop", "plat"])
    assert preplan.ticket_product(tk, data) == (None, ["shop", "platform"])


def test_priority_decides_between_a_product_backlog_and_a_project():
    data = product_data()
    data.projects = [project("pay", product="shop", priority=1)]
    data.products[0].priority = 0  # product backlog more important than the project
    data.tickets = [
        ticket("P", 8, project="pay"),
        ticket("B", 8, project=None, labels=["shop"]),
    ]
    assert [tk.key for tk in order_tickets(data)[0]] == ["B", "P"]
    data.products[0].priority = 1  # equal priority: the project (target date) first
    assert [tk.key for tk in order_tickets(data)[0]] == ["P", "B"]
    data.products[0].priority = None  # not given: after every project
    assert [tk.key for tk in order_tickets(data)[0]] == ["P", "B"]


def test_product_rule_and_priority_round_trip_through_products_yaml():
    from sprintforecast.model import Rule
    from sprintforecast.storage import products_from_dict, products_to_dict

    products = [
        Product("shop", "Shop", priority=2, match=Rule(source="label", values=["shop"])),
        Product("platform", "Platform"),
    ]
    again = products_from_dict(products_to_dict(products), "products.yaml")
    assert again[0].priority == 2 and again[0].match == products[0].match
    assert again[1].priority is None and again[1].match is None
