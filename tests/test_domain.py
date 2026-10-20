# SPDX-License-Identifier: EUPL-1.2
"""Domain tests: properties of the calculation, edge cases, hand-calculated examples and a
backtest (retrospective check).

The consistency tests check whether pages match the calculation core. These tests check whether
the calculation core makes sense in terms of the domain, regardless of how it is implemented."""

import random
import statistics
from datetime import date, timedelta
from pathlib import Path

import pytest

from sprintforecast import analysis
from sprintforecast.calendar import team_workdays
from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource, SprintInput, compute
from sprintforecast.forecast import build_forecast
from sprintforecast.model import (
    ForecastSettings,
    Membership,
    Person,
    Sprint,
    Team,
    TrendMode,
)
from sprintforecast.storage import Repository, TeamData

TODAY = date(2026, 10, 15)
MODES = list(TrendMode)
REF = 40.0


# --- Helpers --------------------------------------------------------------------------------


def inputs_for(velocities: list[float | None], capacity: float = 40.0, future: int = 3):
    """Sprints with fixed capacity; ``None`` = open (future)."""
    rows = [
        SprintInput(
            id=str(i),
            capacity=capacity,
            capacity_source=CapacitySource.RECORDED,
            commitment=v,
            velocity=v,
            scope_creep=None,
        )
        for i, v in enumerate(velocities)
    ]
    rows += [
        SprintInput(
            id=f"f{i}",
            capacity=capacity,
            capacity_source=CapacitySource.RECORDED,
            commitment=None,
            velocity=None,
            scope_creep=None,
        )
        for i in range(future)
    ]
    return rows


def settings(mode: TrendMode, window: int = 5) -> ForecastSettings:
    return ForecastSettings(reference_capacity=REF, window=window, trend_mode=mode)


def team_data(velocities: list[float], capacity: float = 40.0, window: int = 5) -> TeamData:
    team = Team(key="t", name="T")
    team.forecast.reference_capacity = REF
    team.forecast.window = window
    start = date(2026, 1, 7)
    sprints = []
    for i, v in enumerate(velocities):
        s = start + timedelta(days=14 * i)
        sprints.append(
            Sprint(
                f"2026.{i + 1}",
                s,
                s + timedelta(days=14),
                capacity=capacity,
                velocity=v,
                commitment=v,
            )
        )
    team.sprint.first_id, team.sprint.first_start = "2026.1", start
    return TeamData(team=team, sprints=sprints)


def person(pid="a", fte=1.0, workweek=None, since=date(2020, 1, 1)) -> Person:
    return Person(pid, pid.upper(), workweek=workweek, memberships=[Membership(since, fte=fte)])


def sprint_at(start: date, days: int = 14, absences=None) -> Sprint:
    return Sprint("x", start, start + timedelta(days=days), absences=absences or {})


def capacity_of(people, sprint, **team_kw) -> float:
    team = Team(key="t", name="T")
    team.capacity.region = "NW"
    for key, value in team_kw.items():
        setattr(team.capacity, key, value)
    return sprint_capacity(team, people, sprint).capacity


# --- Properties of the calculation core -----------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("window", [1, 3, 5])
def test_constant_velocity_gives_constant_forecast(mode, window):
    """Constant velocity → constant forecast, in every trend mode."""
    results = compute(inputs_for([10.0] * 12), settings(mode, window))
    future = results[12:]
    assert [r.plan for r in future] == [10.0, 10.0, 10.0]
    assert not any(r.trend_fallback for r in future)


@pytest.mark.parametrize("mode", MODES)
def test_forecast_scales_with_capacity_not_with_noise_in_capacity(mode):
    """Same normalized velocity: half the capacity → half the forecast."""
    rows = inputs_for([10.0] * 8, future=0)
    rows += [
        SprintInput("half", 20.0, CapacitySource.RECORDED, None, None, None),
        SprintInput("full", 40.0, CapacitySource.RECORDED, None, None, None),
    ]
    r = compute(rows, settings(mode))
    assert r[-2].plan == pytest.approx(r[-1].plan / 2)


