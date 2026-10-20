# SPDX-License-Identifier: EUPL-1.2
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from sprintforecast import analysis
from sprintforecast.forecast import build_forecast
from sprintforecast.model import Sprint, Team
from sprintforecast.storage import Repository, TeamData

TODAY = date(2026, 10, 15)


def team_with(velocities: list[float], capacity: float = 40, scope=None) -> TeamData:
    """Completed sprints with fixed capacity; reference 40 → normalized velocity = velocity."""
    team = Team(key="t", name="T")
    team.forecast.reference_capacity = 40
    team.forecast.window = 5
    start = date(2026, 6, 3)
    sprints = []
    for i, v in enumerate(velocities):
        s = start + timedelta(days=14 * i)
        sprints.append(
            Sprint(
                f"2026.{i + 1}", s, s + timedelta(days=14), capacity=capacity, velocity=v,
                commitment=v, scope_creep=None if scope is None else scope[i],
            )
        )  # fmt: skip
    return TeamData(team=team, sprints=sprints)


def test_band_uses_min_median_max_of_recent_sprints():
    data = team_with([30, 8, 10, 12, 20, 14])  # last 5: 8, 10, 12, 20, 14
    fc = build_forecast(data, TODAY)
    entry = fc.upcoming()[0]
    cap = entry.result.plan_capacity
    b = analysis.band(fc, entry)
    assert (b.low, b.mid, b.high, b.samples) == (
        pytest.approx(int(8 / 40 * cap * 10) / 10),
        pytest.approx(int(12 / 40 * cap * 10) / 10),
        pytest.approx(int(20 / 40 * cap * 10) / 10),
        5,
    )


def test_band_needs_history():
    fc = build_forecast(team_with([10]), TODAY)
    assert analysis.band(fc, fc.upcoming()[0]) is None


def test_focus_factor():
    fc = build_forecast(team_with([10, 20, 30], capacity=40), TODAY)
    assert analysis.focus_factor(fc.history()[0]) == pytest.approx(0.25)
    assert analysis.average_focus_factor(fc) == pytest.approx(0.5)


def test_buffer_hint():
    fc = build_forecast(team_with([10] * 5, scope=[0.3, 0.3, 0.3, None, None]), TODAY)
    hint = analysis.buffer_hint(fc)
    assert hint.samples == 3 and hint.average_scope_creep == pytest.approx(0.3)
    assert hint.configured_small_stuff == pytest.approx(0.2)
    assert hint.buffer_too_small
    fc = build_forecast(team_with([10] * 5, scope=[0.1, 0.1, None, None, None]), TODAY)
    assert not analysis.buffer_hint(fc).sufficient_data


def test_completion_is_deterministic_with_constant_velocity():
    # constant velocity 10 at capacity 40 = reference → 10 per sprint, roadmap 80 % → 8
    data = team_with([10] * 5)
    result = analysis.completion(data, TODAY, remaining=20, share=0.8, runs=500)
    future = result.sprints
    assert result.p50 == result.p85 == future[2]  # 8 + 8 + 8 ≥ 20 in the 3rd sprint
    assert result.cumulative[2] == pytest.approx(1.0)
    assert analysis.completion(data, TODAY, remaining=20, share=1.0, runs=10).p85 == future[1]
    # project share 50 % of the roadmap share → 4 per sprint → done in the 5th sprint
    half = analysis.completion(data, TODAY, remaining=20, share=0.8 * 0.5, runs=10)
    assert half.p85 == future[4]
    assert half.per_sprint == pytest.approx(4.0)
    assert analysis.completion(data, TODAY, remaining=20, share=0) is None


def test_completion_on_demo(data_dir: Path):
    data = Repository(data_dir).load("demo")
    result = analysis.completion(data, TODAY, remaining=40, share=0.8)
    order = result.sprints
    assert order.index(result.p50) <= order.index(result.p85)
    assert result.cumulative == sorted(result.cumulative)
    # With a people list the capacity always comes from calendar and people, never from the trend.
    assert result.trend_capacity_sprints == []
    no_people = Repository(data_dir).load("demo")
    no_people.people = []
    trend_only = analysis.completion(no_people, TODAY, remaining=40, share=0.8)
    assert "2026.23" in trend_only.trend_capacity_sprints  # teams without a people list
    assert analysis.completion(data, TODAY, remaining=0, share=1) is None


def test_existing_values_are_unchanged(data_dir: Path):
    """The analyses only add to the results: Forecast PLAN, roadmap, small items stay as before."""
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    upcoming = {e.sprint.id: (e.result.plan, e.result.roadmap) for e in fc.upcoming()}
    # Demo with trend mode flat (default): constant average instead of the classic trend
    assert upcoming["2026.21"] == (9.5, pytest.approx(7.6))
    assert upcoming["2026.22"] == (11.2, pytest.approx(8.96))


