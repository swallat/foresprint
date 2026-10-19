# SPDX-License-Identifier: EUPL-1.2
"""Ticket pre-planning, step 4: variants, range and handover
(docs/design/ticket-planning.md, sections 5.5 and 10)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from test_preplan import TODAY, future, project, team_data, ticket

from sprintforecast.analysis import band, horizon_forecast
from sprintforecast.model import (
    BudgetBasis,
    Earmark,
    EstimateSource,
    ManualEstimate,
    Membership,
    Person,
    Preplan,
    Product,
    ProductValues,
    Sprint,
    Ticket,
)
from sprintforecast.preplan import (
    Distribution,
    ProjectStatus,
    Variant,
    Variants,
    distribute,
    distribute_variants,
    handover_rows,
    project_range,
    ticket_range,
)
from sprintforecast.storage import TeamData

# Normalized velocities 6..14: the plan per future sprint is 6 (conservative), 10 (median, the
# Forecast PLAN) and 14 (optimistic); with the plannable share of 80 % the budgets are 4.8, 8
# and 11.2.
SPREAD = (6, 8, 10, 12, 14)


def spread_data(**tracker: object) -> TeamData:
    return team_data(velocities=SPREAD, **tracker)


# --- Plans per variant ---------------------------------------------------------------------


def test_variant_plans_follow_the_band_of_the_forecast():
    """Conservative and optimistic recalculate the plan like ``analysis.band``; the median is
    the Forecast PLAN."""
    data = spread_data()
    # With a people list the capacity of the future sprints comes from the calendar.
    data.people = [Person(id="a", name="A", memberships=[Membership(start=date(2026, 1, 1))])]
    variants = distribute_variants(data, TODAY)
    assert variants.available and variants.samples == 5
    fc = horizon_forecast(data, TODAY)
    for sprint_id in ("2026.7", "2026.8", "2026.12"):
        b = band(fc, fc.entry(sprint_id))
        assert variants.conservative.budget(sprint_id, None).plan == b.low
        assert variants.optimistic.budget(sprint_id, None).plan == b.high
        assert variants.median.budget(sprint_id, None).plan == fc.entry(sprint_id).result.plan
        assert b.low < b.high


def test_variant_plans_beyond_the_people_list_use_the_average_capacity():
    data = spread_data()
    variants = distribute_variants(data, TODAY)
    plans = {v: {b.plan for b in dist.budgets} for v, dist in variants.items()}
    assert plans == {
        Variant.OPTIMISTIC: {14.0},
        Variant.MEDIAN: {10.0},
        Variant.CONSERVATIVE: {6.0},
    }
    for dist in (variants.conservative, variants.optimistic):
        assert all(b.base == pytest.approx(b.plan * 0.8) for b in dist.budgets)
    assert [d.variant for _, d in variants.items()] == [
        Variant.OPTIMISTIC,
        Variant.MEDIAN,
        Variant.CONSERVATIVE,
    ]


def test_budget_basis_plan_applies_to_every_variant():
    variants = distribute_variants(spread_data(budget_basis=BudgetBasis.PLAN), TODAY)
    assert variants.conservative.budgets[0].base == 6.0
    assert variants.optimistic.budgets[0].base == 14.0


def fixtures() -> list[TeamData]:
    plain = team_data()
    with_tickets = spread_data()
    with_tickets.projects = [project("p"), project("q", date(2027, 1, 31), product=None)]
    with_tickets.tickets = [
        ticket("A", 5, rank="0|a"),
        ticket("B", 3, source=EstimateSource.ROUGH, rank="0|b", depends_on=["A"]),
        ticket("C", 8, rank="0|c", in_sprint="2026.8"),
        ticket("D", None, rank="0|d"),
        ticket("E", 2, project="q", rank="0|e", refined_unclear=True),
    ]
    with_tickets.preplan = Preplan(
        earmarks=[Earmark(ticket="B", sprint="2026.10")],
        estimates=[ManualEstimate(ticket="D", estimate=2)],
    )
    shop = team_data(products=[Product(id="x", name="X"), Product(id="y", name="Y")])
    shop.projects = [project("p", product="x"), project("q", product="y")]
    shop.tickets = [
        ticket(f"T{i}", 3, project=("p", "q")[i % 2], rank=f"0|{i:02d}") for i in range(9)
    ]
    return [plain, with_tickets, shop]


@pytest.mark.parametrize("index", range(3))
def test_median_is_the_distribution_of_before(index: int):
    """The median variant is today's distribution, unchanged (the Forecast PLAN)."""
    data = fixtures()[index]
    plain = distribute(data, TODAY)
    assert plain.variant is Variant.MEDIAN
    assert distribute(data, TODAY, variant="median") == plain
    assert distribute_variants(data, TODAY).median == plain
    assert distribute(data, TODAY, max_sprints=8).sprints == plain.sprints[:8]