@pytest.mark.parametrize("seed", range(10))
def test_plan_lies_within_band_for_default_mode(seed):
    """The plan (flat) lies within the range of the last Sprints."""
    rng = random.Random(seed)
    data = team_data([max(1.0, rng.gauss(12, 3)) for _ in range(14)])
    fc = build_forecast(data, date(2026, 1, 7) + timedelta(days=14 * 14))
    assert data.team.forecast.trend_mode is TrendMode.FLAT
    for e in fc.upcoming():
        b = analysis.band(fc, e)
        assert b is not None and b.low <= e.result.plan <= b.high


def test_classic_and_linear_can_leave_the_band():
    """Rationale for the flat default (A1): linear extrapolates noise and, after a few future
    Sprints, lies outside its own range."""
    values = [10, 11, 13, 14, 16, 17, 19, 21, 22, 24]  # rising
    data = team_data([float(v) for v in values])
    data.team.forecast.trend_mode = TrendMode.LINEAR
    data.team.forecast.horizon = 5
    fc = build_forecast(data, date(2026, 1, 7) + timedelta(days=14 * len(values)))
    outside = [
        e.sprint.id
        for e in fc.upcoming()
        if (b := analysis.band(fc, e)) and not b.low <= e.result.plan <= b.high
    ]
    assert outside, "linear sollte bei steigender Reihe aus der Bandbreite laufen"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seed", range(5))
def test_forecast_is_never_negative(mode, seed):
    rng = random.Random(seed)
    falling = [max(0.0, 40 - 5 * i + rng.gauss(0, 2)) for i in range(10)]
    for r in compute(inputs_for(falling, future=6), settings(mode, window=3)):
        assert r.plan is None or r.plan >= 0
        assert r.normalized_velocity.trend is None or r.normalized_velocity.trend >= 0


def test_holiday_sprint_has_less_capacity_than_normal_sprint():
    people = [person("a"), person("b", fte=0.5)]
    normal = sprint_at(date(2026, 11, 2))  # 10 working days
    christmas = sprint_at(date(2026, 12, 21))  # Dec 25 (Fri) and Jan 1 (Fri) fall inside
    assert len(team_workdays(Team(key="t", name="T"), normal.start, normal.end)) == 10
    assert capacity_of(people, christmas) < capacity_of(people, normal)
    assert capacity_of(people, normal) == pytest.approx(15.0)  # (1 + 0.5) × 10
    assert capacity_of(people, christmas) == pytest.approx(12.0)  # (1 + 0.5) × 8


@pytest.mark.parametrize("seed", range(8))
def test_more_people_never_means_less_capacity(seed):
    rng = random.Random(seed)
    sprint = sprint_at(date(2026, 10, 14), absences={"p0": rng.choice([0, 1, 2])})
    people: list[Person] = []
    previous = 0.0
    for n in range(6):
        people.append(person(f"p{n}", fte=rng.choice([0.2, 0.5, 0.8, 1.0])))
        for kw in ({}, {"overhead_share": 0.1}, {"overhead_days": 1.0}):
            now = capacity_of(people, sprint, **kw)
            if not kw:
                assert now >= previous
                previous = now
            assert now >= 0


@pytest.mark.parametrize("days", [7, 14, 21, 28])
def test_different_sprint_lengths_scale_capacity(days):
    """Capacity counts working days: 7 calendar days ≈ 5 working days etc. (without holidays)."""
    start = date(2026, 3, 2)  # Monday, no holidays until the end of March
    people = [person("a")]
    assert capacity_of(people, sprint_at(start, days)) == pytest.approx(days / 7 * 5)


# --- Edge cases -------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [TrendMode.CLASSIC, TrendMode.LINEAR])
def test_exactly_window_sprints_gives_flat_with_note(mode):
    """A4: Exactly ``window`` Sprints of history → a forecast instead of none, with a note."""
    results = compute(inputs_for([8.0, 10.0, 12.0], future=2), settings(mode, window=3))
    assert [r.plan for r in results[3:]] == [10.0, 10.0]
    assert all(r.trend_fallback for r in results[3:])