def test_buffer_hint_compares_on_the_same_base():
    """A9: scope creep refers to the commitment, the small-items share to the Forecast PLAN;
    the comparison is made on the Forecast PLAN."""
    data = team_with([10.0] * 6, scope=[0.3] * 6)
    fc = build_forecast(data, date(2026, 12, 31))
    hint = analysis.buffer_hint(fc)
    # Plan = commitment (10): 30 % scope creep is 30 % of the plan, more than the 20 % small items
    assert hint.average_scope_creep == pytest.approx(0.3)
    assert hint.average_late_share == pytest.approx(0.3) and hint.buffer_too_small
    for sprint in data.sprints:
        sprint.forecast_plan = 20.0  # planning forecast twice as much
    hint = analysis.buffer_hint(build_forecast(data, date(2026, 12, 31)))
    assert hint.average_scope_creep == pytest.approx(0.3)  # input unchanged
    assert hint.average_late_share == pytest.approx(0.15)  # 0.3 × 10 / 20
    assert not hint.buffer_too_small


def test_completion_note_only_below_the_minimum_of_samples():
    from sprintforecast.report import completion_note

    assert completion_note(analysis.MIN_SAMPLES) is None
    note = completion_note(analysis.MIN_SAMPLES - 1)
    assert note and note.startswith("Wenig Daten: Die Simulation zieht aus nur 4 Sprints")


def test_window_hint_only_when_the_window_really_caps_the_sample():
    """The notice appears only if a window below MIN_SAMPLES actually cuts off values (more
    values exist than in the sample): it says why and names the window. If there are simply no
    more values, a larger window does not help, so no notice."""
    from sprintforecast.report import window_hint

    assert window_hint(analysis.MIN_SAMPLES, 5, 12) == ""
    assert window_hint(8, 8, 12) == ""
    hint = window_hint(3, 3, 12)
    assert "auf 3 Sprints gestellt" in hint and hint.endswith("mehr Werte in die Spanne ein.")
    simulation = window_hint(3, 3, 12, simulation=True)
    assert "auf 3 Sprints gestellt" in simulation
    assert simulation.endswith("mehr Werte in Spanne und Simulation ein.")
    assert window_hint(5, 5, 12, simulation=True) == ""
    # Window 3, but only 2 or exactly 3 values: the window caps nothing.
    assert window_hint(3, 2, 2) == ""
    assert window_hint(3, 3, 3) == ""
    assert window_hint(3, 2, 2, simulation=True) == ""


# --- Plan within the range: running sprint with a recorded review value (velocity) -------


def running_sprint(
    velocities: list[float | None],
    *,
    window: int = 5,
    capacities: list[float] | None = None,
    running: int = -1,
    days_in: int = 5,
):
    """Team data whose sprint ``running`` (default: the last) is running (``today`` is ``days_in``
    days after its start); ``None`` = review value not recorded. Sprints after ``running`` lie in
    the future. Returns ``(data, today)``."""
    data = team_with([v or 0.0 for v in velocities])
    data.team.forecast.window = window
    for i, (sprint, v) in enumerate(zip(data.sprints, velocities, strict=True)):
        if v is None:
            sprint.velocity = sprint.commitment = None
        if capacities is not None:
            sprint.capacity = capacities[i]
    return data, data.sprints[running].start + timedelta(days=days_in)


def future_entries(fc):
    return [e for e in fc.upcoming() if e.sprint.start > fc.today]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("window", [2, 3, 5, 8])
def test_plan_lies_in_band_once_the_running_sprint_has_a_review_value(seed, window):
    """Property: with a recorded velocity of the running sprint, the plan of the following sprints
    (which uses it) and the range are based on the same set of values: the plan lies within the
    range, even if the review value is an outlier and the capacity fluctuates.

    Only the default trend ``flat`` is checked on purpose: only it keeps the plan within the range
    (see ``test_classic_and_linear_can_leave_the_band``); for ``classic``/``linear`` this is a
    known remainder. The guarantee extends up to and including the running sprint (see
    ``test_a_future_sprint_with_a_recorded_value_can_still_leave_the_band``)."""
    rng = random.Random(seed)
    count = rng.randint(3, 14)  # a plan exists from three values on (thin history)
    velocities = [round(rng.uniform(1, 40), 1) for _ in range(count)]
    velocities[-1] = rng.choice([0.5, 80.0, velocities[-1]])  # outlier as review value
    capacities = [rng.choice([20.0, 32.0, 40.0, 48.0]) for _ in range(count)]
    data, today = running_sprint(velocities, window=window, capacities=capacities)
    fc = build_forecast(data, today)
    assert data.team.forecast.trend_mode.value == "flat"
    assert fc.current is not None and fc.current.sprint.velocity == velocities[-1]
    for entry in future_entries(fc):
        b = analysis.band(fc, entry)
        assert b is not None
        assert b.low <= entry.result.plan <= b.high, (entry.sprint.id, b, entry.result.plan)
        assert b.samples == min(window, count)


