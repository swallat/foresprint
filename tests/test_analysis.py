# SPDX-License-Identifier: EUPL-1.2
from datetime import date, timedelta
from pathlib import Path

import pytest

from sprintforecast import analysis
from sprintforecast.forecast import build_forecast
from sprintforecast.model import Sprint, Team
from sprintforecast.storage import Repository, TeamData

TODAY = date(2026, 10, 15)


def team_with(velocities: list[float], capacity: float = 40, scope=None) -> TeamData:
    """Abgeschlossene Sprints mit fester Kapazität; Referenz 40 → n. Velocity = Velocity."""
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
                forecast_ist=v, scope_creep=None if scope is None else scope[i],
            )
        )  # fmt: skip
    return TeamData(team=team, sprints=sprints)


def test_band_uses_min_median_max_of_recent_sprints():
    data = team_with([30, 8, 10, 12, 20, 14])  # letzte 5: 8, 10, 12, 20, 14
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
    # konstante Velocity 10 bei Kapazität 40 = Referenz → 10 je Sprint, Roadmap 80 % → 8
    data = team_with([10] * 5)
    result = analysis.completion(data, TODAY, remaining=20, share=0.8, runs=500)
    future = result.sprints
    assert result.p50 == result.p85 == future[2]  # 8 + 8 + 8 ≥ 20 im 3. Sprint
    assert result.cumulative[2] == pytest.approx(1.0)
    assert analysis.completion(data, TODAY, remaining=20, share=1.0, runs=10).p85 == future[1]
    # Projektanteil 50 % vom Roadmap-Anteil → 4 je Sprint → im 5. Sprint fertig
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
    # Mit Personenliste kommt die Kapazität immer aus Kalender und Personen, nie aus dem Trend.
    assert result.trend_capacity_sprints == []
    no_people = Repository(data_dir).load("demo")
    no_people.people = []
    trend_only = analysis.completion(no_people, TODAY, remaining=40, share=0.8)
    assert "2026.23" in trend_only.trend_capacity_sprints  # Teams ohne Personenliste
    assert analysis.completion(data, TODAY, remaining=0, share=1) is None


def test_existing_values_are_unchanged(data_dir: Path):
    """Die Analysen ergänzen nur – Forecast PLAN, Roadmap, Kleinkram bleiben wie bisher."""
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    upcoming = {e.sprint.id: (e.result.plan, e.result.roadmap) for e in fc.upcoming()}
    # Demo mit Trend-Modus flat (Standard): konstanter Durchschnitt statt klassischer Trend
    assert upcoming["2026.21"] == (9.5, pytest.approx(7.6))
    assert upcoming["2026.22"] == (11.2, pytest.approx(8.96))


def test_buffer_hint_compares_on_the_same_base():
    """A9: Scope Creep ist auf das Commitment bezogen, der Kleinkram-Anteil auf den Forecast PLAN –
    verglichen wird auf dem Forecast PLAN."""
    data = team_with([10.0] * 6, scope=[0.3] * 6)
    fc = build_forecast(data, date(2026, 12, 31))
    hint = analysis.buffer_hint(fc)
    # Plan = Commitment (10): 30 % Scope Creep sind 30 % des Plans, mehr als die 20 % Kleinkram
    assert hint.average_scope_creep == pytest.approx(0.3)
    assert hint.average_late_share == pytest.approx(0.3) and hint.buffer_too_small
    for sprint in data.sprints:
        sprint.forecast_plan = 20.0  # beim Planning wurde doppelt so viel prognostiziert
    hint = analysis.buffer_hint(build_forecast(data, date(2026, 12, 31)))
    assert hint.average_scope_creep == pytest.approx(0.3)  # Eingabe unverändert
    assert hint.average_late_share == pytest.approx(0.15)  # 0,3 × 10 / 20
    assert not hint.buffer_too_small