def test_empty_history_gives_no_forecast_and_no_error():
    results = compute(inputs_for([], future=3), settings(TrendMode.FLAT))
    assert [r.plan for r in results] == [None, None, None]


def test_one_value_below_window_gives_no_trend():
    results = compute(inputs_for([10.0], future=2), settings(TrendMode.FLAT, window=3))
    assert [r.plan for r in results[1:]] == [None, None]


def test_fte_zero_gives_zero_capacity_and_no_division_error():
    sprint = sprint_at(date(2026, 10, 14))
    assert capacity_of([person("a", fte=0.0)], sprint) == 0.0
    # Sprint with capacity 0: normalized velocity undefined, forecast without crashing
    rows = [
        *inputs_for([10.0] * 6, future=0),
        SprintInput("zero", 0.0, CapacitySource.RECORDED, None, 5.0, None),
        *inputs_for([], future=1),
    ]
    results = compute(rows, settings(TrendMode.FLAT))
    assert results[6].normalized_velocity.value is None
    assert results[7].plan is not None


def test_gaps_do_not_count_as_values():
    """A4: Gaps (Sprints without velocity) do not count; the window reaches back further."""
    values: list[float | None] = [10.0, 10.0, None, 10.0, None, 10.0, 10.0]
    results = compute(inputs_for(values, future=1), settings(TrendMode.FLAT, window=5))
    assert results[-1].plan == 10.0
    assert results[-1].samples == 5


# --- Hand-calculated examples: FTE, work week, overhead, absences --------------------------

START = date(2026, 3, 2)  # Monday; 10 working days until Mar 16, no holidays


def test_fte_is_share_of_the_persons_working_days():
    """A6: Mon-Fri + FTE 0.8 = four-day week + FTE 1 = 8 PD; both together would deduct twice."""
    s = sprint_at(START)
    assert capacity_of([person(fte=0.8)], s) == pytest.approx(8.0)
    assert capacity_of([person(fte=1.0, workweek="mon,tue,wed,thu")], s) == pytest.approx(8.0)
    doubled = capacity_of([person(fte=0.8, workweek="mon,tue,wed,thu")], s)
    assert doubled == pytest.approx(6.4)  # 8 × 0.8: the case the help warns about
    assert capacity_of([person(fte=0.5)], s) == pytest.approx(5.0)


def test_absences_are_taken_in_person_days_times_fte():
    s = sprint_at(START, absences={"a": 2})
    assert capacity_of([person(fte=1.0)], s) == pytest.approx(8.0)
    assert capacity_of([person(fte=0.5)], s) == pytest.approx(4.0)  # (5 − 2 × 0.5)


def test_overhead_days_replace_percentage_for_confirmed_and_expected_absences():
    """A8: One combined calculation. Fixed PD replace the percentage deduction (not added)."""
    s = sprint_at(START)
    people = [person("a"), person("b", fte=0.5)]
    assert capacity_of(people, s, overhead_share=0.1) == pytest.approx(13.5)  # 15 − 10%
    assert capacity_of(people, s, overhead_days=1.0) == pytest.approx(13.5)  # 15 − (1 + 0.5)
    both = capacity_of(people, s, overhead_share=0.1, overhead_days=1.0)
    assert both == pytest.approx(13.5)  # not 12.0


def test_expected_and_estimated_absences_use_the_same_overhead_rule():
    """Confirmed absences (2 days), expected rate (20%) and announced absences calculate the
    same: absences first, then overhead, then rounding."""
    people = [person("a")]
    team = Team(key="t", name="T")
    team.capacity.region = "NW"
    team.capacity.overhead_days = 1.0
    confirmed = sprint_at(START, absences={"a": 2})
    assert sprint_capacity(team, people, confirmed).capacity == pytest.approx(7.0)  # 8 − 1
    estimated = sprint_capacity(team, people, sprint_at(START), absence_rate=0.2).capacity
    assert estimated == pytest.approx(7.0)  # 10 × 0.8 − 1
    assert sprint_capacity(team, people, sprint_at(START), absence_rate=0.2).overhead == 1.0