def test_running_sprints_review_value_enters_band_and_sample_count():
    data, today = running_sprint([10, 12, 8, 14, 11, 30])
    fc = build_forecast(data, today)
    entry = future_entries(fc)[0]
    cap = entry.result.plan_capacity
    assert analysis.normalized_history(fc) == [12.0, 8.0, 14.0, 11.0, 30.0]
    assert analysis.sample_count(fc) == 5
    b = analysis.band(fc, entry)
    assert (b.low, b.high, b.samples) == (
        pytest.approx(int(8 / 40 * cap * 10) / 10),
        pytest.approx(int(30 / 40 * cap * 10) / 10),
        5,
    )
    # The plan uses the mean of the same five values (15), not the mean without the review value
    # (11).
    assert entry.result.plan == pytest.approx(int(15 / 40 * cap * 10) / 10)


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("window", [3, 5])
def test_band_and_samples_are_unchanged_while_no_review_value_is_recorded(seed, window):
    """Without a recorded review value of the running sprint only completed sprints count, as
    before (``fc.history()``)."""
    rng = random.Random(seed)
    velocities: list[float | None] = [
        round(rng.uniform(1, 40), 1) for _ in range(rng.randint(3, 12))
    ]
    velocities.append(None)  # running sprint, review still pending
    data, today = running_sprint(velocities, window=window)
    fc = build_forecast(data, today)
    old = [e.result.normalized_velocity.value for e in fc.history()]
    old = [v for v in old if v is not None][-window:]
    assert analysis.normalized_history(fc) == old
    assert analysis.sample_count(fc) == len(old)
    for entry in future_entries(fc):
        b = analysis.band(fc, entry)
        assert b.samples == len(old)
        assert (b.low, b.high) == (
            pytest.approx(analysis.round_down(min(old) / 40 * entry.result.plan_capacity, 1)),
            pytest.approx(analysis.round_down(max(old) / 40 * entry.result.plan_capacity, 1)),
        )
        assert b.low <= entry.result.plan <= b.high


def test_completed_sprints_forecast_numbers_do_not_change():
    """Only range, sample and simulation change, not the forecast of completed sprints or of
    following sprints without a new value."""
    data, today = running_sprint([10, 12, 8, 14, 11, None])
    before = [(e.sprint.id, e.result.plan) for e in build_forecast(data, today).entries]
    data.sprints[-1].velocity = 11.0  # record review value: changes only the following sprints
    after = build_forecast(data, today).entries
    closed = [e for e in after if e.sprint.end <= today]
    assert [(e.sprint.id, e.result.plan) for e in closed] == before[: len(closed)]


@pytest.mark.parametrize("window", [1, 2, 3, 5, 8])
def test_sample_count_is_capped_at_the_window(window):
    data, today = running_sprint([float(10 + i) for i in range(12)], window=window)
    fc = build_forecast(data, today)
    assert analysis.sample_count(fc) == window
    assert len(analysis.normalized_history(fc)) == window
    if window >= 2:  # fewer than two values: no simulation (minimum stays)
        assert analysis.completion(data, today, 20, 1.0, runs=20).samples == window
    else:
        assert analysis.completion(data, today, 20, 1.0, runs=20) is None
    # The threshold stays fixed at MIN_SAMPLES: teams with a window below 5 always see the notice.
    assert analysis.few_samples(fc) is (window < analysis.MIN_SAMPLES)


def test_running_sprint_counts_on_its_first_day():
    """On the start day (``start == today``) the sprint already runs: its review value counts."""
    data, today = running_sprint([10.0, 12.0, 8.0, 14.0], days_in=0)
    assert today == data.sprints[-1].start
    fc = build_forecast(data, today)
    assert fc.current is not None and fc.current.sprint.id == data.sprints[-1].id
    assert analysis.normalized_history(fc) == [10.0, 12.0, 8.0, 14.0]
    assert analysis.sample_count(fc) == 4


def test_a_future_sprint_with_a_recorded_value_can_still_leave_the_band():
    """KNOWN, DELIBERATELY OPEN EDGE CASE (import/file): the engine also averages in a future sprint
    with a recorded value, the range does not count it. The plan then lies outside. This test
    records the actual behavior; the decision is up to the owner."""
    data, today = running_sprint([10, 12, 8, 14, 11, None, 60], running=5)
    fc = build_forecast(data, today)
    assert fc.current.sprint.id == data.sprints[5].id
    assert analysis.normalized_history(fc) == [10.0, 12.0, 8.0, 14.0, 11.0]
    after = next(e for e in fc.entries if e.sprint.start > data.sprints[6].start)
    b = analysis.band(fc, after)
    assert b.samples == 5
    assert after.result.plan > b.high  # plan (mean with the 60) above the range 8–14