def test_variant_argument_accepts_strings_and_rejects_unknown_names():
    data = spread_data()
    assert distribute(data, TODAY, variant="conservative").variant is Variant.CONSERVATIVE
    with pytest.raises(ValueError):
        distribute(data, TODAY, variant="pessimistic")


# --- rough_factor ----------------------------------------------------------------------------


def rough_data(factor: float = 1.5) -> TeamData:
    data = spread_data(rough_factor=factor)
    data.projects = [project("p")]
    data.tickets = [
        ticket("rough", 4, source=EstimateSource.ROUGH, rank="0|a"),
        ticket("unclear", 2, rank="0|b", refined_unclear=True),
        ticket("refined", 2, rank="0|c"),
        ticket("manual", 2, source=EstimateSource.MANUAL, rank="0|d"),
        ticket("own", None, rank="0|e"),
    ]
    data.preplan = Preplan(estimates=[ManualEstimate(ticket="own", estimate=2)])
    return data


def test_rough_factor_applies_only_in_the_conservative_variant():
    variants = distribute_variants(rough_data(), TODAY)
    sizes = {v: {p.ticket: p.size for p in dist.placements} for v, dist in variants.items()}
    plain = {"rough": 4, "unclear": 2, "refined": 2, "manual": 2, "own": 2}
    assert sizes[Variant.MEDIAN] == plain
    assert sizes[Variant.OPTIMISTIC] == plain
    # Rough and unclear-refined estimates are inflated, refined and manual ones are not.
    assert sizes[Variant.CONSERVATIVE] == {
        "rough": 6, "unclear": 3, "refined": 2, "manual": 2, "own": 2,
    }  # fmt: skip
    assert distribute(rough_data(), TODAY, variant="conservative").placement("rough").size == 6


def test_rough_factor_changes_the_placement_in_the_conservative_variant_only():
    data = spread_data(rough_factor=3.0)
    data.projects = [project("p")]
    # Median budget 8: 4 + 4 fit together; conservative budget 4.8: 12 does not fit at all.
    data.tickets = [
        ticket("rough", 4, source=EstimateSource.ROUGH, rank="0|a"),
        ticket("fine", 4, rank="0|b"),
    ]
    variants = distribute_variants(data, TODAY)
    first = variants.median.sprints[0]
    assert variants.median.placement("rough").sprint == first
    assert variants.optimistic.placement("rough").sprint == first
    assert variants.median.placement("fine").sprint == first
    assert variants.conservative.placement("rough").reason == "too_large"
    assert variants.conservative.placement("fine").sprint == first
    # A factor of 1 changes nothing for the sizes.
    data.team.tracker.rough_factor = 1.0
    sizes = {p.ticket: p.size for p in distribute(data, TODAY, variant="conservative").placements}
    assert sizes == {"rough": 4, "fine": 4}


# --- Too little history --------------------------------------------------------------------


def test_too_little_history_returns_only_the_median():
    data = team_data(velocities=(10,))
    data.projects = [project("p")]
    data.tickets = [ticket("A", 3)]
    variants = distribute_variants(data, TODAY)
    assert not variants.available and variants.samples == 1
    assert variants.conservative is None and variants.optimistic is None
    assert variants.median == distribute(data, TODAY)
    assert [v for v, _ in variants.items()] == [Variant.MEDIAN]
    assert variants.get("conservative") is None and variants.get(Variant.MEDIAN) is variants.median
    with pytest.raises(ValueError):
        distribute(data, TODAY, variant=Variant.OPTIMISTIC)
    # The range of a project is the median alone.
    span = project_range(variants, "p")
    assert not span.available and span.uniform
    assert span.earliest == span.latest == variants.median.status("p").last_sprint
    assert span.light_range == (span.worst_light, span.worst_light)
    assert set(ticket_range(variants, "A").sprints) == {Variant.MEDIAN}