def test_unknown_absences_still_use_calendar_and_people():
    """A2: Capacity of future Sprints without absences comes from the calendar and people, not
    from the trend, here with a holiday Sprint that a trend cannot know about."""
    data = team_data([10.0] * 6)
    data.people = [person("a")]
    data.team.capacity.region = "NW"
    for s in data.sprints:
        s.capacity = None
        s.velocity = None
    data.sprints = data.sprints[:0]
    data.team.sprint.first_start = date(2026, 12, 21)  # first Sprint contains 2 holidays
    data.team.sprint.first_id = "2026.1"
    fc = build_forecast(data, date(2026, 12, 1))
    first, second = fc.entries[0], fc.entries[1]
    assert first.result.plan_capacity_source is CapacitySource.CALENDAR
    assert first.result.plan_capacity == pytest.approx(8.0)  # 10 − 2 holidays
    assert second.result.plan_capacity == pytest.approx(10.0)
    assert first.result.plan_capacity < second.result.plan_capacity


# --- Backtest ----------------------------------------------------------------------------------


def predict(
    values: list[float], mode: TrendMode, window: int, capacity: float = 40.0, ahead: int = 1
) -> float:
    """Normalized velocity that would be forecast for the Sprint ``ahead`` Sprints after
    ``values`` (1 = the next one)."""
    results = compute(inputs_for(values, capacity, future=ahead), settings(mode, window))
    trend = results[-1].normalized_velocity.trend
    assert trend is not None
    return trend


def backtest(series: list[float], window: int = 5, ahead: int = 1) -> dict[str, float]:
    """For each Sprint from ``window`` + 2 on: forecast with the data available at the time
    (``ahead`` Sprints earlier) and compare with the actual value (mean absolute error per
    method)."""
    errors: dict[str, list[float]] = {m.value: [] for m in MODES} | {"mean": [], "median": []}
    for i in range(window + 2 + ahead - 1, len(series)):
        past, actual = series[: i - ahead + 1], series[i]
        for mode in MODES:
            errors[mode.value].append(abs(predict(past, mode, window, ahead=ahead) - actual))
        recent = past[-window:]
        errors["mean"].append(abs(statistics.fmean(recent) - actual))
        errors["median"].append(abs(statistics.median(recent) - actual))
    return {name: statistics.fmean(values) for name, values in errors.items()}


def stationary(seed: int, n: int = 40) -> list[float]:
    rng = random.Random(seed)
    return [max(1.0, rng.gauss(12, 2.5)) for _ in range(n)]


def test_backtest_flat_equals_the_constant_mean_forecast():
    """flat is the constant forecast from the mean of the last Sprints, and not worse."""
    for seed in range(5):
        result = backtest(stationary(seed))
        assert result["flat"] == pytest.approx(result["mean"])


def test_backtest_default_mode_is_best_on_stationary_series():
    """On stationary series with noise the default is better than classic/linear and not worse
    than the constant forecast (mean, median)."""
    totals: dict[str, list[float]] = {}
    for seed in range(20):
        for name, error in backtest(stationary(seed)).items():
            totals.setdefault(name, []).append(error)
    mae = {name: statistics.fmean(v) for name, v in totals.items()}
    assert mae["flat"] < mae["classic"] and mae["flat"] < mae["linear"]
    assert mae["flat"] <= mae["mean"] + 1e-9
    assert mae["flat"] <= mae["median"] * 1.05  # the median is not better for normal noise


def test_backtest_three_sprints_ahead_penalizes_extrapolating_noise():
    """The further ahead, the more extrapolating noise hurts (A1)."""
    totals: dict[str, list[float]] = {}
    for seed in range(20):
        for name, error in backtest(stationary(seed), ahead=3).items():
            totals.setdefault(name, []).append(error)
    mae = {name: statistics.fmean(v) for name, v in totals.items()}
    assert mae["flat"] < mae["classic"] * 0.9
    assert mae["flat"] < mae["linear"] * 0.9
    assert mae["flat"] <= mae["mean"] + 1e-9