def test_gap_notice_uses_the_same_sprints_as_the_average():
    """The gap notice considers the same sprints as the calculation (incl. the running sprint):
    the window of 5 reaches back over the gap, but only with the running sprint."""
    from sprintforecast.engine import gaps_in_window

    data, today = running_sprint([10.0, 12.0, None, 14.0, 11.0, 9.0])
    fc = build_forecast(data, today)
    series = [e.result.normalized_velocity.value for e in analysis.plan_basis(fc)]
    assert gaps_in_window(series, 5) == 1
    old = [e.result.normalized_velocity.value for e in fc.history()]
    assert gaps_in_window(old, 5) == 0  # this is how the old notice saw it: the gap dropped out


def test_few_samples_follows_what_is_drawn_from():
    data, today = running_sprint([10.0, 11.0, 12.0], window=5)  # 2 completed + running
    fc = build_forecast(data, today)
    assert analysis.sample_count(fc) == 3 and analysis.few_samples(fc)
    data, today = running_sprint([10.0, 11.0, 12.0, 9.0, 10.0, 12.0], window=5)
    assert not analysis.few_samples(build_forecast(data, today))
    data, today = running_sprint([10.0, 11.0, None], window=5)
    assert analysis.sample_count(build_forecast(data, today)) == 2


def test_reliability_note_counts_the_values_drawn_from():
    from sprintforecast.report import reliability_notes

    data, today = running_sprint([10.0, 11.0, 12.0], window=5)
    note = reliability_notes(build_forecast(data, today))[0]
    assert note.startswith("Wenig Daten: bisher nur 3 Sprints mit Velocity (ab 5 ")
    assert "Prognosefenster" not in note  # window 5: no addendum
    # Window 3 with 12 values still warns (fixed threshold 5), names both numbers (not "only 3"
    # for 12 recorded values) and explains why.
    data, today = running_sprint(
        [10.0, 11.0, 12.0, 9.0, 10.0, 12.0, 11.0, 10.0, 13.0, 9.0, 11.0, 10.0], window=3
    )
    note = reliability_notes(build_forecast(data, today))[0]
    assert note.startswith(
        "Wenig Daten: Die Spanne zieht aus nur 3 der 12 erfassten Sprints mit Velocity (ab 5 "
    )
    assert "bisher nur 3" not in note
    assert note.endswith(
        "auf 3 Sprints gestellt; mit einem größeren Fenster (Einstellungen) gehen mehr Werte in "
        "die Spanne ein."
    )


def test_reliability_note_without_window_hint_when_the_window_cuts_nothing():
    """Window 3, but only 2 (or exactly 3) values: a larger window would not help, the sentence
    names the values as before and says nothing about the window."""
    from sprintforecast.report import reliability_notes

    for velocities in ([10.0, 11.0], [10.0, 11.0, 12.0]):
        data, today = running_sprint(velocities, window=3)
        note = reliability_notes(build_forecast(data, today))[0]
        assert note.startswith(f"Wenig Daten: bisher nur {len(velocities)} Sprints mit Velocity")
        assert "Prognosefenster" not in note


def test_simulation_draws_from_the_running_sprints_review_value():
    data, today = running_sprint([10.0, 10.0, 40.0])
    result = analysis.completion(data, today, remaining=100, share=1.0, runs=200)
    assert result.samples == 3
    # without a review value only the two completed ones (10 each)
    data.sprints[-1].velocity = None
    without = analysis.completion(data, today, remaining=100, share=1.0, runs=200)
    assert without.samples == 2
    assert without.per_sprint == pytest.approx(10.0)
    assert result.cumulative != without.cumulative


def test_simulation_still_needs_two_values():
    """Minimum for the simulation (and the range): two values, the running sprint counts."""
    data, today = running_sprint([10.0])  # only the running sprint
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10) is None
    data, today = running_sprint([10.0, None])
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10) is None
    assert (
        analysis.band(build_forecast(data, today), build_forecast(data, today).upcoming()[0])
        is None
    )
    data, today = running_sprint([10.0, 10.0])  # one completed + running with a review value
    assert analysis.completion(data, today, remaining=20, share=1.0, runs=10).samples == 2
    # exactly two values also suffice for the range (here two completed ones)
    data, today = running_sprint([10.0, 10.0, None])
    fc = build_forecast(data, today)
    assert analysis.band(fc, future_entries(fc)[0]).samples == 2