def test_no_history_at_all_still_returns_the_median():
    variants = distribute_variants(team_data(velocities=()), TODAY)
    assert not variants.available and variants.samples == 0
    assert variants.median.no_forecast


# --- Range -----------------------------------------------------------------------------------


def stacked_data() -> TeamData:
    """Nine tickets of 3: one per sprint (conservative, budget 4.8), two (median, 8) and three
    (optimistic, 11.2) -> last sprint index 8, 4 and 2."""
    data = spread_data()
    data.projects = [project("p")]
    data.tickets = [ticket(f"T-{i}", 3, rank=f"0|{i:02d}") for i in range(9)]
    return data


def test_project_range_is_minimum_and_maximum_over_the_variants():
    data = stacked_data()
    variants = distribute_variants(data, TODAY)
    sprints = variants.median.sprints
    assert variants.optimistic.status("p").last_sprint == sprints[2]
    # Target in the fifth sprint: optimistic on track, median tight, conservative missed.
    data.projects[0].target = future(variants.median, data)[4].end - timedelta(days=1)
    variants = distribute_variants(data, TODAY)
    span = project_range(variants, "p")
    assert span.available and span.complete
    assert span.last_sprint == {
        Variant.OPTIMISTIC: sprints[2],
        Variant.MEDIAN: sprints[4],
        Variant.CONSERVATIVE: sprints[8],
    }
    assert span.light == {
        Variant.OPTIMISTIC: "on_track",
        Variant.MEDIAN: "tight",
        Variant.CONSERVATIVE: "missed",
    }
    assert (span.earliest, span.latest) == (sprints[2], sprints[8])
    assert span.light_range == ("on_track", "missed") and not span.uniform and not span.on_track
    # Tickets: the first one is in the first sprint everywhere, the last one moves.
    first, last = ticket_range(variants, "T-0"), ticket_range(variants, "T-8")
    assert first.fixed and first.earliest == sprints[0]
    assert (last.earliest, last.latest) == (sprints[2], sprints[8]) and not last.fixed
    assert ticket_range(variants, "no-such-ticket") is None


def test_a_ticket_too_large_in_one_variant_makes_the_project_missed_there():
    data = spread_data()
    data.projects = [project("p")]
    data.tickets = [ticket("big", 5)]  # conservative budget 4.8 < 5 <= 8
    variants = distribute_variants(data, TODAY)
    span = project_range(variants, "p")
    assert span.light[Variant.CONSERVATIVE] == "missed"
    assert span.light[Variant.MEDIAN] == span.light[Variant.OPTIMISTIC] == "on_track"
    assert span.light_range == ("on_track", "missed") and not span.complete
    # No placed ticket in the conservative variant: the sprint range comes from the others.
    assert span.last_sprint[Variant.CONSERVATIVE] is None
    assert span.earliest == span.latest == variants.median.sprints[0]
    ticket_span = ticket_range(variants, "big")
    assert not ticket_span.complete and ticket_span.sprints[Variant.CONSERVATIVE] is None
    assert ticket_span.earliest == ticket_span.latest == variants.median.sprints[0]


def fake(variant: Variant, sprints: list[str], status: ProjectStatus) -> Distribution:
    return Distribution(sprints=sprints, projects=[status], variant=variant)


def fake_status(last: str | None, light: str, not_distributable: int = 0) -> ProjectStatus:
    return ProjectStatus("p", light, "S3", last, 1, not_distributable)


def test_the_range_does_not_assume_monotonicity_across_the_variants():
    """Greedy placement can finish earlier with a smaller budget: earliest and latest are the
    minimum and maximum over the variants, not the optimistic and the conservative one."""
    sprints = [f"S{i}" for i in range(1, 7)]
    variants = Variants(
        median=fake(Variant.MEDIAN, sprints, fake_status("S6", "missed")),
        conservative=fake(Variant.CONSERVATIVE, sprints, fake_status("S2", "on_track")),
        optimistic=fake(Variant.OPTIMISTIC, sprints, fake_status("S4", "tight")),
    )
    span = project_range(variants, "p")
    assert (span.earliest, span.latest) == ("S2", "S6")
    assert span.light_range == ("on_track", "missed")
    with pytest.raises(KeyError):
        project_range(variants, "unknown")