def test_backtest_trend_series_shows_when_linear_is_better():
    """With a real, stable trend ``linear`` beats the default, which is why it stays
    explicitly selectable but is not the default."""
    series = [10 + 0.6 * i + random.Random(i).gauss(0, 0.3) for i in range(40)]
    result = backtest(series)
    assert result["linear"] < result["flat"]


def test_backtest_jump_series_flat_recovers_after_one_window():
    """After a jump (team change) the default catches up with the new level after one window."""
    rng = random.Random(3)
    series = [max(1.0, rng.gauss(10, 1)) for _ in range(20)]
    series += [max(1.0, rng.gauss(16, 1)) for _ in range(20)]
    window = 5
    late = [
        abs(predict(series[:i], TrendMode.FLAT, window) - series[i])
        for i in range(20 + window + 1, 40)  # from one window after the jump on
    ]
    early = [
        abs(predict(series[:i], TrendMode.FLAT, window) - series[i]) for i in range(20, 20 + window)
    ]
    assert statistics.fmean(late) < statistics.fmean(early) / 2


def demo_series() -> list[float]:
    data = Repository(Path(__file__).parent.parent / "examples" / "teams").load("demo")
    fc = build_forecast(data, TODAY)
    return [
        v
        for e in fc.history()
        if (v := e.result.normalized_velocity.value) is not None  # reference of the demo team
    ]


def test_backtest_on_demo_history_default_mode_is_not_worse_than_constant_forecast():
    series = demo_series()
    assert len(series) >= 15
    result = backtest(series)
    assert result["flat"] <= result["mean"] + 1e-9
    assert result["flat"] <= result["classic"]  # classic lags behind the noise
    assert result["flat"] <= result["linear"]


def test_plan_of_demo_lies_in_band():
    data = Repository(Path(__file__).parent.parent / "examples" / "teams").load("demo")
    fc = build_forecast(data, TODAY)
    for e in fc.upcoming():
        b = analysis.band(fc, e)
        assert b is not None and b.low <= e.result.plan <= b.high


def test_fte_change_within_sprint_weights_absences_with_mean_fte():
    """A7: Approximation for an FTE change within the Sprint, hand-calculated and marked as such."""
    changing = Person(
        "a",
        "A",
        memberships=[
            Membership(date(2020, 1, 1), date(2026, 3, 6), fte=1.0),
            Membership(date(2026, 3, 9), fte=0.5),
        ],
    )
    team = Team(key="t", name="T")
    team.capacity.region = "NW"
    sprint = sprint_at(START, absences={"a": 2})
    breakdown = sprint_capacity(team, [changing], sprint)
    # 5 days × 1 + 5 days × 0.5 = 7.5; mean FTE 0.75; 2 absences × 0.75 = 1.5
    assert breakdown.capacity == pytest.approx(6.0)
    assert breakdown.people[0].fte_changes
    assert [p.person.id for p in breakdown.approximated] == ["a"]
    steady = sprint_capacity(team, [person("b", fte=0.5)], sprint_at(START, absences={"b": 2}))
    assert not steady.people[0].fte_changes and not steady.approximated
    # without absences nothing is approximated
    assert not sprint_capacity(team, [changing], sprint_at(START)).approximated


@pytest.mark.parametrize("mode", MODES)
def test_reference_capacity_does_not_change_the_forecast(mode):
    """A13: The reference capacity cancels out; it is only a display scale.
    Focus factor and normalized velocity are the same quantity (norm. velocity = focus factor ×
    reference)."""
    rng = random.Random(7)
    values = [max(1.0, rng.gauss(12, 3)) for _ in range(10)]
    plans = []
    for ref in (20.0, 40.0, 67.0, 100.0):
        s = ForecastSettings(reference_capacity=ref, window=5, trend_mode=mode, rounding=6)
        results = compute(inputs_for(values, capacity=33.0, future=3), s)
        plans.append([r.plan for r in results[10:]])
        for r in results[:10]:
            focus = r.velocity.value / r.capacity.value
            assert r.normalized_velocity.value == pytest.approx(focus * ref)
    for other in plans[1:]:
        assert other == pytest.approx(plans[0], abs=2e-6)