@pytest.mark.parametrize(
    "lights, expected",
    [
        (("on_track", "on_track", "on_track"), ("on_track", "on_track")),
        (("tight", "on_track", "tight"), ("on_track", "tight")),
        (("missed", "tight", "on_track"), ("on_track", "missed")),
        (("missed", "missed", "tight"), ("tight", "missed")),
        (("empty", "empty", "empty"), ("empty", "empty")),
    ],
)
def test_light_range_orders_on_track_before_tight_before_missed(lights, expected):
    optimistic, median, conservative = lights
    sprints = ["S1", "S2"]
    variants = Variants(
        median=fake(Variant.MEDIAN, sprints, fake_status("S1", median)),
        conservative=fake(Variant.CONSERVATIVE, sprints, fake_status("S1", conservative)),
        optimistic=fake(Variant.OPTIMISTIC, sprints, fake_status("S1", optimistic)),
    )
    span = project_range(variants, "p")
    assert span.light_range == expected
    assert span.on_track == (lights == ("on_track",) * 3)


def test_sprints_after_the_horizon_compare_by_their_last_day():
    sprints = ["S1", "S2"]
    median = fake(Variant.MEDIAN, sprints, fake_status("L2", "missed"))
    median.later = {"L1": date(2030, 1, 1), "L2": date(2030, 6, 1), "U": None}
    other = fake(Variant.OPTIMISTIC, sprints, fake_status("S2", "on_track"))
    other.later = median.later
    cons = fake(Variant.CONSERVATIVE, sprints, fake_status("U", "missed"))
    cons.later = median.later
    span = project_range(Variants(median, cons, other), "p")
    assert (span.earliest, span.latest) == ("S2", "U")  # an unknown sprint counts as latest


# --- Property: every variant respects its own budgets and dependencies ---------------------------


@pytest.mark.parametrize("seed", range(12))
def test_every_variant_respects_its_budgets_and_dependencies(seed: int):
    rng = random.Random(seed)
    products = None
    if rng.random() < 0.5:
        products = [Product(id="x", name="X"), Product(id="y", name="Y", share=0.3)]
    gap = rng.choice([0, 1])
    data = team_data(
        velocities=tuple(rng.choice([4, 6, 8, 10, 12, 16]) for _ in range(5)),
        products=products,
        dependency_gap=gap,
        rough_factor=rng.choice([1.0, 1.5, 2.0]),
    )
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
        tickets.append(
            Ticket(
                key=key,
                estimate=rng.choice([None, 1, 2, 3, 5, 8]),
                estimate_source=rng.choice(list(EstimateSource)),
                refined_unclear=rng.random() < 0.15,
                in_sprint=rng.choice([None] * 6 + ["2026.8", "2026.9"]),
                rank=f"0|{rng.randint(0, 99):02d}",
                depends_on=[k for k in keys[:i] if rng.random() < 0.15],
                project=rng.choice(["p0", "p1", "p2", None]),
                done=rng.random() < 0.1,
            )
        )
    data.tickets = tickets
    data.preplan = Preplan(
        earmarks=[
            Earmark(ticket=k, sprint=rng.choice(["2026.7", "2026.10"]))
            for k in keys
            if rng.random() < 0.1
        ]
    )
    variants = distribute_variants(data, TODAY)
    assert variants.available
    products_of = {p.id: p.product for p in data.projects}
    open_keys = {tk.key for tk in tickets if not tk.done}
    for variant, dist in variants.items():
        assert dist.variant is variant
        index = {s: i for i, s in enumerate(dist.sprints)}
        by_key = {p.ticket: p for p in dist.placements}
        assert set(by_key) == open_keys  # each open ticket exactly once
        for tk in tickets:
            if tk.done:
                continue
            p = by_key[tk.key]
            assert (p.sprint is None) == (not p.distributable)
            if p.reason != "placed":
                continue
            for dep in tk.depends_on:
                if dep in open_keys:
                    dep_place = by_key[dep]
                    assert dep_place.sprint is not None
                    assert index[p.sprint] >= index.get(dep_place.sprint, -1) + gap
        for b in dist.budgets:
            own = [
                p
                for p in dist.placements
                if p.sprint == b.sprint
                and p.reason == "placed"
                and products_of.get(p.project) == b.product
            ]
            assert b.placed == pytest.approx(sum(p.size for p in own))
            # Distributed tickets never exceed the budget of their own variant.
            assert b.placed <= b.plan - b.fixed + 1e-9 or b.placed == 0
    # The budgets differ only by the plan; the conservative plan is the smaller one here.
    for low, mid, high in zip(
        variants.conservative.budgets,
        variants.median.budgets,
        variants.optimistic.budgets,
        strict=True,
    ):
        assert (low.sprint, low.product) == (mid.sprint, mid.product) == (high.sprint, high.product)
        assert low.plan <= high.plan
    for status in variants.median.projects:
        span = project_range(variants, status.project)
        sprints = [s for s in span.last_sprint.values() if s is not None]
        assert (span.earliest is None) == (not sprints)
        assert span.best_light in {"empty", "on_track", "tight", "missed"}


# --- Handover --------------------------------------------------------------------------------


def handover_data() -> TeamData:
    data = team_data(
        velocities=SPREAD,
        products=[Product(id="x", name="X"), Product(id="y", name="Y")],
    )
    data.projects = [project("p", product="x"), project("q", product="y")]
    data.tickets = [
        ticket("A", 3, project="p", rank="0|a"),
        ticket("B", 1, project="p", rank="0|b"),
        ticket("C", 2, project="q", rank="0|c"),
        ticket("D", 1.25, project="q", rank="0|d", in_sprint="2026.8"),
        ticket("E", 1, project="p", rank="0|e", in_sprint="2026.6"),  # the current sprint
        ticket("F", None, project="p", rank="0|f"),  # unestimated
    ]
    data.preplan = Preplan(earmarks=[Earmark(ticket="C", sprint="2026.9")])
    return data


def test_handover_sums_the_sizes_per_sprint_and_product():
    data = handover_data()
    dist = distribute(data, TODAY)
    rows = handover_rows(data, dist, 3)
    assert [(r.sprint, r.product, r.proposed, r.current) for r in rows] == [
        ("2026.7", "x", 4.0, None),  # A + B, distributed
        ("2026.8", "y", 1.3, None),  # D fixed by the tracker (1.25 rounds to 1.3)
        ("2026.9", "y", 2.0, None),  # C earmarked
    ]
    # Only the sprints that are shown count.
    assert [r.sprint for r in handover_rows(data, dist, 1)] == ["2026.7"]
    assert handover_rows(data, dist, 26) == handover_rows(data, dist, 100)


def test_handover_uses_the_sizes_of_the_median_distribution_and_the_current_values():
    data = handover_data()
    data.sprints.append(
        Sprint(
            "2026.7",
            data.sprints[-1].end,
            data.sprints[-1].end + timedelta(days=14),
            products={"x": ProductValues(preplanned=3)},
        )
    )
    rows = handover_rows(data, distribute(data, TODAY), 3)
    first = rows[0]
    assert (first.sprint, first.product, first.current) == ("2026.7", "x", 3)
    assert first.action() == "keep" and first.action(overwrite=True) == "overwrite"
    assert not first.writes() and first.writes(overwrite=True)
    assert rows[1].action() == "write" and rows[1].writes()
    first.current = first.proposed
    assert first.action() == "same" and not first.writes(overwrite=True)


def test_handover_ignores_tickets_without_a_known_product():
    data = handover_data()
    data.projects.append(project("r", product="no-such-product"))
    data.tickets.append(ticket("G", 2, project="r", in_sprint="2026.8"))
    data.tickets.append(ticket("H", 2, project=None, in_sprint="2026.8"))
    rows = handover_rows(data, distribute(data, TODAY), 3)
    assert {(r.sprint, r.product) for r in rows} == {
        ("2026.7", "x"),
        ("2026.8", "y"),
        ("2026.9", "y"),
    }
